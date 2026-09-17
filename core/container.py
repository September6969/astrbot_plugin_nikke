# SPDX-License-Identifier: GPL-3.0-or-later
"""服务容器与依赖装配工厂。

集中负责各 Resolver, Builder, Renderer 与外设服务的初始化与装配，
解耦 NikkePlugin 入口类的构造复杂度。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..features.announcement.delivery import AnnouncementDelivery
from ..features.announcement.service import AnnouncementService
from ..features.calendar.service import CalendarService
from ..features.campaign.builder import CampaignHistoryBuilder
from ..features.campaign.stage_resolver import CampaignStageResolver
from ..features.cdk.service import CdkService
from ..features.character.builder import CharacterCardBuilder
from ..features.character.identity import CharacterDirectoryResolver
from ..features.character.registries.costume import CostumeRegistry
from ..features.character.stat_resources import CharacterStatResourceLoader
from ..features.daily.runner import DailyRunner
from ..features.profile.builder import ProfileBuilder
from ..features.raid.builder import UnionRaidBuilder
from ..features.tarot.service import TarotDataError, TarotService
from ..features.tower.registry import TowerRegistry
from ..features.voice.audio import VoiceAudioCache
from ..features.voice.character_resolver import VoiceCharacterResolver
from ..features.voice.encoder import VoiceEncoder
from ..features.voice.mapping import VoiceMapRegistry
from ..features.voice.pipeline import VoicePipeline
from ..features.voice.provider import VoiceResourceProvider
from ..integrations.blablalink.client import BlaBlaClient
from ..integrations.spine.config import build_spine_renderer
from ..integrations.web.service import BindingWebService
from ..ui.primitives import CardRenderer
from ..ui.renderers import (
    CampaignHistoryRenderer,
    CharacterCardRenderer,
    ProfileCardRenderer,
    UnionRaidRenderer,
)
from .asset_manager import AssetManager
from .feedback import DelayedFeedbackManager
from .privacy import safe_exception_message
from .storage import NikkeStore

logger = logging.getLogger("astrbot_plugin_nikke")


@dataclass
class ServiceContainer:
    """管理所有领域服务、存储与渲染器依赖的容器实例。"""

    plugin_dir: Path
    data_dir: Path
    config: dict[str, Any]
    extension_zip: Path
    store: NikkeStore
    character_stat_resources: CharacterStatResourceLoader
    client: BlaBlaClient
    renderer: CardRenderer
    character_builder: CharacterCardBuilder
    character_identity: CharacterDirectoryResolver
    asset_manager: AssetManager
    character_renderer: CharacterCardRenderer
    campaign_resolver: CampaignStageResolver
    profile_builder: ProfileBuilder
    profile_renderer: ProfileCardRenderer
    raid_builder: UnionRaidBuilder
    raid_renderer: UnionRaidRenderer
    campaign_builder: CampaignHistoryBuilder
    campaign_renderer: CampaignHistoryRenderer
    cdk_service: CdkService
    feedback_manager: DelayedFeedbackManager
    voice_mapping: VoiceMapRegistry
    voice_character_resolver: VoiceCharacterResolver
    costume_registry: CostumeRegistry
    voice_audio: VoiceAudioCache
    voice_provider: VoiceResourceProvider
    voice_encoder: VoiceEncoder | None
    voice_pipeline: VoicePipeline | None
    announcements: AnnouncementService
    announcement_delivery: AnnouncementDelivery
    calendar: CalendarService
    tarot: TarotService | None
    web: BindingWebService
    daily_runner: DailyRunner
    tower_registry: TowerRegistry | None = None


def create_container(
    plugin_dir: Path,
    data_dir: Path,
    config: dict[str, Any],
) -> ServiceContainer:
    """装配插件依赖，建立各服务之间的依赖注入关系。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    extension_zip = data_dir / "nikke-bind-extension.zip"
    store = NikkeStore(data_dir)
    character_stat_resources = CharacterStatResourceLoader(
        data_dir / "cache" / "character-stats"
    )
    client = BlaBlaClient(
        int(config.get("request_timeout", 20)),
        lambda message: logger.info(f"[NIKKE诊断] {message}"),
    )
    renderer = CardRenderer(data_dir / "cards", plugin_dir / "fonts")
    character_builder = CharacterCardBuilder(
        unknown_ol_inventory_path=data_dir / "ol_unknown_inventory.json",
    )
    user_aliases = (config or {}).get("custom_character_aliases")
    try:
        character_identity = CharacterDirectoryResolver(
            plugin_dir / "assets" / "character_aliases.json",
            user_aliases=user_aliases,
        )
    except ValueError as err:
        logger.error("[NIKKE] 用户自定义别名配置错误，已忽略自定义别名：%s", err)
        character_identity = CharacterDirectoryResolver(
            plugin_dir / "assets" / "character_aliases.json",
        )

    spine_budget = (config or {}).get("spine_budget_seconds", 20.0)
    asset_manager = AssetManager(
        data_dir / "cache",
        plugin_dir / "assets",
        remote=True,
        spine_renderer=build_spine_renderer(data_dir / "cache", config),
        spine_budget_seconds=float(spine_budget) if isinstance(spine_budget, (int, float)) and spine_budget > 0 else 20.0,
        spine_manifest_path=data_dir / "spine-manifest.json",
        spine_rendered_dir=data_dir / "spine-rendered",
    )
    character_renderer = CharacterCardRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        asset_manager,
    )
    campaign_resolver = CampaignStageResolver.from_file(plugin_dir / "assets" / "campaign_stages.json")
    profile_builder = ProfileBuilder(campaign_resolver=campaign_resolver)
    profile_renderer = ProfileCardRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        currency_icon_provider=asset_manager.get_currency_icon,
    )
    raid_builder = UnionRaidBuilder()
    raid_renderer = UnionRaidRenderer(data_dir / "cards", plugin_dir / "fonts")
    campaign_builder = CampaignHistoryBuilder()
    campaign_renderer = CampaignHistoryRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        asset_manager,
    )
    cdk_service = CdkService(client)
    feedback_manager = DelayedFeedbackManager(1.5)
    voice_mapping = VoiceMapRegistry(plugin_dir / "assets" / "voice_poke_map.json")
    for error in voice_mapping.errors:
        logger.warning("[NIKKE] 语音映射清单校验失败：%s", error)
    try:
        voice_character_resolver = VoiceCharacterResolver(
            plugin_dir / "assets",
            user_aliases=user_aliases,
        )
    except ValueError as err:
        logger.error("[NIKKE] 语音用户自定义别名配置错误，已忽略自定义别名：%s", err)
        voice_character_resolver = VoiceCharacterResolver(
            plugin_dir / "assets",
        )

    costume_registry = CostumeRegistry(plugin_dir / "assets")
    voice_audio = VoiceAudioCache(plugin_dir / "assets" / "voices", data_dir / "voice_cache")
    voice_provider = VoiceResourceProvider(data_dir / "voice_cache")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    voice_encoder = VoiceEncoder(data_dir / "voice_cache", ffmpeg, ffprobe) if ffmpeg and ffprobe else None
    voice_pipeline = VoicePipeline(voice_provider, voice_encoder) if voice_encoder else None

    announcements = AnnouncementService(data_dir / "announcements")
    announcement_delivery = AnnouncementDelivery(store)
    calendar = CalendarService(data_dir / "calendar", announcement_service=announcements)
    try:
        tarot = TarotService(
            plugin_dir,
            data_dir / "tarot",
            deck_mode="auto",
            rotate_reversed=True,
        )
    except (OSError, ValueError, TarotDataError) as exc:
        logger.warning("[NIKKE] 塔罗服务初始化失败：%s", safe_exception_message(exc))
        tarot = None

    public_base_url = str(
        config.get("public_base_url", "https://nikke.irises777.xyz")
    ).rstrip("/")
    web = BindingWebService(
        store,
        client,
        extension_zip,
        str(config.get("binding_api_key", "")),
        public_base_url=public_base_url,
    )
    daily_runner = DailyRunner(client=client, store=store, config=config)

    return ServiceContainer(
        plugin_dir=plugin_dir,
        data_dir=data_dir,
        config=config,
        extension_zip=extension_zip,
        store=store,
        character_stat_resources=character_stat_resources,
        client=client,
        renderer=renderer,
        character_builder=character_builder,
        character_identity=character_identity,
        asset_manager=asset_manager,
        character_renderer=character_renderer,
        campaign_resolver=campaign_resolver,
        profile_builder=profile_builder,
        profile_renderer=profile_renderer,
        raid_builder=raid_builder,
        raid_renderer=raid_renderer,
        campaign_builder=campaign_builder,
        campaign_renderer=campaign_renderer,
        cdk_service=cdk_service,
        feedback_manager=feedback_manager,
        voice_mapping=voice_mapping,
        voice_character_resolver=voice_character_resolver,
        costume_registry=costume_registry,
        voice_audio=voice_audio,
        voice_provider=voice_provider,
        voice_encoder=voice_encoder,
        voice_pipeline=voice_pipeline,
        announcements=announcements,
        announcement_delivery=announcement_delivery,
        calendar=calendar,
        tarot=tarot,
        web=web,
        daily_runner=daily_runner,
        tower_registry=None,
    )
