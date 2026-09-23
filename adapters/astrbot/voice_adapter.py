# SPDX-License-Identifier: GPL-3.0-or-later
"""将 AstrBot 语音事件转换为领域上下文并映射回复。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ...features.voice.application import VoiceApplication, VoicePokeContext
from ...features.voice.audio import is_self_poke


class AstrBotVoiceAdapter:
    """只处理框架事件形状与消息组件，不选择角色或音频资源。"""

    SUPPORTED_POKE_PLATFORM = "aiocqhttp"

    def __init__(self, application: VoiceApplication) -> None:
        self._application = application

    @staticmethod
    def _event_value(event: AstrMessageEvent, name: str, default: Any = "") -> Any:
        value = getattr(event, name, None)
        if value is None:
            return default
        return value() if callable(value) else value

    def poke_context_from_event(
        self,
        event: AstrMessageEvent,
        *,
        closing: bool = False,
    ) -> VoicePokeContext:
        """把 OneBot notice 事件压缩成框架无关的判断字段。"""
        platform_name = str(self._event_value(event, "get_platform_name", "") or "")
        actor_id = str(self._event_value(event, "get_sender_id", "") or "")
        origin = str(self._event_value(event, "unified_msg_origin", "") or "")
        message = getattr(event, "message_obj", None)
        raw_message = getattr(message, "raw_message", None)
        return VoicePokeContext(
            platform_name=platform_name,
            actor_id=actor_id,
            sender_id=actor_id,
            unified_msg_origin=origin,
            supported_platform=platform_name == self.SUPPORTED_POKE_PLATFORM,
            is_self_poke=is_self_poke(raw_message),
            closing=closing,
        )

    async def voice_settings(
        self,
        event: AstrMessageEvent,
        action: str = "",
        value: str = "",
    ) -> AsyncIterator[Any]:
        """适配偏好命令的身份字段和纯文本回复。"""
        platform_name = str(self._event_value(event, "get_platform_name", "") or "")
        actor_id = str(self._event_value(event, "get_sender_id", "") or "")
        text = self._application.update_settings(
            platform_name,
            actor_id,
            action,
            value,
        )
        yield event.plain_result(text)

    async def on_poke(
        self,
        event: AstrMessageEvent,
        *,
        closing: bool = False,
    ) -> AsyncIterator[Any]:
        """将应用解析出的唯一音频路径包装为 AstrBot Record。"""
        context = self.poke_context_from_event(event, closing=closing)
        audio = await self._application.resolve_poke(context)
        if audio:
            from astrbot.api.message_components import Record

            yield event.chain_result([Record.fromFileSystem(str(audio))])
