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
from .adapters.astrbot.command_presentation import AstrBotCommandPresentation
from .adapters.astrbot.command_parser import HASH_PREFIX_PATTERN, parse_nikke_message
from .adapters.astrbot.command_runtime import NikkeCommandRuntime, normalize_nikke_prefix
from .adapters.astrbot.runtime import AstrBotRuntimeAdapter
from .adapters.astrbot.voice_adapter import AstrBotVoiceAdapter
from .application.commands.account import AccountCommandHandler
from .application.commands.arena import ArenaCommandHandler
from .application.commands.announcement import AnnouncementCommandHandler
from .application.commands.campaign import CampaignCommandHandler
from .application.commands.character import CharacterCommandHandler
from .application.commands.cdk import CdkCommandHandler
from .application.commands.calendar import CalendarCommandHandler
from .application.commands.daily import DailyCommandHandler
from .application.commands.community_automation import CommunityAutomationHandler
from .application.commands.guide import GuideCommandHandler
from .application.commands.profile import ProfileCommandHandler
from .application.commands.raid import RaidCommandHandler
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
        self.context = context
        # 不修改宿主全局 wake_prefix；#妮姬 / #nikke 由插件级 regex 入口 nikke_hash_prefix 处理。
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
        self.presentation = AstrBotCommandPresentation(
            services=self.services,
            html_render=lambda: getattr(self, "html_render", None),
            context=context,
        )
        community_handler = CommunityAutomationHandler(
            tasks=self.services.community_tasks, renewal=self.services.session_renewal,
            store=self.services.store, config=self.config, send_notice=self.presentation.send_daily_notice)
        daily_handler = DailyCommandHandler(
            account_reader=self.services.store,
            store=self.services.store,
            runner=self.services.daily_runner,
            client=self.services.client,
            config=self.config,
            format_summary=self.presentation.format_daily_summary,
            send_summary=self.presentation.send_summary,
            send_notice=self.presentation.send_daily_notice,
            extra_automation=community_handler,
        )
        self.runtime = AstrBotRuntimeAdapter(
            coordinator=self.services.runtime_coordinator,
            services=self.services,
            context=context,
            plugin_dir=self.plugin_dir,
            data_dir=self.data_dir,
            config=self.config,
            web_host=self.web_host,
            web_port=self.web_port,
            run_daily=daily_handler.run_all_daily,
            send_summary=daily_handler.send_automatic_summary,
            on_directory_loaded=self._apply_directory,
        )
        def _invalidate_cookie(actor_id: str) -> None:
            self.services.store.mark_cookie_invalid(actor_id)
            self.services.client.invalidate_cache(actor_id)

        self.handlers = PluginCommandHandlers(
            account=AccountCommandHandler(
                application=self.services.account_application,
                public_base_url=self.public_base_url,
                allow_group_bind=bool(self.config.get("allow_group_bind", False)),
                runtime_health=lambda: self.runtime.health_details(
                    len(self._directory)
                ),
                render_manual_summary=daily_handler.render_manual_summary,
                on_unbind=self.services.client.invalidate_cache,
                session_handler=community_handler.handle_renewal,
            ),
            announcement=AnnouncementCommandHandler(
                application=self.services.announcement_application,
                push_enabled=lambda: bool(
                    self.config.get("enable_announcement_push", False)
                ),
            ),
            cdk=CdkCommandHandler(
                account_reader=self.services.store,
                store=self.services.store,
                client=self.services.client,
                service=self.services.cdk_service,
                config=self.config,
            ),
            calendar=CalendarCommandHandler(
                application=self.services.calendar_application,
                payload_builder=self.presentation.calendar_payload_builder,
                render=lambda payload: self.presentation.try_t2i(
                    "calendar_schedule", payload
                ),
                start_background_refresh=self.runtime.request_calendar_refresh,
                start_feedback=self.runtime.start_delayed_feedback,
            ),
            campaign=CampaignCommandHandler(
                application=self.services.campaign_application,
                present=self.presentation.render_campaign_record,
                invalidate_cookie=_invalidate_cookie,
                start_feedback=self.runtime.start_delayed_feedback,
            ),
            character=CharacterCommandHandler(
                application=self.services.character_application,
                directory=lambda: tuple(self._directory),
                render_roster=self.presentation.render_roster,
                render_card=self.presentation.render_character_card,
                invalidate_cookie=_invalidate_cookie,
                start_feedback=self.runtime.start_delayed_feedback,
            ),
            daily=daily_handler,
            guide=GuideCommandHandler(self.services.guide_application),
            profile=ProfileCommandHandler(
                account_reader=self.services.store,
                application=self.services.profile_application,
                present=self.presentation.render_profile,
                invalidate_cookie=_invalidate_cookie,
                start_feedback=self.runtime.start_delayed_feedback,
            ),
            raid=RaidCommandHandler(
                application=self.services.raid_application,
                render_overview=self.presentation.render_raid_overview,
                render_ranking=self.presentation.render_raid_ranking,
                invalidate_cookie=_invalidate_cookie,
                start_feedback=self.runtime.start_delayed_feedback,
            ),
            tarot=TarotCommandHandler(self.services.tarot),
            tower=TowerCommandHandler(self.services.tower_application),
            arena=ArenaCommandHandler(
                self.services.arena_application, enabled=True, web_routes=self.services.arena_web,
                render=self.presentation.try_t2i,
            ) if self.services.arena_application is not None else None,
        )
        self._command_runtime = NikkeCommandRuntime(
            adapters=self.adapters,
            handlers=self.handlers,
            config=self.config,
        )
        self.runtime.start()

    def _apply_directory(self, directory: list[dict[str, Any]]) -> None:
        self._directory = directory
        self.services.campaign_application.update_directory(directory)

    @property
    def command_runtime(self) -> NikkeCommandRuntime:
        """延迟创建轻量路由器，兼容无需完整初始化的测试夹具。"""
        runtime = self.__dict__.get("_command_runtime")
        if runtime is None:
            runtime = NikkeCommandRuntime(
                adapters=self.adapters,
                handlers=self.handlers,
                config=getattr(self, "config", None),
            )
            self.__dict__["_command_runtime"] = runtime
        return runtime

    @filter.command("妮姬", alias={"nikke", "#妮姬", "#nikke"})
    async def nikke(
        self,
        event: AstrMessageEvent,
        command: str = "",
        arg1: str = "",
        arg2: str = "",
        arg3: str = "",
    ):
        """保留历史统一命令注册并薄委托给命令路由器。

        路由器优先从 event.message_str 还原完整尾参；直接位置传参（如单测）时合并 arg3。
        """
        if arg3:
            arg2 = f"{arg2} {arg3}".strip()
        async for result in self.command_runtime.nikke(event, command, arg1, arg2):
            yield result

    @filter.regex(HASH_PREFIX_PATTERN)
    async def nikke_hash_prefix(self, event: AstrMessageEvent):
        """未唤醒消息中的 #妮姬 / #nikke 入口；已唤醒消息交给 nikke 命令处理器，避免重复回复。"""
        if getattr(event, "is_at_or_wake_command", False):
            return
        parsed = parse_nikke_message(str(getattr(event, "message_str", "") or ""))
        if parsed is None:
            return
        async for result in self.command_runtime.nikke(
            event, parsed.command, parsed.arg1, parsed.tail
        ):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_nikke_poke(self, event: AstrMessageEvent):
        """保留全消息事件注册并委托给语音事件适配器。"""
        async for result in self.adapters.voice.on_poke(
            event,
            closing=getattr(getattr(self, "runtime", None), "closing", False),
        ):
            yield result

    async def terminate(self):
        await self.close()

    async def close(self):
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            await runtime.close()
