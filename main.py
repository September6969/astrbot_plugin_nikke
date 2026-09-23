# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 综合助手 AstrBot 插件入口与框架注册。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# 确保 AstrBot 从插件目录加载时，包根目录可被导入。
_PACKAGE_DIR = Path(__file__).resolve().parent
_PLUGINS_DIR = str(_PACKAGE_DIR.parent)
if _PLUGINS_DIR not in sys.path:
    sys.path.insert(0, _PLUGINS_DIR)

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from ._version import PLUGIN_VERSION
from .adapters.astrbot.collections import AstrBotAdapterCollection, PluginCommandHandlers
from .adapters.astrbot.compatibility import require_supported_astrbot_version
from .adapters.astrbot.command_adapter import AstrBotCommandAdapter
from .adapters.astrbot.command_runtime import NikkeCommandRuntime, normalize_nikke_prefix
from .adapters.astrbot.runtime import AstrBotRuntimeAdapter
from .adapters.astrbot.voice_adapter import AstrBotVoiceAdapter
from .application.commands.account import AccountCommandHandler
from .application.commands.announcement import AnnouncementCommandHandler
from .application.commands.campaign import CampaignCommandHandler
from .application.commands.cdk import CdkCommandHandler
from .application.commands.calendar import CalendarCommandHandler
from .application.commands.daily import DailyCommandHandler
from .application.commands.guide import GuideCommandHandler
from .application.commands.profile import ProfileCommandHandler
from .application.commands.tarot import TarotCommandHandler
from .application.commands.tower import TowerCommandHandler
from .core.config import normalize_runtime_config
from .core.container import create_container

__all__ = ["NikkePlugin", "PLUGIN_VERSION", "normalize_nikke_prefix"]


class NikkePlugin(Star):
    """负责宿主装配、命令注册与生命周期入口的轻量插件外壳。"""

    def __init__(self, context: Context, config=None):
        require_supported_astrbot_version()
        super().__init__(context)
        self._command_runtime = NikkeCommandRuntime(self)
        self.context = context
        if hasattr(context, "astrbot_config") and isinstance(context.astrbot_config, dict):
            wake_prefixes = context.astrbot_config.setdefault("wake_prefix", ["/"])
            if isinstance(wake_prefixes, list) and "#" not in wake_prefixes:
                wake_prefixes.append("#")
        self.config = normalize_runtime_config(config)
        self.plugin_dir = _PACKAGE_DIR
        self.data_dir = Path("data") / "nikke"
        self._directory: list[dict[str, Any]] = []
        self.services = create_container(
            self.plugin_dir,
            self.data_dir,
            self.config,
            directory_provider=lambda: self._directory,
        )
        self.public_base_url = str(
            self.config.get("public_base_url", "https://nikke.irises777.xyz")
        ).rstrip("/")
        self.web_host = str(self.config.get("web_host", "0.0.0.0"))
        self.web_port = int(self.config.get("web_port", 6210))
        self.adapters = AstrBotAdapterCollection(
            command=AstrBotCommandAdapter(),
            voice=AstrBotVoiceAdapter(self.services.voice_application),
        )
        runtime = self._command_runtime
        self.runtime = AstrBotRuntimeAdapter(
            coordinator=self.services.runtime_coordinator,
            services=self.services,
            context=context,
            plugin_dir=self.plugin_dir,
            config=self.config,
            web_host=self.web_host,
            web_port=self.web_port,
            run_daily=runtime._run_all_daily,
            send_summary=runtime._send_summary,
            on_directory_loaded=runtime._apply_directory,
        )
        self.handlers = PluginCommandHandlers(
            account=AccountCommandHandler(
                application=self.services.account_application,
                public_base_url=self.public_base_url,
                allow_group_bind=bool(self.config.get("allow_group_bind", False)),
                runtime_health=runtime._account_runtime_health_details,
                render_manual_summary=runtime._render_manual_daily_summary,
            ),
            announcement=runtime._build_announcement_command_handler(),
            cdk=runtime._build_cdk_command_handler(),
            calendar=runtime._build_calendar_command_handler(),
            daily=runtime._build_daily_command_handler(),
            guide=GuideCommandHandler(self.services.guide_application),
            profile=ProfileCommandHandler(
                account_reader=self.services.store,
                application=self.services.profile_application,
                present=runtime._render_profile_dashboard,
            ),
            tarot=TarotCommandHandler(self.services.tarot),
            tower=TowerCommandHandler(self.services.tower_application),
        )
        self.runtime.start()

    @property
    def command_runtime(self) -> NikkeCommandRuntime:
        """延迟创建轻量路由器，兼容无需完整初始化的测试夹具。"""
        runtime = self.__dict__.get("_command_runtime")
        if runtime is None:
            runtime = NikkeCommandRuntime(self)
            self.__dict__["_command_runtime"] = runtime
        return runtime

    def __getattr__(self, name: str) -> Any:
        """保留旧插件实例方法的委托访问，不复制领域服务属性。"""
        runtime = self.__dict__.get("_command_runtime")
        if runtime is None:
            runtime = self.command_runtime
        if hasattr(type(runtime), name):
            return getattr(runtime, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    @staticmethod
    def _help_text(category: str = "", include_admin: bool = False) -> str:
        return NikkeCommandRuntime._help_text(category, include_admin)

    @filter.command("妮姬", alias={"nikke", "#妮姬", "#nikke"})
    async def nikke(
        self,
        event: AstrMessageEvent,
        command: str = "",
        arg1: str = "",
        arg2: str = "",
    ):
        """保留历史统一命令注册并薄委托给命令路由器。"""
        async for result in self.command_runtime.nikke(event, command, arg1, arg2):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_nikke_poke(self, event: AstrMessageEvent):
        """保留全消息事件注册并委托给语音事件适配器。"""
        async for result in self.adapters.voice.on_poke(
            event,
            closing=getattr(getattr(self, "runtime", None), "closing", False),
        ):
            yield result

    async def tarot_command(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.tarot, action=action, value=value
        ):
            yield result

    async def nikke_help(self, event: AstrMessageEvent, category: str = ""):
        async for result in self.command_runtime.nikke_help(event, category):
            yield result

    async def me(self, event: AstrMessageEvent):
        async for result in self.command_runtime.me(event):
            yield result

    async def query(self, event: AstrMessageEvent, kind: str = "", name: str = ""):
        async for result in self.command_runtime.query(event, kind, name):
            yield result

    async def progress(self, event: AstrMessageEvent):
        async for result in self.command_runtime.progress(event):
            yield result

    async def daily(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.daily, action=action, value=value
        ):
            yield result

    async def claim(self, event: AstrMessageEvent):
        async for result in self.daily(event):
            yield result

    async def cdk(self, event: AstrMessageEvent, code: str):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.cdk, operation="single", code=code
        ):
            yield result

    async def cdk_batch(self, event: AstrMessageEvent, raw_codes: str):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.cdk, operation="batch", codes=raw_codes
        ):
            yield result

    async def cdk_available(self, event: AstrMessageEvent):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.cdk, operation="available"
        ):
            yield result

    async def cdk_history(self, event: AstrMessageEvent):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.cdk, operation="history"
        ):
            yield result

    async def campaign(
        self, event: AstrMessageEvent, stage_str: str = "", mode_str: str = ""
    ):
        async for result in self.command_runtime.campaign(event, stage_str, mode_str):
            yield result

    async def event_schedule(self, event: AstrMessageEvent, horizon: str = ""):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.calendar, horizon=horizon
        ):
            yield result

    async def announcements_view(
        self,
        event: AstrMessageEvent,
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ):
        async for result in self.adapters.command.dispatch(
            event,
            self.handlers.announcement,
            operation="view",
            locale=locale or "",
            category=category or "",
            query=query or "",
        ):
            yield result

    async def announcement_deep_rescan(
        self, event: AstrMessageEvent, locale: str = "en"
    ):
        async for result in self.adapters.command.dispatch(
            event,
            self.handlers.announcement,
            operation="deep_rescan",
            locale=locale,
        ):
            yield result

    async def announcement_subscription(self, event: AstrMessageEvent, action: str):
        operation = "unsubscribe" if action == "取消订阅" else "subscribe"
        target = getattr(event, "unified_msg_origin", "") or ""
        async for result in self.adapters.command.dispatch(
            event,
            self.handlers.announcement,
            operation=operation,
            target=target,
        ):
            yield result

    async def guide(
        self, event: AstrMessageEvent, category: str = "", page: str = "1"
    ):
        async for result in self.adapters.command.dispatch(
            event, self.handlers.guide, category=category, page=page
        ):
            yield result

    async def account(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        async for result in self._dispatch_account_command(
            event, operation="account", action=action, value=value
        ):
            yield result

    async def bind(self, event: AstrMessageEvent):
        async for result in self._dispatch_account_command(event, operation="bind"):
            yield result

    async def unbind(self, event: AstrMessageEvent):
        async for result in self._dispatch_account_command(event, operation="unbind"):
            yield result

    async def status(self, event: AstrMessageEvent):
        async for result in self._dispatch_account_command(event, operation="status"):
            yield result

    async def push(self, event: AstrMessageEvent, state: str):
        async for result in self._dispatch_account_command(
            event, operation="push", state=state
        ):
            yield result

    async def admin(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        async for result in self._dispatch_account_command(
            event, operation="admin", action=action, value=value
        ):
            yield result

    async def group_set(self, event: AstrMessageEvent, action: str = "set"):
        async for result in self._dispatch_account_command(
            event, operation="group_set", action=action
        ):
            yield result

    async def schedule(self, event: AstrMessageEvent, clock: str):
        async for result in self._dispatch_account_command(
            event, operation="schedule", value=clock
        ):
            yield result

    async def summary(self, event: AstrMessageEvent, clock: str):
        async for result in self._dispatch_account_command(
            event, operation="summary", value=clock
        ):
            yield result

    async def run(self, event: AstrMessageEvent):
        async for result in self._dispatch_account_command(event, operation="run"):
            yield result

    async def health(self, event: AstrMessageEvent):
        async for result in self._dispatch_account_command(event, operation="health"):
            yield result

    async def voice_settings(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ):
        async for result in self.adapters.voice.voice_settings(event, action, value):
            yield result

    async def roster(self, event: AstrMessageEvent):
        async for result in self.command_runtime.roster(event):
            yield result

    async def character(self, event: AstrMessageEvent, name: str):
        async for result in self.command_runtime.character(event, name):
            yield result

    async def info(self, event: AstrMessageEvent, name: str):
        async for result in self.command_runtime.info(event, name):
            yield result

    async def union_raid(self, event: AstrMessageEvent):
        async for result in self.command_runtime.union_raid(event):
            yield result

    async def union_raid_ranking(self, event: AstrMessageEvent):
        async for result in self.command_runtime.union_raid_ranking(event):
            yield result

    async def union_raid_my(self, event: AstrMessageEvent):
        async for result in self.command_runtime.union_raid_my(event):
            yield result

    async def terminate(self):
        await self.close()

    async def close(self):
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            await runtime.close()
