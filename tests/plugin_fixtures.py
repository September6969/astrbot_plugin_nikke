from __future__ import annotations

from types import SimpleNamespace

from astrbot_plugin_nikke.adapters.astrbot.collections import (
    AstrBotAdapterCollection,
    PluginCommandHandlers,
)
from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.cdk import CdkCommandHandler
from astrbot_plugin_nikke.application.commands.calendar import CalendarCommandHandler
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
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
    plugin.handlers = PluginCommandHandlers()
    plugin.adapters = AstrBotAdapterCollection(command=AstrBotCommandAdapter())
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
        render=lambda payload: plugin._try_t2i("calendar_schedule", payload),
        start_background_refresh=plugin._request_calendar_refresh,
    )
