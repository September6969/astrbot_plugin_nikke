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
import json
import os
import random
import re
import shutil
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star

from .adapters.astrbot.command_adapter import AstrBotCommandAdapter
from .application.commands.account import AccountCommandHandler, RuntimeHealthDetails
from .application.commands.campaign import CampaignCommandHandler
from .application.commands.cdk import CdkCommandHandler
from .application.commands.daily import DailyCommandHandler
from .application.commands.guide import GuideCommandHandler
from .application.commands.profile import ProfileCommandHandler
from .application.commands.tarot import TarotCommandHandler
from .application.commands.tower import TowerCommandHandler
from ._version import PLUGIN_VERSION
from .core.container import create_container
from .features.daily.runner import DailyRunner
from .features.announcement.service import AnnouncementService
from .features.announcement.delivery import AnnouncementDelivery
from .features.calendar.service import CalendarService
from .core.asset_manager import AssetManager
from .ui.renderers import (
    CampaignHistoryRenderer,
    CharacterCardRenderer,
    T2IRenderer,
    UnionRaidRenderer,
)
from .ui.primitives import CardRenderer
from .ui.t2i_payloads import CalendarT2IPayloadBuilder
from .features.character.application import (
    CharacterAmbiguousMatch,
    CharacterNotFound,
    CharacterNotOwned,
)
from .features.cdk.service import CdkService
from .integrations.blablalink.client import BlaBlaClient, BlaBlaError, CookieExpired
from .core.privacy import safe_exception_message
from .features.daily.models import DailyTaskResult
from .core.feedback import DelayedFeedbackManager
from .core.health import collect_runtime_health, format_runtime_health
from .core.config import normalize_runtime_config, read_schedule_clock
from .integrations.spine.config import build_spine_renderer
from .core.storage import NikkeStore
from .features.character.registries.costume import CostumeRegistry
from .features.voice.character_resolver import VoiceCharacterResolver
from .features.voice.audio import VoiceAudioCache, VoicePreference, is_self_poke
from .features.voice.encoder import VoiceEncoder
from .features.voice.mapping import VoiceMapRegistry
from .features.voice.pipeline import VoicePipeline
from .features.voice.provider import VoiceResourceProvider
from .integrations.web.service import BindingWebService


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
        self.container = create_container(self.plugin_dir, self.data_dir, self.config)

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
        self.voice_mapping = self.container.voice_mapping
        self.voice_character_resolver = self.container.voice_character_resolver
        self.costume_registry = self.container.costume_registry
        self._voice_audio = self.container.voice_audio
        self.voice_provider = self.container.voice_provider
        self.voice_encoder = self.container.voice_encoder
        self.voice_pipeline = self.container.voice_pipeline
        self.announcements = self.container.announcements
        self.announcement_delivery = self.container.announcement_delivery
        self.calendar = self.container.calendar
        self.tarot = self.container.tarot
        self.tower_application = self.container.tower_application
        self.daily_runner = self.container.daily_runner
        self.web = self.container.web
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

        self.public_base_url = str(
            self.config.get("public_base_url", "https://nikke.irises777.xyz")
        ).rstrip("/")
        self.web_host = str(self.config.get("web_host", "0.0.0.0"))
        self.web_port = int(self.config.get("web_port", 6210))
        self._directory: list[dict] = []
        self.account_application = self.container.account_application
        self.account_command_handler = AccountCommandHandler(
            application=self.account_application,
            public_base_url=self.public_base_url,
            allow_group_bind=bool(self.config.get("allow_group_bind", False)),
            runtime_health=self._account_runtime_health_details,
            render_manual_summary=self._render_manual_daily_summary,
        )
        self._voice_poke_cooldowns: dict[tuple, float] = {}
        self._termination_lock = asyncio.Lock()
        self._background_tasks: list[asyncio.Task] = []
        self._closing = False
        self._spawn_background_task(self._start_services())

    def _build_campaign_renderer(self) -> CampaignHistoryRenderer:
        """让所有图片渲染器复用同一个资源缓存与线程池。"""
        return CampaignHistoryRenderer(
            self.data_dir / "cards",
            self.plugin_dir / "fonts",
            self.asset_manager,
        )

    def _spawn_background_task(self, coro):
        """统一登记任务，关闭期间拒绝新任务并释放尚未启动的协程。"""
        if getattr(self, "_closing", False):
            coro.close()
            return None
        if not hasattr(self, "_background_tasks"):
            self._background_tasks = []
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        def done(completed):
            if completed in self._background_tasks:
                self._background_tasks.remove(completed)
            if not completed.cancelled() and completed.exception() is not None:
                logger.warning("[NIKKE] 后台任务失败: %s", type(completed.exception()).__name__)
        task.add_done_callback(done)
        return task

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

    async def _send_daily_summary_image(self, target: str, path: str) -> None:
        await self.context.send_message(target, MessageChain([Image.fromFileSystem(path)]))

    def _pack_extension(self) -> None:
        extension_dir = self.plugin_dir / "extension"
        with zipfile.ZipFile(self.extension_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in extension_dir.rglob("*"):
                if path.is_file():
                    if path.name == "manifest.json":
                        manifest = json.loads(path.read_text(encoding="utf-8"))
                        manifest["host_permissions"] = [
                            "https://*.blablalink.com/*", self.web.site_origin + "/*"
                        ]
                        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                    else:
                        archive.write(path, path.relative_to(extension_dir))

    async def _start_services(self) -> None:
        try:
            await asyncio.to_thread(self._pack_extension)
        except Exception as exc:
            logger.warning("[NIKKE] 浏览器扩展打包跳过: %s", safe_exception_message(exc))
        try:
            await self.tower_application.preload()
        except Exception as exc:
            logger.warning("[NIKKE] 塔层静态资料预热失败: %s", safe_exception_message(exc))
        try:
            await self.web.start(self.web_host, self.web_port)
            logger.info(f"[NIKKE] 绑定服务已监听 {self.web_host}:{self.web_port}")
        except Exception as exc:
            logger.error("[NIKKE] 绑定服务启动失败: %s", safe_exception_message(exc))
        try:
            self._directory = await self.client.get_directory()
            self.campaign_application.update_directory(self._directory)
            logger.info(f"[NIKKE] 已载入 {len(self._directory)} 条妮姬目录")
        except Exception as exc:
            logger.warning("[NIKKE] 妮姬目录载入失败: %s", safe_exception_message(exc))
        try:
            # L2D 索引只在服务启动时单次预热；角色卡热路径只读本地索引，避免 N+1。
            await asyncio.to_thread(self.asset_manager.nikke_db.get_l2d_index, allow_remote=True)
        except Exception as exc:
            logger.debug("[NIKKE] L2D 索引预热跳过: %s", safe_exception_message(exc))
        try:
            # Exia 静态表只在服务启动时统一预热；角色卡只读取缓存，不逐字段请求网络。
            await self.character_application.preload_stat_resources()
            logger.info("[NIKKE] Exia/NIKKE 静态属性表已载入并缓存")
        except Exception as exc:
            logger.warning("[NIKKE] 静态属性表预热失败，角色卡将保留 —：%s", safe_exception_message(exc))
        self._spawn_background_task(self._sync_announcements_background())
        self._spawn_background_task(self._sync_calendar_background())
        await self._scheduler_loop()

    async def _sync_announcements_background(self) -> None:
        try:
            await self.announcements.sync_from_source()
        except Exception as exc:
            logger.debug("[NIKKE] 后台公告同步跳过: %s", safe_exception_message(exc))

    async def _sync_calendar_background(self) -> None:
        try:
            await self.calendar.sync_from_source()
        except Exception as exc:
            logger.debug("[NIKKE] 后台日程同步跳过: %s", safe_exception_message(exc))

    async def _send_delayed_notice(self, event: AstrMessageEvent, text: str) -> None:
        try:
            if hasattr(self, "context") and hasattr(self.context, "send_message") and hasattr(event, "unified_msg_origin"):
                await self.context.send_message(event.unified_msg_origin, MessageChain([Plain(text)]))
        except Exception as exc:
            logger.debug("[NIKKE] 延迟提示发送跳过: %s", safe_exception_message(exc))

    async def _scheduler_loop(self) -> None:
        last_daily = ""
        last_summary = ""
        last_announcement_sync = 0.0
        last_calendar_sync = 0.0
        while not self._closing:
            now = datetime.now(timezone(timedelta(hours=8)))
            today = now.strftime("%Y-%m-%d")
            daily_h, daily_m = read_schedule_clock(
                self.store.get_setting,
                "daily",
                default_hour=self.config["daily_hour"],
                default_minute=self.config["daily_minute"],
            )
            summary_h, summary_m = read_schedule_clock(
                self.store.get_setting,
                "summary",
                default_hour=self.config["summary_hour"],
                default_minute=self.config["summary_minute"],
            )
            if (now.hour, now.minute) == (daily_h, daily_m) and last_daily != today:
                last_daily = today
                self._spawn_background_task(self._run_all_daily(today, stagger=True, automatic=True))
            if (now.hour, now.minute) == (summary_h, summary_m) and last_summary != today:
                last_summary = today
                self._spawn_background_task(self._send_summary(today))
            if time.time() - last_announcement_sync > 3600:
                last_announcement_sync = time.time()
                self._spawn_background_task(self._sync_announcements_background())
            if time.time() - last_calendar_sync > 300:
                last_calendar_sync = time.time()
                self._spawn_background_task(self._sync_calendar_background())
            if self.config.get("enable_announcement_push", False):
                task = getattr(self, "_announcement_push_task", None)
                if task is None or task.done():
                    self._announcement_push_task = self._spawn_background_task(self._dispatch_announcements())
            await asyncio.sleep(20)

    def _deadline_reminders_for_delivery(self):
        calendar = getattr(self, "calendar", None)
        if calendar is not None and calendar.has_snapshot() and calendar.activity_count() > 0:
            return calendar.list_reminder_deadlines()
        return self.announcements.list_active_deadlines()

    async def _dispatch_announcements(self):
        """默认关闭，只有管理员启用且目标显式订阅后才由调度调用。"""
        if not self.config.get("enable_announcement_push", False):
            return
        async def sender(target, text):
            await asyncio.wait_for(self.context.send_message(target, MessageChain([Plain(text)])), timeout=10)
            return True
        await self.announcement_delivery.dispatch(
            self.announcements.list_announcements(limit=10000),
            self._deadline_reminders_for_delivery(),
            sender,
        )

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

    def resolve_voice_character(self, query: str) -> str | None:
        resolver = getattr(self, "voice_character_resolver", None)
        if resolver is None:
            user_aliases = (self.config or {}).get("custom_character_aliases")
            try:
                resolver = VoiceCharacterResolver(self.plugin_dir / "assets", user_aliases=user_aliases)
            except ValueError as err:
                logger.error("[NIKKE] 语音用户自定义别名配置错误，已忽略自定义别名：%s", err)
                resolver = VoiceCharacterResolver(self.plugin_dir / "assets")
            self.voice_character_resolver = resolver
        return resolver.resolve(query, getattr(self, "_directory", None))

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
                yield event.plain_result("公告命令已简化，请使用：\n\n/妮姬 公告")
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
            lambda: self._send_delayed_notice(event, "正在生成个人账号概览...")
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
        """保存明确的语音偏好，音频需管理员在本地登记授权来源。"""
        from .features.voice.audio import VoicePreference
        key = f"{event.get_platform_name()}:{self._qq_id(event)}"
        preference = VoicePreference.load(self.store, key)
        action_clean = str(action or "").strip()
        value_clean = str(value or "").strip()

        if action_clean in {"开", "关"}:
            preference.enabled = action_clean == "开"
        elif action_clean == "语言" and value_clean.lower() in {"ja", "en", "ko"}:
            preference.locale = value_clean.lower()
            preference.explicit_locale = True
        elif action_clean == "角色":
            if not value_clean:
                yield event.plain_result("用法：/妮姬 语音 角色 <角色名|英文名|代码>")
                return
            resolved_char = self.resolve_voice_character(value_clean)
            if not resolved_char:
                yield event.plain_result(f"未找到妮姬：{value_clean}")
                return
            preference.character = resolved_char
            preference.skin = "default"
            preference.spine_asset_id = ""
        elif action_clean in {"服装", "皮肤", "skin", "costume"}:
            char_res = getattr(self, "voice_character_resolver", None)
            current_rid = char_res.get_resource_id(preference.character) if char_res else None
            costume_reg = getattr(self, "costume_registry", None)
            if costume_reg is None:
                costume_reg = CostumeRegistry(self.plugin_dir / "assets")
                self.costume_registry = costume_reg

            if not value_clean:
                available = costume_reg.get_costumes_for_resource(current_rid)
                if available:
                    lines = [f"当前角色 {preference.character} 可用已核验服装："]
                    for c in available:
                        lines.append(f"- {c.costume_id}：{c.costume_name} ({c.spine_asset_id})")
                    lines.append("用法：/妮姬 语音 服装 <默认|服装ID|服装名>")
                    yield event.plain_result("\n".join(lines))
                else:
                    yield event.plain_result(f"当前角色 {preference.character} 暂无可切换的已核验服装。\n用法：/妮姬 语音 服装 默认")
                return

            result = costume_reg.resolve(value_clean, expected_resource_id=current_rid)
            if not result.ok:
                yield event.plain_result(result.message)
                return
            if result.status == "RESET_DEFAULT":
                preference.skin = "default"
                preference.spine_asset_id = ""
            else:
                preference.skin = result.costume.costume_id
                preference.spine_asset_id = result.costume.spine_asset_id
        elif action_clean:
            yield event.plain_result("用法：/妮姬 语音 开|关，语音 语言 ja|en|ko，语音 角色 <角色名>，语音 服装 <默认|服装ID|服装名>")
            return

        preference.save(self.store, key)
        skin_str = f" · {preference.skin}" if preference.skin != "default" else ""
        yield event.plain_result(f"互动语音：{'开启' if preference.enabled else '关闭'} · {preference.character}{skin_str} · {preference.locale}。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_nikke_poke(self, event: AstrMessageEvent):
        """仅对戳向本 Bot 的通知响应；默认关闭，不发送未经登记的音频，纯语音无文本兜底。"""
        raw = getattr(event.message_obj, "raw_message", None)
        if event.get_platform_name() != "aiocqhttp" or not is_self_poke(raw):
            return
        preference = VoicePreference.load(self.store, f"{event.get_platform_name()}:{self._qq_id(event)}")
        if not preference.enabled or getattr(self, "_closing", False):
            return
        now = time.monotonic()
        cooldowns = getattr(self, "_voice_poke_cooldowns", {})
        cooldown_key = (event.get_platform_name(), event.get_sender_id(), getattr(event, "unified_msg_origin", ""))
        if now - cooldowns.get(cooldown_key, float("-inf")) < 10:
            return
        self._voice_poke_cooldowns = {key: stamp for key, stamp in cooldowns.items() if now - stamp < 10}
        self._voice_poke_cooldowns[cooldown_key] = now
        try:
            audio = await self._voice_audio.resolve(preference)
        except (OSError, ValueError, asyncio.TimeoutError):
            audio = None
        if audio is None:
            mapping_registry = getattr(self, "voice_mapping", None)
            pipeline = getattr(self, "voice_pipeline", None)
            canonical_spine = getattr(preference, "spine_asset_id", "") or None
            if mapping_registry:
                if hasattr(mapping_registry, "resolve_poke"):
                    mapping = mapping_registry.resolve_poke(
                        preference.character,
                        preference.skin,
                        preference.locale,
                        spine_asset_id=canonical_spine,
                    )
                else:
                    mapping = mapping_registry.resolve(
                        preference.character,
                        preference.skin,
                        preference.locale,
                        spine_asset_id=canonical_spine,
                    )
                    if mapping is None and canonical_spine:
                        mapping = mapping_registry.resolve_by_spine_asset(canonical_spine, preference.locale)
            if (
                mapping is not None
                and pipeline is not None
                and getattr(self, "config", {}).get("voice_dynamic_enabled", True)
            ):
                try:
                    audio = await pipeline.resolve(mapping.map_key, mapping.speech_id, mapping.locale, budget=4)
                except (OSError, ValueError, asyncio.TimeoutError):
                    audio = None
        if audio:
            from astrbot.api.message_components import Record
            yield event.chain_result([Record.fromFileSystem(str(audio))])

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
            lambda: self._send_delayed_notice(event, "正在查询联盟突袭战况...")
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
            lambda: self._send_delayed_notice(event, "正在查询与渲染角色卡片...")
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
                lambda: self._send_delayed_notice(
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
        """查询进行中与即将截止的官方活动日程。"""
        sub = str(horizon or "").strip().casefold()
        if sub in {"刷新", "refresh", "rescan"}:
            calendar = getattr(self, "calendar", None)
            if calendar is not None:
                if hasattr(calendar, "refresh_schedule_data"):
                    ok, msg = await calendar.refresh_schedule_data()
                else:
                    ok, msg = await calendar.sync_from_source()
                quality = getattr(calendar, "data_quality", "OK")
                yield event.plain_result(
                    f"【NIKKE 日程】数据刷新完成：{'成功' if ok else '失败（已保留旧快照）'} ({quality})\n"
                    f"当前活动条目数：{calendar.activity_count()}"
                    f"{f'，提示：{msg}' if msg != 'ok' else ''}"
                )
                return
            yield event.plain_result("日程服务尚未就绪。")
            return

        try:
            days = CalendarService.normalize_horizon(horizon)
        except ValueError as exc:
            yield event.plain_result(f"日程范围错误：{exc}\n用法：/妮姬 日程 [7|14|30] 或 /妮姬 日程 刷新")
            return

        calendar = getattr(self, "calendar", None)
        if calendar is None:
            if hasattr(self, "_spawn_background_task"):
                if hasattr(self, "_sync_announcements_background"):
                    self._spawn_background_task(self._sync_announcements_background())
                elif hasattr(self, "announcements") and hasattr(self.announcements, "sync_from_source"):
                    self._spawn_background_task(self.announcements.sync_from_source())
            yield event.plain_result("日程服务尚未就绪，正在后台同步，请稍后重试。")
            return

        if not calendar.has_snapshot():
            if hasattr(self, "_spawn_background_task"):
                if hasattr(self, "_sync_calendar_background"):
                    self._spawn_background_task(self._sync_calendar_background())
                elif hasattr(calendar, "refresh_schedule_data"):
                    self._spawn_background_task(calendar.refresh_schedule_data())
                elif hasattr(calendar, "sync_from_source"):
                    self._spawn_background_task(calendar.sync_from_source())
            yield event.plain_result("日程数据尚未就绪，正在后台同步，请稍后重试。")
            return

        payload = CalendarT2IPayloadBuilder().build(calendar, days)
        path_or_paths = await self._try_t2i("calendar_schedule", payload)
        if isinstance(path_or_paths, (list, tuple)):
            for p in path_or_paths:
                if p:
                    yield event.image_result(p)
        elif path_or_paths:
            yield event.image_result(path_or_paths)
        else:
            yield event.plain_result(payload["fallback_text"])
        return

    async def announcements_view(
        self,
        event: AstrMessageEvent,
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ):
        """查看本地缓存中的公告，可按已知 locale/category/关键词过滤。"""
        fallback_error = ""
        if self.announcements.record_count() == 0:
            try:
                success, msg = await asyncio.wait_for(self.announcements.sync_from_source(), timeout=4.0)
                if not success:
                    fallback_error = msg
            except asyncio.TimeoutError:
                fallback_error = "同步公告超时"
            except Exception as e:
                fallback_error = f"同步异常: {e}"
        try:
            text = self.announcements.format_announcements_text(
                5,
                fallback_error=fallback_error,
                locale=locale,
                category=category,
                query=query,
            )
        except ValueError as exc:
            text = f"公告查询参数无效：{exc}"
        yield event.plain_result(text)

    async def announcement_deep_rescan(self, event: AstrMessageEvent, locale: str = "en"):
        """管理员受限的公开只读深度公告重扫，不发送消息。"""
        if not self._is_admin(event):
            yield event.plain_result("仅机器人管理员可执行公告深度刷新。")
            return
        try:
            selected_locale = self.announcements.normalize_locale(locale)
        except ValueError as exc:
            yield event.plain_result(f"公告语言无效：{exc}")
            return
        try:
            success, message = await asyncio.wait_for(
                self.announcements.sync_from_source(locale=selected_locale, deep=True),
                timeout=40.0,
            )
        except asyncio.TimeoutError:
            yield event.plain_result("公告深度刷新超时，已保留原有缓存。")
            return
        except Exception as exc:
            yield event.plain_result(f"公告深度刷新异常：{exc}")
            return
        if not success:
            yield event.plain_result(message)
            return
        yield event.plain_result(message + " 仅执行公开只读同步，未发送消息。")

    async def announcement_subscription(self, event: AstrMessageEvent, action: str):
        """目标只取当前会话，禁止通过命令替其它会话订阅。"""
        if not self._is_admin(event):
            yield event.plain_result("仅机器人管理员可管理公告订阅。")
            return
        target = getattr(event, "unified_msg_origin", "")
        if not target:
            yield event.plain_result("当前适配器未提供可持久化会话目标。")
            return
        if action == "取消订阅":
            self.announcement_delivery.unsubscribe(target)
            yield event.plain_result("已取消当前会话的公告订阅。")
            return
        self.announcement_delivery.subscribe(target, self.announcements.list_announcements(limit=10000))
        suffix = "" if self.config.get("enable_announcement_push", False) else " 全局推送开关当前关闭，不会自动发送。"
        yield event.plain_result("已订阅当前会话；不补发已有公告，截止提醒为 24/6/1 小时。" + suffix)

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
        lock = getattr(self, "_termination_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._termination_lock = lock
        async with lock:
            if getattr(self, "_terminated", False):
                return
            self._closing = True
            cleanup_errors = []
            # 先停止生产任务，再关闭它们依赖的资源。
            tasks = list(getattr(self, "_background_tasks", ()))
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            feedback_manager = getattr(self, "feedback_manager", None)
            if feedback_manager is not None:
                try:
                    await feedback_manager.close()
                except Exception as exc:
                    cleanup_errors.append(exc)
                    logger.debug("[NIKKE] 反馈管理器回收失败：%s", safe_exception_message(exc))
            voice_pipeline = getattr(self, "voice_pipeline", None)
            if voice_pipeline is not None:
                try:
                    await voice_pipeline.close()
                except Exception as exc:
                    cleanup_errors.append(exc)
                    logger.debug("[NIKKE] 语音管线回收失败：%s", safe_exception_message(exc))
            else:
                for resource in (getattr(self, "voice_provider", None), getattr(self, "voice_encoder", None)):
                    close = getattr(resource, "close", None)
                    if close is not None:
                        try:
                            result = close()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as exc:
                            cleanup_errors.append(exc)
                            logger.debug("[NIKKE] 语音资源回收失败：%s", safe_exception_message(exc))
            asset_manager = getattr(self, "asset_manager", None)
            if asset_manager is not None:
                try:
                    asset_manager.close()
                except Exception as exc:
                    cleanup_errors.append(exc)
                    logger.debug("[NIKKE] 素材管理器回收失败：%s", safe_exception_message(exc))
            web = getattr(self, "web", None)
            if web is not None:
                try:
                    await web.stop()
                except Exception as exc:
                    cleanup_errors.append(exc)
                    logger.debug("[NIKKE] 绑定服务回收失败：%s", safe_exception_message(exc))
            if cleanup_errors:
                raise cleanup_errors[0]
            self._terminated = True
            logger.info("[NIKKE] 插件已停止")

    async def close(self):
        await self.terminate()
