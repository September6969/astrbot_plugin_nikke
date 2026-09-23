# SPDX-License-Identifier: GPL-3.0-or-later
"""服务容器与依赖装配工厂。

集中负责各 Resolver, Builder, Renderer 与外设服务的初始化与装配，
解耦 NikkePlugin 入口类的构造复杂度。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..features.account.application import AccountApplication
    from ..features.character.builder import CharacterCardBuilder
    from ..integrations.blablalink.client import BlaBlaClient
    from ..ui.primitives import CardRenderer
    from .asset_manager import AssetManager
    from .feedback import DelayedFeedbackManager

from ..features.announcement.application import AnnouncementApplication
from ..features.announcement.service import AnnouncementService
from ..features.calendar.service import CalendarService
from ..features.calendar.application import CalendarApplication
from ..features.campaign.application import CampaignApplication
from ..features.campaign.builder import CampaignHistoryBuilder
from ..features.campaign.stage_resolver import CampaignStageResolver
from ..features.cdk.service import CdkService
from ..features.character.application import CharacterApplication
from ..features.character.identity import CharacterDirectoryResolver
from ..integrations.character.stat_resources import CharacterStatResourceLoader
from ..features.daily.runner import DailyRunner
from ..features.guide.application import GuideApplication
from ..features.profile.builder import ProfileBuilder
from ..features.profile.application import ProfileApplication
from ..features.raid.application import RaidApplication
from ..features.raid.builder import UnionRaidBuilder
from ..features.tarot.service import TarotDataError, TarotService
from ..features.tower.application import TowerApplication
from ..features.voice.application import VoiceApplication
from ..integrations.web.service import BindingWebService
from ..ui.renderers import (
    CampaignHistoryRenderer,
    CharacterCardRenderer,
    ProfileCardRenderer,
    UnionRaidRenderer,
)
from .providers.account import create_account_application
from .providers.announcement import create_announcement_resources
from .providers.campaign import create_campaign_resources
from .providers.cdk import create_cdk_service
from .providers.character import create_character_resources
from .providers.content import create_guide_application, create_tower_application
from .providers.daily import create_daily_runner
from .providers.feedback import create_feedback_manager
from .providers.profile import create_profile_resources
from .providers.raid import create_raid_resources
from .providers.shared import create_shared_resources
from .providers.tarot import create_tarot_service
from .providers.voice import create_voice_application
from .providers.web import create_binding_web_service
from .lifecycle.coordinator import RuntimeCoordinator
from astrbot_plugin_nikke.core.storage import NikkeStore


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
    shared = create_shared_resources(plugin_dir, data_dir, config)
    extension_zip = shared.extension_zip
    store = shared.store
    account_application = create_account_application(store)
    client = shared.client
    renderer = shared.renderer
    user_aliases = (config or {}).get("custom_character_aliases")
    clock = lambda: datetime.now(timezone(timedelta(hours=8)))
    character = create_character_resources(
        plugin_dir,
        data_dir,
        account_reader=store,
        gateway=client,
        clock=clock,
        config=config or {},
    )
    campaign = create_campaign_resources(
        plugin_dir,
        data_dir,
        account_reader=store,
        gateway=client,
        asset_manager=shared.asset_manager,
        clock=clock,
    )
    profile = create_profile_resources(
        plugin_dir,
        data_dir,
        gateway=client,
        campaign_resolver=campaign.resolver,
        asset_manager=shared.asset_manager,
        clock=clock,
    )
    raid = create_raid_resources(
        plugin_dir,
        data_dir,
        account_reader=store,
        gateway=client,
        clock=clock,
    )
    asset_manager = shared.asset_manager
    cdk_service = create_cdk_service(client)
    runtime_coordinator = shared.runtime_coordinator
    feedback_manager = create_feedback_manager(runtime_coordinator)
    voice_application = create_voice_application(
        plugin_dir,
        data_dir,
        settings_store=store,
        task_factory=runtime_coordinator.create_task,
        config=config or {},
        directory_provider=directory_provider,
    )

    announcements = create_announcement_resources(data_dir, store=store)
    tarot = create_tarot_service(plugin_dir, data_dir)
    web = create_binding_web_service(store, client, extension_zip, config)
    daily_runner = create_daily_runner(client=client, store=store, config=config)
    guide_application = create_guide_application(plugin_dir)
    tower_application = create_tower_application(plugin_dir)

    return ServiceContainer(
        plugin_dir=plugin_dir,
        data_dir=data_dir,
        config=config,
        extension_zip=extension_zip,
        store=store,
        account_application=account_application,
        character_application=character.application,
        character_stat_resources=character.stat_resources,
        client=client,
        renderer=renderer,
        character_builder=character.builder,
        character_identity=character.identity,
        asset_manager=asset_manager,
        character_renderer=character.renderer,
        campaign_resolver=campaign.resolver,
        profile_builder=profile.builder,
        profile_application=profile.application,
        profile_renderer=profile.renderer,
        raid_builder=raid.builder,
        raid_application=raid.application,
        raid_renderer=raid.renderer,
        campaign_builder=campaign.builder,
        campaign_renderer=campaign.renderer,
        campaign_application=campaign.application,
        cdk_service=cdk_service,
        runtime_coordinator=runtime_coordinator,
        feedback_manager=feedback_manager,
        voice_application=voice_application,
        announcements=announcements.service,
        announcement_application=announcements.application,
        calendar=announcements.calendar,
        calendar_application=announcements.calendar_application,
        tarot=tarot,
        guide_application=guide_application,
        web=web,
        daily_runner=daily_runner,
        tower_application=tower_application,
    )
