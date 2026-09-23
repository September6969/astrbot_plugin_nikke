# SPDX-License-Identifier: GPL-3.0-or-later
"""服务容器与依赖装配工厂。

集中负责各 Resolver, Builder, Renderer 与外设服务的初始化与装配，
解耦 NikkePlugin 入口类的构造复杂度。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .._version import PLUGIN_VERSION
from ..features.account.application import AccountApplication
from ..features.announcement.application import AnnouncementApplication
from ..features.announcement.delivery import AnnouncementDelivery
from ..features.announcement.service import AnnouncementService
from ..features.calendar.service import CalendarService
from ..features.calendar.application import CalendarApplication
from ..features.campaign.application import CampaignApplication
from ..features.campaign.builder import CampaignHistoryBuilder
from ..features.campaign.stage_resolver import CampaignStageResolver
from ..features.cdk.service import CdkService
from ..features.character.application import CharacterApplication
from ..features.character.composition import create_character_card_builder
from ..features.character.identity import CharacterDirectoryResolver
from ..features.character.registries.costume import CostumeRegistry
from ..features.character.stat_resources import CharacterStatResourceLoader
from ..features.daily.runner import DailyRunner
from ..features.guide.application import GuideApplication
from ..features.profile.builder import ProfileBuilder
from ..features.profile.application import ProfileApplication
from ..features.raid.application import RaidApplication
from ..features.raid.builder import UnionRaidBuilder
from ..features.tarot.service import TarotDataError, TarotService
from ..features.tower.application import TowerApplication
from ..features.voice.audio import VoiceAudioCache
from ..features.voice.application import VoiceApplication
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
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from .feedback import DelayedFeedbackManager
from .lifecycle.coordinator import RuntimeCoordinator
from .privacy import safe_exception_message
from astrbot_plugin_nikke.core.storage import NikkeStore

logger = logging.getLogger("astrbot_plugin_nikke")


@dataclass
class ServiceContainer:
    """管理所有领域服务、存储与渲染器依赖的容器实例。"""

    plugin_dir: Path
    data_dir: Path
    config: dict[str, Any]
    extension_zip: Path
    store: NikkeStore
    account_application: AccountApplication
    character_application: CharacterApplication
    character_stat_resources: CharacterStatResourceLoader
    client: BlaBlaClient
    renderer: CardRenderer
    character_builder: CharacterCardBuilder
    character_identity: CharacterDirectoryResolver
    asset_manager: AssetManager
    character_renderer: CharacterCardRenderer
    campaign_resolver: CampaignStageResolver
    profile_builder: ProfileBuilder
    profile_application: ProfileApplication
    profile_renderer: ProfileCardRenderer
    raid_builder: UnionRaidBuilder
    raid_application: RaidApplication
    raid_renderer: UnionRaidRenderer
    campaign_builder: CampaignHistoryBuilder
    campaign_renderer: CampaignHistoryRenderer
    campaign_application: CampaignApplication
    cdk_service: CdkService
    runtime_coordinator: RuntimeCoordinator
    feedback_manager: DelayedFeedbackManager
    voice_application: VoiceApplication
    announcements: AnnouncementService
    announcement_application: AnnouncementApplication
    calendar: CalendarService
    calendar_application: CalendarApplication
    tarot: TarotService | None
    guide_application: GuideApplication
    web: BindingWebService
    daily_runner: DailyRunner
    tower_application: TowerApplication


def create_container(
    plugin_dir: Path,
    data_dir: Path,
    config: dict[str, Any],
    *,
    directory_provider: Callable[[], Any] | None = None,
) -> ServiceContainer:
    """装配插件依赖，建立各服务之间的依赖注入关系。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    extension_zip = data_dir / "nikke-bind-extension.zip"
    store = NikkeStore(data_dir)
    account_application = AccountApplication(store)
    character_stat_resources = CharacterStatResourceLoader(
        data_dir / "cache" / "character-stats"
    )
    client = BlaBlaClient(
        int(config.get("request_timeout", 20)),
        lambda message: logger.info(f"[NIKKE诊断] {message}"),
    )
    renderer = CardRenderer(data_dir / "cards", plugin_dir / "fonts")
    character_builder = create_character_card_builder(
        plugin_dir,
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
    character_application = CharacterApplication(
        account_reader=store,
        gateway=client,
        identity=character_identity,
        stat_resources=character_stat_resources,
        card_builder=character_builder,
        clock=lambda: datetime.now(timezone(timedelta(hours=8))),
        plugin_version=PLUGIN_VERSION,
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
    )
    campaign_resolver = CampaignStageResolver.from_file(plugin_dir / "assets" / "campaign_stages.json")
    profile_builder = ProfileBuilder(campaign_resolver=campaign_resolver)
    profile_application = ProfileApplication(
        gateway=client,
        builder=profile_builder,
        clock=lambda: datetime.now(timezone(timedelta(hours=8))),
        plugin_version=PLUGIN_VERSION,
    )
    profile_renderer = ProfileCardRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        currency_icon_provider=asset_manager.get_currency_icon,
    )
    raid_builder = UnionRaidBuilder()
    raid_application = RaidApplication(
        account_reader=store,
        gateway=client,
        builder=raid_builder,
        clock=lambda: datetime.now(timezone(timedelta(hours=8))),
        plugin_version=PLUGIN_VERSION,
    )
    raid_renderer = UnionRaidRenderer(data_dir / "cards", plugin_dir / "fonts")
    campaign_builder = CampaignHistoryBuilder()
    campaign_renderer = CampaignHistoryRenderer(
        data_dir / "cards",
        plugin_dir / "fonts",
        asset_manager,
    )
    campaign_application = CampaignApplication(
        resolver=campaign_resolver,
        gateway=client,
        account_reader=store,
        builder=campaign_builder,
        clock=lambda: datetime.now(timezone(timedelta(hours=8))),
        plugin_version=PLUGIN_VERSION,
    )
    cdk_service = CdkService(client)
    runtime_coordinator = RuntimeCoordinator()
    feedback_manager = DelayedFeedbackManager(
        1.5,
        task_factory=runtime_coordinator.create_task,
    )
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
    voice_provider = VoiceResourceProvider(
        data_dir / "voice_cache",
        task_factory=runtime_coordinator.create_task,
    )
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    voice_encoder = VoiceEncoder(data_dir / "voice_cache", ffmpeg, ffprobe) if ffmpeg and ffprobe else None
    voice_pipeline = (
        VoicePipeline(
            voice_provider,
            voice_encoder,
            task_factory=runtime_coordinator.create_task,
        )
        if voice_encoder
        else None
    )
    voice_application = VoiceApplication(
        store=store,
        character_resolver=voice_character_resolver,
        costume_registry=costume_registry,
        audio_cache=voice_audio,
        mapping_registry=voice_mapping,
        pipeline=voice_pipeline,
        provider=voice_provider,
        encoder=voice_encoder,
        dynamic_enabled=lambda: bool(config.get("voice_dynamic_enabled", True)),
        directory_provider=directory_provider,
    )

    announcements = AnnouncementService(data_dir / "announcements")
    announcement_delivery = AnnouncementDelivery(store)
    calendar = CalendarService(data_dir / "calendar", announcement_service=announcements)
    calendar_application = calendar.application
    announcement_application = AnnouncementApplication(
        announcements=announcements,
        delivery=announcement_delivery,
        deadline_selector=calendar_application.reminder_deadlines,
    )
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
    guide_application = GuideApplication(plugin_dir / "assets" / "guides")
    tower_application = TowerApplication(
        plugin_dir / "assets" / "tower_floors.json"
    )

    return ServiceContainer(
        plugin_dir=plugin_dir,
        data_dir=data_dir,
        config=config,
        extension_zip=extension_zip,
        store=store,
        account_application=account_application,
        character_application=character_application,
        character_stat_resources=character_stat_resources,
        client=client,
        renderer=renderer,
        character_builder=character_builder,
        character_identity=character_identity,
        asset_manager=asset_manager,
        character_renderer=character_renderer,
        campaign_resolver=campaign_resolver,
        profile_builder=profile_builder,
        profile_application=profile_application,
        profile_renderer=profile_renderer,
        raid_builder=raid_builder,
        raid_application=raid_application,
        raid_renderer=raid_renderer,
        campaign_builder=campaign_builder,
        campaign_renderer=campaign_renderer,
        campaign_application=campaign_application,
        cdk_service=cdk_service,
        runtime_coordinator=runtime_coordinator,
        feedback_manager=feedback_manager,
        voice_application=voice_application,
        announcements=announcements,
        announcement_application=announcement_application,
        calendar=calendar,
        calendar_application=calendar_application,
        tarot=tarot,
        guide_application=guide_application,
        web=web,
        daily_runner=daily_runner,
        tower_application=tower_application,
    )
