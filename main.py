# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 综合助手 AstrBot 插件。"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure plugin directory parent is on sys.path so astrbot_plugin_nikke is importable in AstrBot
_pkg_dir = Path(__file__).resolve().parent
_plugins_dir = str(_pkg_dir.parent)
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

from .adapters.astrbot.command_adapter import AstrBotCommandAdapter
from .adapters.astrbot.runtime import AstrBotRuntimeAdapter
from .adapters.astrbot.voice_adapter import AstrBotVoiceAdapter
from .application.commands.account import AccountCommandHandler, RuntimeHealthDetails
from .application.commands.announcement import AnnouncementCommandHandler
from .application.commands.campaign import CampaignCommandHandler
from .application.commands.cdk import CdkCommandHandler
from .application.commands.calendar import CalendarCommandHandler
from .application.commands.daily import DailyCommandHandler
from .application.commands.guide import GuideCommandHandler
from .application.commands.profile import ProfileCommandHandler
from .application.commands.tarot import TarotCommandHandler
from .application.commands.tower import TowerCommandHandler
from ._version import PLUGIN_VERSION
from .core.container import create_container
from .features.daily.runner import DailyRunner
from .features.calendar.application import CalendarApplication
from .ui.renderers import (
    CampaignHistoryRenderer,
    T2IRenderer,
)
from .ui.payloads.calendar import CalendarT2IPayloadBuilder
from .features.character.application import (
    CharacterAmbiguousMatch,
    CharacterNotFound,
    CharacterNotOwned,
)
from .features.cdk.service import CdkService
from .integrations.blablalink.client import BlaBlaError, CookieExpired
from .core.privacy import safe_exception_message
from .features.daily.models import DailyTaskResult
from .core.health import collect_runtime_health, format_runtime_health
from .core.config import normalize_runtime_config


def normalize_nikke_prefix(text: str) -> str:
    """将 #妮姬 / #nikke 统一预处理规范化为 /妮姬 / /nikke。"""
    stripped = text.strip()
    if stripped.startswith("#妮姬"):
        return "/妮姬" + stripped[len("#妮姬"):]
    if stripped.startswith("#nikke"):
        return "/nikke" + stripped[len("#nikke"):]
    return text


class NikkePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.context = context
        if hasattr(self.context, "astrbot_config") and isinstance(self.context.astrbot_config, dict):
            wake_prefixes = self.context.astrbot_config.setdefault("wake_prefix", ["/"])
            if isinstance(wake_prefixes, list) and "#" not in wake_prefixes:
                wake_prefixes.append("#")
        self.config = normalize_runtime_config(config)
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = Path("data") / "nikke"
        self._directory: list[dict] = []
        self.container = create_container(
            self.plugin_dir,
            self.data_dir,
            self.config,
            directory_provider=lambda: self._directory,
        )

        # 映射公开组件到插件门面；Profile 与 Character 用例由应用边界编排。
        self.extension_zip = self.container.extension_zip
        self.store = self.container.store
        self.character_application = self.container.character_application
        self.client = self.container.client
        self.renderer = self.container.renderer
        self.asset_manager = self.container.asset_manager
        self.character_renderer = self.container.character_renderer
        self.campaign_application = self.container.campaign_application
        self.profile_application = self.container.profile_application
        self.profile_renderer = self.container.profile_renderer
        self.raid_builder = self.container.raid_builder
        self.raid_application = self.container.raid_application
        self.raid_renderer = self.container.raid_renderer
        self.campaign_renderer = self.container.campaign_renderer
        self.cdk_service = self.container.cdk_service
        self.feedback_manager = self.container.feedback_manager
        self.voice_application = self.container.voice_application
        self.voice_event_adapter = AstrBotVoiceAdapter(self.voice_application)
        self.announcement_application = self.container.announcement_application
        self.calendar = self.container.calendar
        self.calendar_application = self.container.calendar_application
        self.tarot = self.container.tarot
        self.tower_application = self.container.tower_application
        self.daily_runner = self.container.daily_runner
        self.web = self.container.web
        self.public_base_url = str(
            self.config.get("public_base_url", "https://nikke.irises777.xyz")
        ).rstrip("/")
        self.web_host = str(self.config.get("web_host", "0.0.0.0"))
        self.web_port = int(self.config.get("web_port", 6210))
        self.account_application = self.container.account_application
        self.runtime = AstrBotRuntimeAdapter(
            coordinator=self.container.runtime_coordinator,
            services=self.container,
            context=self.context,
            plugin_dir=self.plugin_dir,
            config=self.config,
            web_host=self.web_host,
            web_port=self.web_port,
            run_daily=self._run_all_daily,
            send_summary=self._send_summary,
            on_directory_loaded=self._apply_directory,
        )
        self.command_adapter = AstrBotCommandAdapter()
        self.tower_command_handler = TowerCommandHandler(self.tower_application)
        self.tarot_command_handler = TarotCommandHandler(
            self.tarot,
            self.plugin_dir,
            self.data_dir,
            on_service_created=lambda service: setattr(self, "tarot", service),
        )
        self.guide_application = self.container.guide_application
        self.guide_command_handler = GuideCommandHandler(self.guide_application)
        self.profile_command_handler = ProfileCommandHandler(
            account_reader=self.store,
            application=self.profile_application,
            present=self._render_profile_dashboard,
        )
        self.daily_command_handler = self._build_daily_command_handler()
        self.cdk_command_handler = self._build_cdk_command_handler()
        self.calendar_command_handler = self._build_calendar_command_handler()
        self.announcement_command_handler = self._build_announcement_command_handler()

        self.account_command_handler = AccountCommandHandler(
            application=self.account_application,
            public_base_url=self.public_base_url,
            allow_group_bind=bool(self.config.get("allow_group_bind", False)),
            runtime_health=self._account_runtime_health_details,
            render_manual_summary=self._render_manual_daily_summary,
        )
        self.runtime.start()

    def _apply_directory(self, directory: list[dict[str, Any]]) -> None:
        """将运行时载入的角色目录交给插件展示状态与战役应用。"""
        self._directory = directory
        self.campaign_application.update_directory(directory)

    def _build_campaign_renderer(self) -> CampaignHistoryRenderer:
        """让所有图片渲染器复用同一个资源缓存与线程池。"""
        return CampaignHistoryRenderer(
            self.data_dir / "cards",
            self.plugin_dir / "fonts",
            self.asset_manager,
        )

    async def _render_campaign_record(self, record):
        """同一 DTO 切换展示路径，渲染失败不重新请求业务接口。"""
        if (getattr(self, "config", None) or {}).get("ui_renderer", "pillow") == "t2i":
            try:
                renderer = getattr(self, "campaign_t2i_renderer", None)
                if renderer is None:
                    renderer = T2IRenderer(html_render=self.html_render, assets=self.asset_manager)
                    self.campaign_t2i_renderer = renderer
                return await renderer.render_campaign_history(record)
            except Exception as exc:
                logger.warning("[NIKKE] Campaign T2I 失败，回退 Pillow: %s", type(exc).__name__)
        return await asyncio.to_thread(self.campaign_renderer.render_campaign_history, record)

    async def _try_t2i(self, page, data, **kwargs):
        """图片展示失败返回空信号，由命令使用已取得的数据安全回退。"""
        config = getattr(self, "config", None) or {}
        if page == "character":
            if config.get("character_card_layout", "replica") == "classic":
                return None
        elif config.get("ui_renderer", "pillow") != "t2i":
            return None
        try:
            renderer = getattr(self, "campaign_t2i_renderer", None)
            if renderer is None:
                renderer = T2IRenderer(html_render=self.html_render, assets=self.asset_manager)
                self.campaign_t2i_renderer = renderer
            return await renderer.render_view(page, data, **kwargs)
        except Exception as exc:
            logger.warning("[NIKKE] %s T2I 失败，使用已有数据回退: %s", page, type(exc).__name__)
            return None

    @property
    def cdk_service(self) -> CdkService:
        if getattr(self, "_cdk_service_inst", None) is None:
            self._cdk_service_inst = CdkService(getattr(self, "client", None))
        return self._cdk_service_inst

    @cdk_service.setter
    def cdk_service(self, value: CdkService) -> None:
        self._cdk_service_inst = value

    @property
    def daily_command_handler(self) -> DailyCommandHandler:
        handler = getattr(self, "_daily_command_handler", None)
        if handler is None:
            handler = self._build_daily_command_handler()
            self._daily_command_handler = handler
        return handler

    @daily_command_handler.setter
    def daily_command_handler(self, handler: DailyCommandHandler) -> None:
        self._daily_command_handler = handler

    def _build_daily_command_handler(self) -> DailyCommandHandler:
        return DailyCommandHandler(
            account_reader=getattr(self, "store", None),
            store=getattr(self, "store", None),
            runner=self.daily_runner,
            client=getattr(self, "client", None),
            config=getattr(self, "config", {}),
            render_summary=lambda rows: self.renderer.render_summary(rows),
            send_summary=self._send_daily_summary_image,
        )

    @property
    def cdk_command_handler(self) -> CdkCommandHandler:
        handler = getattr(self, "_cdk_command_handler", None)
        if handler is None:
            handler = self._build_cdk_command_handler()
            self._cdk_command_handler = handler
        return handler

    @cdk_command_handler.setter
    def cdk_command_handler(self, handler: CdkCommandHandler) -> None:
        self._cdk_command_handler = handler

    def _build_cdk_command_handler(self) -> CdkCommandHandler:
        return CdkCommandHandler(
            account_reader=getattr(self, "store", None),
            store=getattr(self, "store", None),
            client=getattr(self, "client", None),
            service=self.cdk_service,
            config=getattr(self, "config", {}),
        )

    @property
    def calendar_application(self) -> CalendarApplication:
        application = getattr(self, "_calendar_application", None)
        return application or CalendarApplication(getattr(self, "calendar", None))

    @calendar_application.setter
    def calendar_application(self, application: CalendarApplication) -> None:
        self._calendar_application = application

    @property
    def calendar_command_handler(self) -> CalendarCommandHandler | None:
        handler = getattr(self, "_calendar_command_handler", None)
        return handler or self._build_calendar_command_handler()

    @calendar_command_handler.setter
    def calendar_command_handler(self, handler: CalendarCommandHandler) -> None:
        self._calendar_command_handler = handler

    def _build_calendar_command_handler(self) -> CalendarCommandHandler:
        return CalendarCommandHandler(
            application=self.calendar_application,
            payload_builder=CalendarT2IPayloadBuilder(),
            render=lambda payload: self._try_t2i("calendar_schedule", payload),
            start_background_refresh=self._request_calendar_refresh,
        )

    def _build_announcement_command_handler(self) -> AnnouncementCommandHandler:
        return AnnouncementCommandHandler(
            application=self.announcement_application,
            push_enabled=lambda: bool(
                self.config.get("enable_announcement_push", False)
            ),
        )

    def _request_calendar_refresh(self) -> None:
        """将命令触发的刷新委托给运行时，未初始化时安全忽略。"""
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            runtime.request_calendar_refresh()

    async def _send_daily_summary_image(self, target: str, path: str) -> None:
        await self.context.send_message(target, MessageChain([Image.fromFileSystem(path)]))

    @staticmethod
    def _qq_id(event: AstrMessageEvent) -> str:
        return str(event.get_sender_id())

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        return bool(event.is_admin())

    def _account_runtime_health_details(self) -> RuntimeHealthDetails:
        """收集命令展示所需的宿主运行时信息。"""
        return RuntimeHealthDetails(
            plugin_version=PLUGIN_VERSION,
            directory_count=len(self._directory),
            web_host=self.web_host,
            web_port=self.web_port,
            daily_actions_enabled=bool(self.config.get("enable_daily_actions", False)),
            cdk_redemption_enabled=bool(self.config.get("enable_cdk_redemption", False)),
            diagnostics=format_runtime_health(collect_runtime_health(self.data_dir)),
        )

    async def _render_manual_daily_summary(self) -> str:
        """执行一次管理员手动日常汇总并返回展示图片。"""
        return await self.daily_command_handler.render_manual_summary()

    async def _dispatch_account_command(
        self,
        event: AstrMessageEvent,
        *,
        operation: str,
        action: str = "",
        value: str = "",
        state: str = "",
    ):
        """将平台事件转成账号命令上下文并返回已适配结果。"""
        async for result in self.command_adapter.dispatch(
            event,
            self.account_command_handler,
            operation=operation,
            action=action,
            value=value,
            state=state,
            unified_msg_origin=str(getattr(event, "unified_msg_origin", "") or ""),
        ):
            yield result

    def _account_or_error(self, event: AstrMessageEvent) -> dict:
        account = self.store.get_account(self._qq_id(event))
        if not account:
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        return account

    @staticmethod
    def _ambiguous_character_message(error: CharacterAmbiguousMatch) -> str:
        candidates = "\n".join(
            f"{index}. {candidate}"
            for index, candidate in enumerate(error.candidates, 1)
        )
        suffix = "\n候选过多，请继续补全名称。" if error.too_many else ""
        return "找到多个角色，请输入更完整的名称：\n\n" + candidates + suffix

    @staticmethod
    def _help_text(category: str = "", include_admin: bool = False) -> str:
        sections = {
            "账号": (
                "【账号】\n"
                "/妮姬 账号 — 查看绑定状态\n"
                "/妮姬 账号 绑定　(/nikke bind)\n"
                "/妮姬 账号 解绑　(/nikke unbind)\n"
                "/妮姬 账号 汇总 开|关　(/nikke push on|off)"
            ),
            "查询": (
                "【查询】\n"
                "/妮姬 我的　(/nikke me)\n"
                "/妮姬 查询 练度 [角色名]　(/nikke roster、/nikke character)\n"
                "/妮姬 查询 资料 <角色名>　(/nikke info)\n"
                "/妮姬 战役 <关卡>　(/nikke campaign [普通/困难] 46-40)\n"
                "/妮姬 联盟突袭　(/nikke raid)\n"
                "/妮姬 联盟突袭 排名 — 当前响应范围\n"
                "/妮姬 联盟突袭 我的 — 当前账号在本次响应中的记录\n"
                "/妮姬 塔层 <塔名> <层数> — 静态资料\n"
                "/妮姬 日程 [7|14|30]　(/nikke schedule [7|14|30])\n"
                "/妮姬 公告　(/nikke news)\n"
                "/妮姬 攻略 [分类]　(/nikke guide)\n"
                "/妮姬 塔罗 [单抽|三张|今日|状态]　(/nikke tarot)"
            ),
            "日常": (
                "【日常】\n"
                "/妮姬 签到　(/nikke daily、/nikke claim)\n"
                "/妮姬 签到 状态 — 只查询、不提交\n"
                "/妮姬 日常 自动 开|关 — 仅控制自己的定时签到\n"
                "/妮姬 兑换 <CDK>　(/nikke cdk)\n"
                "/妮姬 兑换 批量 <CDK1> <CDK2>...\n"
                "/妮姬 兑换 可用|历史\n"
                "/妮姬 语音 [开|关|语言|角色|服装]　(/nikke voice)\n"
                "注意：群聊发送兑换命令会公开兑换码。"
            ),
            "管理": (
                "【管理员】\n"
                "/妮姬 管理 设群\n"
                "/妮姬 管理 任务时间 HH:MM\n"
                "/妮姬 管理 汇总时间 HH:MM\n"
                "/妮姬 管理 执行\n"
                "/妮姬 管理 健康"
            ),
        }
        aliases = {
            "account": "账号", "bind": "账号",
            "query": "查询", "roster": "查询", "info": "查询", "data": "查询",
            "raid": "查询", "突袭": "查询", "campaign": "查询", "stage": "查询", "战役": "查询",
            "schedule": "查询", "日程": "查询", "news": "查询", "公告": "查询",
            "guide": "查询", "攻略": "查询",
            "tarot": "查询", "塔罗": "查询",
            "daily": "日常", "routine": "日常", "日常": "日常", "push": "日常",
            "admin": "管理",
        }
        selected = aliases.get(category.strip().lower(), category.strip())
        if selected in sections:
            if selected == "管理" and not include_admin:
                return "管理指令仅对管理员显示。"
            return sections[selected] + "\n\n发送 /妮姬 帮助 查看主菜单。"
        visible = [sections["账号"], sections["查询"], sections["日常"]]
        if include_admin:
            visible.append(sections["管理"])
        return (
            f"NIKKE 综合助手 {PLUGIN_VERSION}\n\n"
            "六个入口：帮助｜账号｜我的｜查询｜签到｜兑换\n\n"
            + "\n\n".join(visible)
            + "\n\n分类帮助：/妮姬 帮助 账号|查询|日常"
            + ("|管理" if include_admin else "")
            + "\n安全提示：不要发送Cookie、密码或转发绑定链接。"
            + "\n所有 /妮姬 命令均支持使用 #妮姬 触发。"
        )

    @filter.command("妮姬", alias={"nikke", "#妮姬", "#nikke"})
    async def nikke(
        self,
        event: AstrMessageEvent,
        command: str = "",
        arg1: str = "",
        arg2: str = "",
    ):
        """NIKKE 中文精简指令入口。"""
        if command.startswith("#"):
            norm = normalize_nikke_prefix(f"{command} {arg1} {arg2}".strip())
            parts = norm.lstrip("/").split(maxsplit=3)
            command = parts[1] if len(parts) > 1 else ""
            arg1 = parts[2] if len(parts) > 2 else ""
            arg2 = parts[3] if len(parts) > 3 else ""
        command_key = command.strip().casefold()
        if command_key in {"塔层", "tower"}:
            async for result in self.command_adapter.dispatch(
                event,
                self.tower_command_handler,
                tower=arg1,
                floor=arg2,
            ):
                yield result
            return
        if command_key in {"语音", "voice"}:
            async for result in self.voice_settings(event, arg1, arg2):
                yield result
            return
        if command_key in {"塔罗", "tarot"}:
            async for result in self.tarot_command(event, arg1, arg2):
                yield result
            return
        if command_key in {"", "帮助", "help"}:
            async for result in self.nikke_help(event, arg1):
                yield result
            return
        if command_key in {"账号", "account"}:
            async for result in self.account(event, arg1, arg2):
                yield result
            return
        if command_key in {"我的", "me", "progress"}:
            async for result in self.me(event):
                yield result
            return
        if command_key in {"查询", "query"}:
            async for result in self.query(event, arg1, arg2):
                yield result
            return
        if command_key in {"签到", "daily", "claim", "日常", "routine"}:
            async for result in self.daily(event, arg1, arg2):
                yield result
            return
        if command_key in {"兑换", "cdk"}:
            sub = arg1.strip().casefold()
            if sub in {"批量", "batch"}:
                if not arg2:
                    yield event.plain_result("用法：/妮姬 兑换 批量 <CDK1> <CDK2> ...")
                    return
                async for result in self.cdk_batch(event, arg2):
                    yield result
                return
            if sub in {"可用", "available"}:
                async for result in self.cdk_available(event):
                    yield result
                return
            if sub in {"历史", "history"}:
                async for result in self.cdk_history(event):
                    yield result
                return
            if not arg1:
                yield event.plain_result("用法：/妮姬 兑换 <CDK> 或 /妮姬 兑换 批量 <CDK...> 或 /妮姬 兑换 可用|历史")
                return
            async for result in self.cdk(event, arg1):
                yield result
            return
        if command_key in {"战役", "campaign", "关卡", "stage"}:
            async for result in self.campaign(event, arg1, arg2):
                yield result
            return
        if command_key in {"日程"}:
            try:
                stream = self.event_schedule(event, arg1)
            except TypeError:
                stream = self.event_schedule(event)
            async for result in stream:
                yield result
            return
        if command_key in {"schedule"}:
            if ":" in arg1 and self._is_admin(event):
                async for result in self.schedule(event, arg1):
                    yield result
                return
            try:
                stream = self.event_schedule(event, arg1)
            except TypeError:
                stream = self.event_schedule(event)
            async for result in stream:
                yield result
            return
        if command_key in {"公告", "news", "announcement"}:
            if arg1 in {"订阅", "取消订阅"}:
                async for result in self.announcement_subscription(event, arg1):
                    yield result
                return
            if arg1:
                adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
                async for result in adapter.dispatch(
                    event,
                    self.announcement_command_handler,
                    operation="unsupported",
                ):
                    yield result
                return
            async for result in self.announcements_view(event):
                yield result
            return
        if command_key in {"攻略", "guide", "guides"}:
            async for result in self.guide(event, arg1, arg2 or "1"):
                yield result
            return
        if command_key in {"突袭", "联盟突袭", "raid", "union_raid"}:
            if arg1 in {"排名", "ranking"}:
                async for result in self.union_raid_ranking(event):
                    yield result
                return
            if arg1 in {"我的", "my"}:
                async for result in self.union_raid_my(event):
                    yield result
                return
            async for result in self.union_raid(event):
                yield result
            return
        if command_key in {"管理", "admin"}:
            async for result in self.admin(event, arg1, arg2):
                yield result
            return

        # 兼容0.1.2及更早版本的英文平铺指令。
        legacy = {
            "bind": (self.bind, (event,)),
            "unbind": (self.unbind, (event,)),
            "status": (self.status, (event,)),
            "roster": (self.roster, (event,)),
            "character": (self.character, (event, arg1)),
            "info": (self.info, (event, arg1)),
            "campaign": (self.campaign, (event, arg1, arg2)),
            "raid": (self.union_raid, (event,)),
            "union_raid": (self.union_raid, (event,)),
            "news": (self.announcements_view, (event,)),
            "guide": (self.guide, (event, arg1)),
            "push": (self.push, (event, arg1)),
            "group": (self.group_set, (event, arg1)),
            "schedule": (self.schedule, (event, arg1)),
            "summary": (self.summary, (event, arg1)),
            "run": (self.run, (event,)),
            "health": (self.health, (event,)),
            "tarot": (self.tarot_command, (event, arg1, arg2)),
        }
        target = legacy.get(command_key)
        if target:
            handler, args = target
            async for result in handler(*args):
                yield result
            return
        yield event.plain_result("未知指令。发送 /妮姬 帮助 查看可用功能。")

    async def tarot_command(
        self,
        event: AstrMessageEvent,
        action: str = "",
        value: str = "",
    ):
        """NIKKE 塔罗：单抽、三张牌阵与每日固定抽牌。"""
        handler = getattr(self, "tarot_command_handler", None)
        if handler is None:
            handler = TarotCommandHandler(
                getattr(self, "tarot", None),
                self.plugin_dir,
                self.data_dir,
                on_service_created=lambda service: setattr(self, "tarot", service),
            )
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, handler, action=action, value=value
        ):
            yield result

    async def nikke_help(self, event: AstrMessageEvent, category: str = ""):
        """查看精简后的中文指令。"""
        yield event.plain_result(self._help_text(category, self._is_admin(event)))

    async def account(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """管理账号绑定、状态和每日汇总。"""
        async for result in self._dispatch_account_command(
            event, operation="account", action=action, value=value
        ):
            yield result

    async def bind(self, event: AstrMessageEvent):
        """生成一次性安全绑定链接及向导。"""
        async for result in self._dispatch_account_command(event, operation="bind"):
            yield result

    async def unbind(self, event: AstrMessageEvent):
        """解除自己的BlaBlaLink账号。"""
        async for result in self._dispatch_account_command(event, operation="unbind"):
            yield result

    async def status(self, event: AstrMessageEvent):
        """检查绑定和Cookie状态。"""
        async for result in self._dispatch_account_command(event, operation="status"):
            yield result

    async def _render_profile_dashboard(self, dashboard):
        """优先使用 T2I，失败时以同一 DTO 回退 Pillow。"""
        path = await self._try_t2i("profile", dashboard)
        if not path:
            path = await asyncio.to_thread(self.profile_renderer.render_profile, dashboard)
        return path

    async def me(self, event: AstrMessageEvent):
        """生成个人账号概览卡。"""
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self.runtime.send_delayed_notice(event, "正在生成个人账号概览...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            async for result in self.command_adapter.dispatch(
                event, self.profile_command_handler
            ):
                yield result
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            yield event.plain_result(f"查询失败：{exc}")
        finally:
            if handle:
                await handle.cancel()

    async def query(self, event: AstrMessageEvent, kind: str = "", name: str = ""):
        """查询个人练度或公开角色资料。"""
        kind_key = kind.strip().casefold()
        if kind_key in {"练度", "roster", "character"}:
            if name:
                async for result in self.character(event, name):
                    yield result
            else:
                async for result in self.roster(event):
                    yield result
            return
        if kind_key in {"资料", "info"}:
            if not name:
                yield event.plain_result("用法：/妮姬 查询 资料 <角色名>")
                return
            async for result in self.info(event, name):
                yield result
            return
        if kind_key in {"战役", "关卡", "campaign", "stage"}:
            async for result in self.campaign(event, name, ""):
                yield result
            return
        if kind_key in {"攻略", "guide"}:
            async for result in self.guide(event, name):
                yield result
            return
        if kind_key in {"突袭", "联盟突袭", "raid", "union_raid"}:
            async for result in self.union_raid(event):
                yield result
            return
        yield event.plain_result("用法：/妮姬 查询 练度 [角色名]、/妮姬 查询 资料 <角色名>、/妮姬 查询 战役 <关卡> 或 /妮姬 攻略")

    async def voice_settings(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """通过语音适配器处理偏好设置命令。"""
        async for result in self.voice_event_adapter.voice_settings(event, action, value):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_nikke_poke(self, event: AstrMessageEvent):
        """将框架戳一戳事件委托给语音事件适配器。"""
        async for result in self.voice_event_adapter.on_poke(
            event,
            closing=getattr(getattr(self, "runtime", None), "closing", False),
        ):
            yield result

    async def union_raid_ranking(self, event: AstrMessageEvent):
        """展示当前响应范围的伤害排名，不声称覆盖完整赛季。"""
        from .features.raid.participants import format_ranking
        try:
            data = await self.raid_application.ranking(self._qq_id(event))
            path = await self._try_t2i("union_records", data)
            yield event.image_result(path) if path else event.plain_result(format_ranking(data))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新绑定。")
        except (BlaBlaError, ValueError):
            yield event.plain_result("突袭排名暂不可用：数据不完整或请求失败，请稍后重试。")

    async def union_raid_my(self, event: AstrMessageEvent):
        """展示当前响应中与当前账号稳定 openid 精确匹配的突袭记录。"""
        from .features.raid.application import RaidMemberIdentityUnavailable
        from .features.raid.participants import format_ranking
        try:
            data = await self.raid_application.member(self._qq_id(event))
            path = await self._try_t2i("union_member", data)
            yield event.image_result(path) if path else event.plain_result(format_ranking(data))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新绑定。")
        except RaidMemberIdentityUnavailable as exc:
            yield event.plain_result(str(exc))
        except (BlaBlaError, ValueError):
            yield event.plain_result("我的突袭记录暂不可用：数据不完整或请求失败，请稍后重试。")

    async def union_raid(self, event: AstrMessageEvent):
        """查询当前账号所属联盟的联盟突袭战况。"""
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self.runtime.send_delayed_notice(event, "正在查询联盟突袭战况...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            data = await self.raid_application.overview(self._qq_id(event))
            path = await self._try_t2i("union_overview", data)
            if not path:
                path = await asyncio.to_thread(self.raid_renderer.render_raid_overview, data)
            yield event.image_result(path)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            yield event.plain_result(f"突袭查询失败：{safe_exception_message(exc)}")
        except Exception as exc:
            logger.error("[NIKKE] 联盟突袭查询异常: %s", safe_exception_message(exc))
            yield event.plain_result(f"突袭查询异常：{safe_exception_message(exc)}")
        finally:
            if handle:
                await handle.cancel()

    async def roster(self, event: AstrMessageEvent):
        """生成自己的妮姬练度表。"""
        try:
            data = await self.character_application.roster(
                self._qq_id(event), self._directory
            )
            path = self.renderer.render_roster(
                data.commander_name,
                data.characters,
                data.name_map,
            )
            yield event.image_result(path)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新绑定。")
        except Exception as exc:
            logger.warning("[NIKKE] roster 查询失败: %s", safe_exception_message(exc))
            yield event.plain_result(f"练度查询失败：{safe_exception_message(exc)}")

    async def progress(self, event: AstrMessageEvent):
        """查看同步器、前哨和主线进度。"""
        async for result in self.me(event):
            yield result

    async def character(self, event: AstrMessageEvent, name: str):
        """查询自己指定妮姬的练度。"""
        if not name.strip():
            yield event.plain_result("用法：/妮姬 查询 练度 <角色名>")
            return
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self.runtime.send_delayed_notice(event, "正在查询与渲染角色卡片...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            card = await self.character_application.character_card(
                self._qq_id(event), name, self._directory
            )
            path = await self._try_t2i("character", card)
            if not path:
                path = await asyncio.to_thread(self.character_renderer.render_character, card)
            yield event.image_result(path)
        except CharacterAmbiguousMatch as exc:
            yield event.plain_result(self._ambiguous_character_message(exc))
        except CharacterNotFound:
            yield event.plain_result("查询失败：没有找到该妮姬")
        except CharacterNotOwned as exc:
            yield event.plain_result(str(exc))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            yield event.plain_result(f"查询失败：{exc}")
        except Exception as exc:
            logger.error("[NIKKE] 角色查询异常: %s", safe_exception_message(exc))
            yield event.plain_result(f"查询失败：{safe_exception_message(exc)}")
        finally:
            if handle:
                await handle.cancel()

    async def info(self, event: AstrMessageEvent, name: str):
        """查询妮姬基础资料。"""
        if not name.strip():
            yield event.plain_result("用法：/妮姬 查询 资料 <角色名>")
            return
        try:
            data = self.character_application.info(name, self._directory)
        except CharacterNotFound:
            yield event.plain_result("没有找到该妮姬。")
            return
        except CharacterAmbiguousMatch as exc:
            yield event.plain_result(self._ambiguous_character_message(exc))
            return
        path = self.renderer.render(data.name, data.title, data.rows)
        yield event.image_result(path)

    @property
    def daily_runner(self) -> DailyRunner:
        runner = getattr(self, "_daily_runner", None)
        if runner is None:
            runner = DailyRunner(
                client=getattr(self, "client", None),
                store=getattr(self, "store", None),
                config=getattr(self, "config", {}),
            )
            self._daily_runner = runner
        else:
            if hasattr(self, "client"):
                runner.client = self.client
            if hasattr(self, "store"):
                runner.store = self.store
            if hasattr(self, "config"):
                runner.config = self.config
        return runner

    @daily_runner.setter
    def daily_runner(self, runner: DailyRunner) -> None:
        self._daily_runner = runner

    async def _run_all_daily(
        self,
        day: str,
        stagger: bool = False,
        automatic: bool = False,
    ) -> list[DailyTaskResult]:
        return await self.daily_command_handler.run_all_daily(
            day, stagger=stagger, automatic=automatic
        )

    async def _send_summary(self, day: str) -> None:
        await self.daily_command_handler.send_automatic_summary(day)

    async def daily(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """将 AstrBot 事件转成 Daily 命令上下文。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, self.daily_command_handler, action=action, value=value
        ):
            yield result

    async def claim(self, event: AstrMessageEvent):
        """兼容旧版英文签到指令。"""
        async for result in self.daily(event):
            yield result

    async def cdk(self, event: AstrMessageEvent, code: str):
        """将单码兑换请求委托给 CDK 命令用例。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, self.cdk_command_handler, operation="single", code=code
        ):
            yield result

    async def cdk_batch(self, event: AstrMessageEvent, raw_codes: str):
        """将批量兑换请求委托给 CDK 命令用例。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, self.cdk_command_handler, operation="batch", codes=raw_codes
        ):
            yield result

    async def cdk_available(self, event: AstrMessageEvent):
        """委托只读可用码查询用例。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, self.cdk_command_handler, operation="available"
        ):
            yield result

    async def cdk_history(self, event: AstrMessageEvent):
        """委托只读兑换历史查询用例。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, self.cdk_command_handler, operation="history"
        ):
            yield result

    async def campaign(self, event: AstrMessageEvent, stage_str: str = "", mode_str: str = ""):
        """查询主线战役关卡的历史通关阵容。"""
        feedback_manager = getattr(self, "feedback_manager", None)
        start_feedback = None
        if feedback_manager is not None:
            start_feedback = lambda: feedback_manager.start_delayed_feedback(
                lambda: self.runtime.send_delayed_notice(
                    event, "正在查询战役通关阵容..."
                )
            )
        handler = CampaignCommandHandler(
            application=self.campaign_application,
            present=self._render_campaign_record,
            invalidate_cookie=lambda qq_id: self.store.mark_cookie_invalid(qq_id),
            start_feedback=start_feedback,
        )
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, handler, stage=stage_str, mode=mode_str
        ):
            yield result

    async def event_schedule(self, event: AstrMessageEvent, horizon: str = ""):
        """将日程查询转为框架命令，并由 Calendar application 处理快照。"""
        handler = self.calendar_command_handler
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event, handler, horizon=horizon
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
        """把公告查询参数委托给 framework-free handler。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event,
            self.announcement_command_handler,
            operation="view",
            locale=locale or "",
            category=category or "",
            query=query or "",
        ):
            yield result

    async def announcement_deep_rescan(self, event: AstrMessageEvent, locale: str = "en"):
        """把管理员深度重扫委托给 framework-free handler。"""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event,
            self.announcement_command_handler,
            operation="deep_rescan",
            locale=locale,
        ):
            yield result

    async def announcement_subscription(self, event: AstrMessageEvent, action: str):
        """由适配器传入当前会话目标，权限与订阅写入归 handler/application。"""
        operation = "unsubscribe" if action == "取消订阅" else "subscribe"
        target = getattr(event, "unified_msg_origin", "") or ""
        adapter = getattr(self, "command_adapter", None) or AstrBotCommandAdapter()
        async for result in adapter.dispatch(
            event,
            self.announcement_command_handler,
            operation=operation,
            target=target,
        ):
            yield result

    async def guide(self, event: AstrMessageEvent, category: str = "", page: str = "1"):
        """查看或发送常用攻略图。"""
        async for result in self.command_adapter.dispatch(
            event,
            self.guide_command_handler,
            category=category,
            page=page,
        ):
            yield result

    async def push(self, event: AstrMessageEvent, state: str):
        """开启或关闭每日群汇总。"""
        async for result in self._dispatch_account_command(
            event, operation="push", state=state
        ):
            yield result

    async def admin(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """管理员配置与运行入口。"""
        async for result in self._dispatch_account_command(
            event, operation="admin", action=action, value=value
        ):
            yield result

    async def group_set(self, event: AstrMessageEvent, action: str = "set"):
        """管理员将当前会话设为每日汇总目标。"""
        async for result in self._dispatch_account_command(
            event, operation="group_set", action=action
        ):
            yield result

    async def schedule(self, event: AstrMessageEvent, clock: str):
        """管理员设置每日任务开始时间。"""
        async for result in self._dispatch_account_command(
            event, operation="schedule", value=clock
        ):
            yield result

    async def summary(self, event: AstrMessageEvent, clock: str):
        """管理员设置每日汇总时间。"""
        async for result in self._dispatch_account_command(
            event, operation="summary", value=clock
        ):
            yield result

    async def run(self, event: AstrMessageEvent):
        """管理员立即执行并发送汇总。"""
        async for result in self._dispatch_account_command(event, operation="run"):
            yield result

    async def health(self, event: AstrMessageEvent):
        """管理员查看插件健康状态；诊断只读，不执行缓存清理。"""
        async for result in self._dispatch_account_command(event, operation="health"):
            yield result

    async def terminate(self):
        await self.close()

    async def close(self):
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            await runtime.close()
