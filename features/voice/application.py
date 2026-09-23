# SPDX-License-Identifier: GPL-3.0-or-later
"""语音偏好与戳一戳音源解析的应用边界。"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .audio import VoicePreference
from .ports import VoiceSettingsStore


@dataclass(frozen=True, slots=True)
class VoicePokeContext:
    """由平台适配器归一化后的戳一戳上下文。"""

    platform_name: str
    actor_id: str
    sender_id: str
    unified_msg_origin: str
    supported_platform: bool
    is_self_poke: bool
    closing: bool = False


class VoiceApplication:
    """集中处理语音设置、精确资源选择与资源关闭。

    戳一戳冷却只保护单个应用实例，不构成跨进程协调。
    """

    COOLDOWN_SECONDS = 10.0

    def __init__(
        self,
        *,
        store: VoiceSettingsStore,
        character_resolver: Any,
        costume_registry: Any,
        audio_cache: Any,
        mapping_registry: Any,
        pipeline: Any = None,
        provider: Any = None,
        encoder: Any = None,
        dynamic_enabled: bool | Callable[[], bool] = True,
        directory_provider: Callable[[], Iterable[dict[str, Any]]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._character_resolver = character_resolver
        self._costume_registry = costume_registry
        self._audio_cache = audio_cache
        self._mapping_registry = mapping_registry
        self._pipeline = pipeline
        self._provider = provider
        self._encoder = encoder
        self._dynamic_enabled = dynamic_enabled
        self._directory_provider = directory_provider or (lambda: ())
        self._monotonic = monotonic
        self._poke_cooldowns: dict[tuple[str, str, str], float] = {}
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed = False

    def update_settings(
        self,
        platform_name: str,
        actor_id: str,
        action: str = "",
        value: str = "",
    ) -> str:
        """更新当前用户的语音偏好，并返回可展示的确认文本。"""
        platform = str(platform_name or "").strip()
        actor = str(actor_id or "").strip()
        if not platform or not actor:
            return "无法识别当前用户，语音设置未修改。"

        key = f"{platform}:{actor}"
        preference = VoicePreference.load(self._store, key)
        action_clean = str(action or "").strip()
        value_clean = str(value or "").strip()

        if action_clean in {"开", "关"}:
            preference.enabled = action_clean == "开"
        elif action_clean == "语言" and value_clean.lower() in {"ja", "en", "ko"}:
            preference.locale = value_clean.lower()
            preference.explicit_locale = True
        elif action_clean == "角色":
            if not value_clean:
                return "用法：/妮姬 语音 角色 <角色名|英文名|代码>"
            resolved_character = self._character_resolver.resolve(
                value_clean,
                self._directory_provider(),
            )
            if not resolved_character:
                return f"未找到妮姬：{value_clean}"
            preference.character = resolved_character
            preference.skin = "default"
            preference.spine_asset_id = ""
        elif action_clean in {"服装", "皮肤", "skin", "costume"}:
            resource_id = self._character_resolver.get_resource_id(preference.character)
            if not value_clean:
                available = self._costume_registry.get_costumes_for_resource(resource_id)
                if available:
                    lines = [f"当前角色 {preference.character} 可用已核验服装："]
                    lines.extend(
                        f"- {costume.costume_id}：{costume.costume_name} ({costume.spine_asset_id})"
                        for costume in available
                    )
                    lines.append("用法：/妮姬 语音 服装 <默认|服装ID|服装名>")
                    return "\n".join(lines)
                return (
                    f"当前角色 {preference.character} 暂无可切换的已核验服装。\n"
                    "用法：/妮姬 语音 服装 默认"
                )
            if resource_id is None:
                return "当前角色身份未核验，无法切换服装。"

            result = self._costume_registry.resolve(
                value_clean,
                expected_resource_id=resource_id,
            )
            if not result.ok:
                return result.message
            if result.status == "RESET_DEFAULT":
                preference.skin = "default"
                preference.spine_asset_id = ""
            else:
                preference.skin = result.costume.costume_id
                preference.spine_asset_id = result.costume.spine_asset_id
        elif action_clean:
            return (
                "用法：/妮姬 语音 开|关，语音 语言 ja|en|ko，语音 角色 <角色名>，"
                "语音 服装 <默认|服装ID|服装名>"
            )

        preference.save(self._store, key)
        skin_text = f" · {preference.skin}" if preference.skin != "default" else ""
        return (
            f"互动语音：{'开启' if preference.enabled else '关闭'} · "
            f"{preference.character}{skin_text} · {preference.locale}。"
        )

    async def resolve_poke(self, context: VoicePokeContext) -> Path | None:
        """解析一个已适配戳一戳事件的本地或精确映射音源。"""
        if (
            self._closed
            or self._closing
            or context.closing
            or not context.supported_platform
            or not context.is_self_poke
            or not context.platform_name
            or not context.actor_id
        ):
            return None

        preference = VoicePreference.load(
            self._store,
            f"{context.platform_name}:{context.actor_id}",
        )
        if not preference.enabled:
            return None

        now = self._monotonic()
        cooldown_key = (
            context.platform_name,
            context.sender_id,
            context.unified_msg_origin,
        )
        if now - self._poke_cooldowns.get(cooldown_key, float("-inf")) < self.COOLDOWN_SECONDS:
            return None
        self._poke_cooldowns = {
            key: stamp
            for key, stamp in self._poke_cooldowns.items()
            if now - stamp < self.COOLDOWN_SECONDS
        }
        self._poke_cooldowns[cooldown_key] = now

        try:
            audio = await self._audio_cache.resolve(preference)
        except (OSError, ValueError, asyncio.TimeoutError):
            audio = None
        if audio:
            return Path(audio)

        enabled = self._dynamic_enabled
        if not (enabled() if callable(enabled) else enabled) or self._pipeline is None:
            return None

        canonical_spine = preference.spine_asset_id or None
        resolver = self._mapping_registry
        if resolver is None:
            return None
        if hasattr(resolver, "resolve_poke"):
            mapping = resolver.resolve_poke(
                preference.character,
                preference.skin,
                preference.locale,
                spine_asset_id=canonical_spine,
            )
        else:
            mapping = resolver.resolve(
                preference.character,
                preference.skin,
                preference.locale,
                spine_asset_id=canonical_spine,
            )
            if mapping is None and canonical_spine:
                mapping = resolver.resolve_by_spine_asset(
                    canonical_spine,
                    preference.locale,
                )
        if mapping is None:
            return None
        try:
            audio = await self._pipeline.resolve(
                mapping.map_key,
                mapping.speech_id,
                mapping.locale,
                budget=4,
            )
        except (OSError, ValueError, asyncio.TimeoutError):
            audio = None
        return Path(audio) if audio else None

    async def close(self) -> None:
        """关闭语音资源；VoicePipeline 是 provider/encoder 的唯一所有者。"""
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            if self._pipeline is not None:
                await self._pipeline.close()
                self._closed = True
                return
            for resource in (self._provider, self._encoder):
                close = getattr(resource, "close", None)
                if close is None:
                    continue
                result = close()
                if inspect.isawaitable(result):
                    await result
            self._closed = True
