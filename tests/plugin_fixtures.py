from __future__ import annotations

from types import SimpleNamespace

from astrbot_plugin_nikke.adapters.astrbot.collections import (
    AstrBotAdapterCollection,
    PluginCommandHandlers,
)
from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.adapters.astrbot.command_presentation import (
    AstrBotCommandPresentation,
)
from astrbot_plugin_nikke.application.commands.cdk import CdkCommandHandler
from astrbot_plugin_nikke.application.commands.calendar import CalendarCommandHandler
from astrbot_plugin_nikke.application.commands.campaign import CampaignCommandHandler
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.application.commands.raid import RaidCommandHandler
from astrbot_plugin_nikke.application.commands.tarot import TarotCommandHandler
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder


def make_plugin_shell() -> NikkePlugin:
    """创建测试用宿主壳，依赖通过正式集合字段显式注入。"""
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.services = SimpleNamespace()
    plugin.config = {}
    plugin.context = SimpleNamespace()
    plugin.handlers = PluginCommandHandlers()
    plugin.adapters = AstrBotAdapterCollection(command=AstrBotCommandAdapter())
    plugin.presentation = AstrBotCommandPresentation(
        services=plugin.services,
        config=lambda: plugin.config,
        html_render=lambda: getattr(plugin, "html_render", None),
        context=plugin.context,
    )
    return plugin


def inject_cdk_handler(plugin: NikkePlugin) -> None:
    """按当前测试服务显式装配 CDK handler，不依赖插件入口的延迟创建。"""
    services = plugin.services
    service = getattr(services, "cdk_service", None)
    if service is None:
        service = CdkService(services.client)
    plugin.handlers.cdk = CdkCommandHandler(
        account_reader=services.store,
        store=services.store,
        client=getattr(services, "client", None),
        service=service,
        config=plugin.config,
    )


def inject_daily_handler(plugin: NikkePlugin) -> None:
    """按当前测试服务显式装配 Daily handler 与 runner。"""
    services = plugin.services
    store = services.store
    runner = getattr(services, "daily_runner", None)
    if runner is None:
        runner = DailyRunner(
            client=getattr(services, "client", None),
            store=store,
            config=plugin.config,
        )
    services.daily_runner = runner

    async def send_summary(_target: str, _path: str) -> None:
        return None

    plugin.handlers.daily = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=getattr(services, "client", None),
        config=plugin.config,
        render_summary=lambda _rows: "",
        send_summary=send_summary,
    )


def inject_tarot_handler(plugin: NikkePlugin) -> None:
    """显式把测试提供的唯一塔罗服务交给命令 handler。"""
    plugin.handlers.tarot = TarotCommandHandler(plugin.services.tarot)


def inject_calendar_handler(plugin: NikkePlugin) -> None:
    """显式装配 Calendar 命令，用 fake 或容器服务替代完整插件。"""
    services = plugin.services
    application = getattr(services, "calendar_application", None)
    if application is None:
        calendar = getattr(services, "calendar", None)
        application = (
            calendar.application
            if isinstance(calendar, CalendarService)
            else CalendarApplication(calendar)
        )
        services.calendar_application = application
    plugin.handlers.calendar = CalendarCommandHandler(
        application=application,
        payload_builder=CalendarT2IPayloadBuilder(),
        render=lambda payload: plugin.presentation.try_t2i(
            "calendar_schedule", payload
        ),
        start_background_refresh=lambda: (
            plugin.runtime.request_calendar_refresh()
            if getattr(plugin, "runtime", None) is not None
            else None
        ),
    )


def _feedback_starter(plugin: NikkePlugin):
    manager = getattr(plugin.services, "feedback_manager", None)
    if manager is None:
        return None
    return lambda _context, _message: manager.start_delayed_feedback(lambda: None)


def inject_profile_handler(plugin: NikkePlugin) -> None:
    invalidate_cookie = getattr(
        plugin.services.store, "mark_cookie_invalid", lambda _actor_id: None
    )
    plugin.handlers.profile = ProfileCommandHandler(
        account_reader=plugin.services.store,
        application=plugin.services.profile_application,
        present=plugin.presentation.render_profile,
        invalidate_cookie=invalidate_cookie,
        start_feedback=_feedback_starter(plugin),
    )


def inject_character_handler(plugin: NikkePlugin) -> None:
    store = getattr(plugin.services, "store", None)
    invalidate_cookie = getattr(
        store, "mark_cookie_invalid", lambda _actor_id: None
    )
    plugin.handlers.character = CharacterCommandHandler(
        application=plugin.services.character_application,
        directory=lambda: tuple(getattr(plugin, "_directory", ())),
        render_roster=plugin.presentation.render_roster,
        render_card=plugin.presentation.render_character_card,
        render_info=plugin.presentation.render_character_info,
        invalidate_cookie=invalidate_cookie,
        start_feedback=_feedback_starter(plugin),
    )


def inject_raid_handler(plugin: NikkePlugin) -> None:
    store = getattr(plugin.services, "store", None)
    invalidate_cookie = getattr(
        store, "mark_cookie_invalid", lambda _actor_id: None
    )
    plugin.handlers.raid = RaidCommandHandler(
        application=plugin.services.raid_application,
        render_overview=plugin.presentation.render_raid_overview,
        render_ranking=plugin.presentation.render_raid_ranking,
        invalidate_cookie=invalidate_cookie,
        start_feedback=_feedback_starter(plugin),
    )


def inject_campaign_handler(plugin: NikkePlugin) -> None:
    store = getattr(plugin.services, "store", None)
    invalidate_cookie = getattr(
        store, "mark_cookie_invalid", lambda _actor_id: None
    )
    plugin.handlers.campaign = CampaignCommandHandler(
        application=plugin.services.campaign_application,
        present=plugin.presentation.render_campaign_record,
        invalidate_cookie=invalidate_cookie,
        start_feedback=_feedback_starter(plugin),
    )
