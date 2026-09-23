# SPDX-License-Identifier: GPL-3.0-or-later
"""语音 feature 的资源与生命周期 provider。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable

from ...features.character.registries.costume import CostumeRegistry
from ...features.voice.application import VoiceApplication
from ...features.voice.audio import VoiceAudioCache
from ...features.voice.character_resolver import VoiceCharacterResolver
from ...features.voice.encoder import VoiceEncoder
from ...features.voice.mapping import VoiceMapRegistry
from ...features.voice.pipeline import VoicePipeline
from ...features.voice.ports import VoiceSettingsStore
from ...integrations.voice.resource_provider import VoiceResourceProvider

logger = logging.getLogger("astrbot_plugin_nikke")


def create_voice_application(
    plugin_dir: Path,
    data_dir: Path,
    *,
    settings_store: VoiceSettingsStore,
    task_factory: Callable[..., Any],
    config: dict[str, Any],
    directory_provider: Callable[[], Iterable[dict[str, Any]]] | None = None,
) -> VoiceApplication:
    """创建唯一语音应用；存储端口和后台任务入口由 composition root 注入。"""
    assets_dir = plugin_dir / "assets"
    voice_mapping = VoiceMapRegistry(assets_dir / "voice_poke_map.json")
    for error in voice_mapping.errors:
        logger.warning("[NIKKE] 语音映射清单校验失败：%s", error)
    user_aliases = config.get("custom_character_aliases")
    try:
        character_resolver = VoiceCharacterResolver(
            assets_dir, user_aliases=user_aliases
        )
    except ValueError as err:
        logger.error(
            "[NIKKE] 语音用户自定义别名配置错误，已忽略自定义别名：%s", err
        )
        character_resolver = VoiceCharacterResolver(assets_dir)

    costume_registry = CostumeRegistry(assets_dir)
    voice_cache_dir = data_dir / "voice_cache"
    audio_cache = VoiceAudioCache(assets_dir / "voices", voice_cache_dir)
    provider = VoiceResourceProvider(voice_cache_dir, task_factory=task_factory)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    encoder = VoiceEncoder(voice_cache_dir, ffmpeg, ffprobe) if ffmpeg and ffprobe else None
    pipeline = (
        VoicePipeline(provider, encoder, task_factory=task_factory)
        if encoder
        else None
    )
    return VoiceApplication(
        store=settings_store,
        character_resolver=character_resolver,
        costume_registry=costume_registry,
        audio_cache=audio_cache,
        mapping_registry=voice_mapping,
        pipeline=pipeline,
        provider=provider,
        encoder=encoder,
        dynamic_enabled=lambda: bool(config.get("voice_dynamic_enabled", True)),
        directory_provider=directory_provider,
    )
