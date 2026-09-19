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
import hashlib
import json
import os
import random
import re
import secrets
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

from ._version import PLUGIN_VERSION
from .core.container import create_container
from .features.daily.runner import DailyRunner
from .features.announcement.service import AnnouncementService
from .features.announcement.delivery import AnnouncementDelivery
from .features.calendar.service import CalendarService
from .core.asset_manager import AssetManager
from .features.campaign.builder import CampaignHistoryBuilder
from .features.campaign.models import ClearLineupStatus
from .ui.renderers import (
    CampaignHistoryRenderer,
    CharacterCardRenderer,
    ProfileCardRenderer,
    T2IRenderer,
    UnionRaidRenderer,
)
from .ui.primitives import CardRenderer
from .ui.t2i_payloads import CalendarT2IPayloadBuilder
from .features.tarot.service import TarotDataError, TarotService
from .features.campaign.stage_resolver import CampaignStageResolver
from .features.character.builder import CharacterCardBuilder
from .features.cdk.service import CDK_PATTERN, CdkInputParser, CdkService
from .features.character.identity import CharacterDirectoryResolver
from .integrations.blablalink.client import BlaBlaClient, BlaBlaError, CookieExpired, UnknownAfterAction
from .features.character.stat_resources import CharacterStatResourceLoader, map_research_levels
from .core.privacy import safe_exception_message
from .features.daily.models import DailyTaskResult, DailyTaskStatus
from .core.feedback import DelayedFeedbackManager
from .features.profile.builder import ProfileBuilder
from .core.health import collect_runtime_health, format_runtime_health
from .core.config import normalize_runtime_config, read_schedule_clock
from .integrations.spine.config import build_spine_renderer
from .core.storage import NikkeStore
from .features.raid.builder import UnionRaidBuilder
from .features.raid.models import PreviousSeasonSummary, RaidState
from .features.character.registries.costume import CostumeRegistry
from .features.tower.registry import TowerRegistry
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

        # 映射容器属性到 self，保留 100% 既有公开调用与测试字段契约
        self.extension_zip = self.container.extension_zip
        self.store = self.container.store
        self.character_stat_resources = self.container.character_stat_resources
        self.client = self.container.client
        self.renderer = self.container.renderer
        self.character_builder = self.container.character_builder
        self.character_identity = self.container.character_identity
        self.asset_manager = self.container.asset_manager
        self.character_renderer = self.container.character_renderer
        self.campaign_resolver = self.container.campaign_resolver
        self.profile_builder = self.container.profile_builder
        self.profile_renderer = self.container.profile_renderer
        self.raid_builder = self.container.raid_builder
        self.raid_renderer = self.container.raid_renderer
        self.campaign_builder = self.container.campaign_builder
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
        self.tower_registry = self.container.tower_registry
        self.daily_runner = self.container.daily_runner
        self.web = self.container.web

        self.public_base_url = str(
            self.config.get("public_base_url", "https://nikke.irises777.xyz")
        ).rstrip("/")
        self.web_host = str(self.config.get("web_host", "0.0.0.0"))
        self.web_port = int(self.config.get("web_port", 6210))
        self._directory: list[dict] = []
        self._name_map_cache: tuple[str, dict[str, str]] | None = None
        self._stats_profile_cache: dict[str, tuple[float, dict[str, object]]] = {}
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
            self.tower_registry = await asyncio.to_thread(
                TowerRegistry, self.plugin_dir / "assets" / "tower_floors.json"
            )
        except Exception as exc:
            logger.warning("[NIKKE] 塔层静态资料预热失败: %s", safe_exception_message(exc))
        try:
            await self.web.start(self.web_host, self.web_port)
            logger.info(f"[NIKKE] 绑定服务已监听 {self.web_host}:{self.web_port}")
        except Exception as exc:
            logger.error("[NIKKE] 绑定服务启动失败: %s", safe_exception_message(exc))
        try:
            self._directory = await self.client.get_directory()
            self.campaign_builder.update_directory(self._directory)
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
            await asyncio.to_thread(self.character_stat_resources.load_base)
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

    async def _get_profile_for_stat_calculation(self, account: dict[str, Any]) -> dict[str, Any]:
        """缓存一次 Outpost 研究快照，避免每张卡重复请求同一账号。"""
        cache_key = str(account.get("game_uid") or account.get("qq_id") or "account")
        now = time.monotonic()
        cached = self._stats_profile_cache.get(cache_key)
        if cached and now - cached[0] < 300:
            return cached[1]
        try:
            profile = await self.client.get_profile(account)
        except CookieExpired:
            raise
        except Exception as exc:
            logger.warning("[NIKKE] 研究快照读取失败：%s", safe_exception_message(exc))
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        # 限制缓存条目上限（最多 50 个账号），先淘汰过期条目，再淘汰最旧条目
        if len(self._stats_profile_cache) >= 50:
            expired = [k for k, v in self._stats_profile_cache.items() if now - v[0] >= 300]
            for k in expired:
                self._stats_profile_cache.pop(k, None)
            while len(self._stats_profile_cache) >= 50:
                oldest_k = min(self._stats_profile_cache, key=lambda k: self._stats_profile_cache[k][0])
                self._stats_profile_cache.pop(oldest_k, None)
        self._stats_profile_cache[cache_key] = (now, profile)
        return profile

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

    def _account_or_error(self, event: AstrMessageEvent) -> dict:
        account = self.store.get_account(self._qq_id(event))
        if not account:
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        return account

    def _name_map(self) -> dict[str, str]:
        """按实际目录内容生成 name_code -> display_name 映射。
        包含所有影响 display_name 与 enrich 的本地化字段：
        name_code, name_zh_cn, name_zh_tw, name_cn, name_en。
        采用确定性结构化 JSON 序列化杜绝字段边界歧义，以 SHA-256 建立指纹。
        """
        directory = getattr(self, "_directory", ()) or ()
        if not directory:
            return {}

        entries = [
            (
                str(item.get("name_code", "")),
                str(item.get("name_zh_cn", "")),
                str(item.get("name_zh_tw", "")),
                str(item.get("name_cn", "")),
                str(item.get("name_en", "")),
            )
            for item in directory
            if isinstance(item, dict)
        ]
        payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        cached = getattr(self, "_name_map_cache", None)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        resolver = getattr(self, "character_identity", None) or CharacterDirectoryResolver()
        mapping = {
            str(item.get("name_code", "")): resolver.display_name(resolver.enrich(item))
            for item in directory
            if isinstance(item, dict)
        }
        self._name_map_cache = (fingerprint, mapping)
        return mapping

    def _find_directory(self, query: str) -> list[dict]:
        resolver = getattr(self, "character_identity", None) or CharacterDirectoryResolver()
        return resolver.find(self._directory, query)

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
            registry = getattr(self, "tower_registry", None)
            if registry is None:
                try:
                    registry = await asyncio.to_thread(
                        TowerRegistry, self.plugin_dir / "assets" / "tower_floors.json"
                    )
                    self.tower_registry = registry
                except Exception:
                    registry = None
            if registry is not None:
                try:
                    result = registry.describe(arg1, arg2)
                except (OSError, ValueError, KeyError, TypeError):
                    result = "塔层静态资料暂不可用。"
            else:
                result = "塔层静态资料暂不可用。"
            yield event.plain_result(result)
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
        service = getattr(self, "tarot", None)
        if service is None:
            try:
                service = TarotService(
                    self.plugin_dir,
                    self.data_dir / "tarot",
                    deck_mode="auto",
                    rotate_reversed=True,
                )
                self.tarot = service
            except (OSError, ValueError, TarotDataError) as exc:
                logger.warning("[NIKKE] 塔罗服务不可用：%s", safe_exception_message(exc))
                yield event.plain_result("塔罗功能暂不可用：牌库资源尚未准备完成。")
                return

        action_key = str(action or "").strip().casefold()
        if action_key in {"", "帮助", "help"}:
            yield event.plain_result(service.format_help())
            return
        if action_key in {"状态", "status"}:
            yield event.plain_result(service.format_status())
            return

        try:
            if action_key in {"单抽", "单张", "single", "one"}:
                reading = service.draw_single()
            elif action_key in {"三张", "三张牌", "three", "spread"}:
                reading = service.draw_three()
            elif action_key in {"今日", "每日", "daily", "today"}:
                user_key = f"{event.get_platform_name()}:{self._qq_id(event)}"
                reading = service.draw_daily(user_key)
            else:
                yield event.plain_result("用法：/妮姬 塔罗 [单抽|三张|今日|状态|帮助]")
                return

            for image_path in service.image_paths(reading):
                if image_path is not None:
                    yield event.image_result(str(image_path))
            yield event.plain_result(service.format_reading(reading))
        except TarotDataError as exc:
            logger.warning("[NIKKE] 塔罗牌库错误：%s", safe_exception_message(exc))
            yield event.plain_result("塔罗牌库暂不可用，请稍后再试。")
        except (OSError, ValueError) as exc:
            logger.warning("[NIKKE] 塔罗抽牌失败：%s", safe_exception_message(exc))
            yield event.plain_result("塔罗抽牌失败，请稍后再试。")

    async def nikke_help(self, event: AstrMessageEvent, category: str = ""):
        """查看精简后的中文指令。"""
        yield event.plain_result(self._help_text(category, self._is_admin(event)))

    async def account(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """管理账号绑定、状态和每日汇总。"""
        action_key = action.strip().casefold()
        if action_key in {"", "状态", "status"}:
            async for result in self.status(event):
                yield result
            return
        if action_key in {"绑定", "bind"}:
            async for result in self.bind(event):
                yield result
            return
        if action_key in {"解绑", "unbind"}:
            async for result in self.unbind(event):
                yield result
            return
        if action_key in {"汇总", "push"}:
            if not value:
                yield event.plain_result("用法：/妮姬 账号 汇总 开|关")
                return
            async for result in self.push(event, value):
                yield result
            return
        yield event.plain_result("用法：/妮姬 账号 [绑定|状态|解绑|汇总 开|关]")

    async def bind(self, event: AstrMessageEvent):
        """生成一次性安全绑定链接及向导。"""
        if not event.is_private_chat() and not bool(self.config.get("allow_group_bind", False)):
            yield event.plain_result("为防止绑定链接被他人抢先使用，请私聊机器人发送 /妮姬 账号 绑定。")
            return
        token = secrets.token_urlsafe(36)
        self.store.create_bind_session(token, self._qq_id(event), 600)
        url = f"{self.public_base_url}/bind/{token}"
        message = (
            "🔐 NIKKE · BlaBlaLink 安全绑定\n\n"
            "绑定链接（10 分钟有效，仅可使用一次）：\n"
            f"{url}\n\n"
            "请勿转发此链接。\n\n"
            "打开后请按照网页内的完整教程完成：\n"
            "1. 安装 NIKKE QQ 安全绑定助手\n"
            "2. 登录 BlaBlaLink\n"
            "3. 点击扩展中的「已登录，提交绑定」\n\n"
            "账号密码只在 BlaBlaLink 官方网站输入，\n"
            "机器人不会接收或保存你的账号密码。"
        )
        yield event.plain_result(message)

    async def unbind(self, event: AstrMessageEvent):
        """解除自己的BlaBlaLink账号。"""
        removed = self.store.delete_account(self._qq_id(event))
        yield event.plain_result("已解除绑定。" if removed else "当前QQ尚未绑定。")

    async def status(self, event: AstrMessageEvent):
        """检查绑定和Cookie状态。"""
        account = self.store.get_account(self._qq_id(event), with_cookie=False)
        if not account:
            yield event.plain_result("未绑定，请私聊发送 /妮姬 账号 绑定。")
            return
        state = "有效" if account["cookie_valid"] else "已失效，请重新绑定"
        yield event.plain_result(
            f"已绑定：{account['nickname'] or account['role_name'] or '未命名指挥官'}\n"
            f"区服ID：{account['area_id'] or '待识别'}\nCookie：{state}\n"
            f"每日汇总：{'开启' if account['push_enabled'] else '关闭'}\n"
            f"自动签到：{'开启' if account.get('auto_daily_enabled') else '关闭'}"
        )

    @staticmethod
    def _profile_rows(
        account: dict,
        basic: dict,
        outpost: dict,
        campaign_resolver: CampaignStageResolver | None = None,
    ) -> list[tuple[str, str]]:
        """只使用真实响应已确认存在的字段生成档案行。"""
        normal_raw = basic.get("progress_normal_campaign", basic.get("progress_campaign_normal"))
        if normal_raw is not None and campaign_resolver is not None:
            stage_normal = campaign_resolver.resolve_id(normal_raw, mode_hint="NORMAL")
            normal_text = f"NORMAL {stage_normal.name}" if stage_normal else (f"未映射 · ID {normal_raw}" if re.fullmatch(r"\d+", str(normal_raw).strip()) else str(normal_raw))
        else:
            normal_text = str(normal_raw if normal_raw is not None else "未知")

        hard_raw = basic.get("progress_hard_campaign", basic.get("progress_campaign_hard"))
        if hard_raw is not None and campaign_resolver is not None:
            stage_hard = campaign_resolver.resolve_id(hard_raw, mode_hint="HARD")
            hard_text = f"HARD {stage_hard.name}" if stage_hard else (f"未映射 · ID {hard_raw}" if re.fullmatch(r"\d+", str(hard_raw).strip()) else str(hard_raw))
        else:
            hard_text = str(hard_raw if hard_raw is not None else "未知")

        rows = [
            ("指挥官", str(basic.get("nickname") or account.get("nickname") or account.get("role_name") or "未知")),
            ("区服", str(account.get("area_id") or "未知")),
            ("同步器", str(outpost.get("synchro_level", 0))),
            ("前哨等级", str(outpost.get("outpost_battle_level", 0))),
            ("普通主线", normal_text),
            ("困难主线", hard_text),
        ]

        optional = (
            ("lv", "指挥官等级"),
            ("team_combat", "部队总战力"),
            ("created_at", "注册时间"),
            ("character_count", "持有妮姬"),
            ("character_costume_count", "时装数量"),
            ("progress_tribe_tower", "无尽塔进度"),
            ("sim_room_overclock_current_sub_season_high_score", "模拟室超频分数"),
        )
        for key, label in optional:
            if key in basic and basic[key] not in (None, ""):
                value = basic[key]
                if key == "team_combat" and isinstance(value, (int, float)):
                    value = f"{int(value):,}"
                rows.append((label, str(value)))

        outpost_optional = (
            ("infra_core_level", "基础核心等级"),
            ("jukebox_count", "点唱机收集"),
        )
        for key, label in outpost_optional:
            if key in outpost and outpost[key] not in (None, ""):
                rows.append((label, str(outpost[key])))

        researches = outpost.get("recycle_room_researches")
        if isinstance(researches, list):
            levels = [int(item.get("lv", 0) or 0) for item in researches if isinstance(item, dict)]
            rows.append(("回收室研究", f"{len(levels)} 项 · 等级合计 {sum(levels)}"))
        memorials = outpost.get("memorial_counts")
        if isinstance(memorials, list):
            count = sum(int(item.get("count", 0) or 0) for item in memorials if isinstance(item, dict))
            rows.append(("收藏记录", str(count)))
        return rows

    async def me(self, event: AstrMessageEvent):
        """生成个人账号概览卡。"""
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self._send_delayed_notice(event, "正在生成个人账号概览...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            account = self._account_or_error(event)
            data = await self.client.get_profile_dashboard(account)
            dashboard = self.profile_builder.build(
                account=account,
                basic=data["basic"],
                outpost=data["outpost"],
                roster=data["roster"],
                outpost_available=data.get("outpost_available"),
                roster_available=data.get("roster_available"),
                daily=data.get("daily"),
                daily_available=data.get("daily_available"),
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            path = await self._try_t2i("profile", dashboard)
            if not path:
                path = await asyncio.to_thread(self.profile_renderer.render_profile, dashboard)
            yield event.image_result(path)
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
        from .features.raid.participants import build_ranking, format_ranking
        try:
            account = self._account_or_error(event)
            payload = await self.client.get_union_raid_data(account)
            scope = "CURRENT_RESPONSE"
            builder = getattr(self, "raid_builder", None)
            if builder is None:
                builder = UnionRaidBuilder()
                self.raid_builder = builder
            if not payload.get("participate_data"):
                manager = payload.get("manager_info") or {}
                raid_state = builder.resolve_raid_state(
                    manager, payload.get("level_info"), seasons=builder._seasons
                )
                if raid_state == RaidState.OFFSEASON and builder._seasons:
                    latest = max(
                        (s for s in builder._seasons if s.get("end_ts", 0) <= time.time()),
                        key=lambda x: x.get("id", 0),
                        default=None,
                    )
                    if latest:
                        s_id = str(latest.get("id"))
                        try:
                            overview = await self.client.get_union_raid_overview(account)
                            guild_id = overview.get("guild_id")
                            if guild_id:
                                hist_data = await self.client.get_union_raid_season(
                                    account, guild_id=str(guild_id), season_id=s_id, levels=False
                                )
                                if hist_data.get("participate_data"):
                                    payload = hist_data
                                    s_num = int(s_id) % 1000000 if s_id.isdigit() else s_id
                                    scope = f"第 {s_num} 季 · LAST_SEASON_RESPONSE"
                        except Exception as exc:
                            logger.warning("[NIKKE] 回退上一赛季排名失败: %s", exc)
            data = build_ranking(payload)
            if scope != "CURRENT_RESPONSE":
                data.scope = scope
            path = await self._try_t2i("union_records", data)
            yield event.image_result(path) if path else event.plain_result(format_ranking(data))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新绑定。")
        except (BlaBlaError, ValueError):
            yield event.plain_result("突袭排名暂不可用：数据不完整或请求失败，请稍后重试。")

    async def union_raid_my(self, event: AstrMessageEvent):
        """展示当前响应中与当前账号稳定 openid 精确匹配的突袭记录。"""
        from .features.raid.participants import build_member_ranking, format_ranking
        try:
            account = self._account_or_error(event)
            member_openid = str(account.get("game_openid") or "").strip()
            if not member_openid:
                yield event.plain_result("当前账号缺少稳定联盟身份，暂不能安全筛选个人记录。")
                return
            payload = await self.client.get_union_raid_data(account)
            builder = getattr(self, "raid_builder", None)
            if builder is None:
                builder = UnionRaidBuilder()
                self.raid_builder = builder
            if not payload.get("participate_data"):
                manager = payload.get("manager_info") or {}
                raid_state = builder.resolve_raid_state(
                    manager, payload.get("level_info"), seasons=builder._seasons
                )
                if raid_state == RaidState.OFFSEASON and builder._seasons:
                    latest = max(
                        (s for s in builder._seasons if s.get("end_ts", 0) <= time.time()),
                        key=lambda x: x.get("id", 0),
                        default=None,
                    )
                    if latest:
                        s_id = str(latest.get("id"))
                        try:
                            overview = await self.client.get_union_raid_overview(account)
                            guild_id = overview.get("guild_id")
                            if guild_id:
                                hist_data = await self.client.get_union_raid_season(
                                    account, guild_id=str(guild_id), season_id=s_id, levels=False
                                )
                                if hist_data.get("participate_data"):
                                    payload = hist_data
                        except Exception as exc:
                            logger.warning("[NIKKE] 回退上一赛季个人记录失败: %s", exc)
            data = build_member_ranking(payload, member_openid)
            path = await self._try_t2i("union_member", data)
            yield event.image_result(path) if path else event.plain_result(format_ranking(data))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新绑定。")
        except (BlaBlaError, ValueError):
            yield event.plain_result("我的突袭记录暂不可用：数据不完整或请求失败，请稍后重试。")

    async def union_raid(self, event: AstrMessageEvent):
        """查询当前账号所属联盟的联盟突袭战况。"""
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self._send_delayed_notice(event, "正在查询联盟突袭战况...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            account = self._account_or_error(event)
            raw = await self.client.get_union_raid_overview(account)
            builder = getattr(self, "raid_builder", None)
            if builder is None:
                builder = UnionRaidBuilder()
                self.raid_builder = builder
            data = builder.build(
                guild_name=raw["guild_name"],
                level_info_payload=raw["level_info"],
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            if data.raid_state == RaidState.OFFSEASON and data.previous_season:
                guild_id = raw.get("guild_id")
                if guild_id and data.previous_season.season_id:
                    try:
                        hist_data = await self.client.get_union_raid_season(
                            account,
                            guild_id=str(guild_id),
                            season_id=str(data.previous_season.season_id),
                            levels=False,
                        )
                        attacks = hist_data.get("participate_data", [])
                        if isinstance(attacks, list):
                            tot_attacks = len(attacks)
                            tot_damage = sum(
                                int(x.get("total_damage", 0) or x.get("damage", 0) or 0)
                                for x in attacks
                            )
                            prev = data.previous_season
                            data.previous_season = PreviousSeasonSummary(
                                season_id=prev.season_id,
                                season_number=prev.season_number,
                                start_at=prev.start_at,
                                end_at=prev.end_at,
                                settled_at=prev.settled_at,
                                total_attacks=tot_attacks,
                                total_damage=tot_damage,
                                boss_progress=prev.boss_progress,
                            )
                    except Exception as exc:
                        logger.warning("[NIKKE] 获取上一赛季突袭数据失败: %s", exc)
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
            account = self._account_or_error(event)
            characters = await self.client.get_roster(account, True)
            path = self.renderer.render_roster(
                account.get("nickname") or account.get("role_name") or "指挥官",
                characters,
                self._name_map(),
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
            account = self._account_or_error(event)
            identity = getattr(self, "character_identity", None) or CharacterDirectoryResolver()
            matches = identity.find(self._directory, name)
            if not matches:
                raise ValueError("没有找到该妮姬")
            if len(matches) > 1:
                candidates = "\n".join(
                    f"{index}. {identity.display_name(item)}"
                    for index, item in enumerate(matches[:10], 1)
                )
                suffix = "\n候选过多，请继续补全名称。" if len(matches) > 10 else ""
                yield event.plain_result(
                    "找到多个角色，请输入更完整的名称：\n\n"
                    + candidates
                    + suffix
                )
                return
            target = matches[0]
            code = str(target.get("name_code", ""))
            try:
                payload = await self.client.get_character_detail(account, code)
            except ValueError as exc:
                if "未持有" in str(exc):
                    yield event.plain_result(
                        f"你未持有该妮姬：{identity.display_name(target)}"
                    )
                    return
                raise
            profile = await self._get_profile_for_stat_calculation(account)
            outpost = profile.get("outpost", {}) if isinstance(profile, dict) else {}
            account_for_card = dict(account)
            account_for_card["research_levels"] = map_research_levels(
                outpost.get("recycle_room_researches") if isinstance(outpost, dict) else None
            )
            try:
                payload = await asyncio.to_thread(
                    self.character_stat_resources.prepare_payload,
                    payload,
                )
            except Exception as exc:
                logger.warning("[NIKKE] 角色静态属性资源准备失败：%s", safe_exception_message(exc))
            card = self.character_builder.build(
                account=account_for_card,
                directory=target,
                payload=payload,
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            path = await self._try_t2i("character", card)
            if not path:
                path = await asyncio.to_thread(self.character_renderer.render_character, card)
            yield event.image_result(path)
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
        matches = self._find_directory(name)
        if not matches:
            yield event.plain_result("没有找到该妮姬。")
            return
        item = matches[0]
        identity = getattr(self, "character_identity", None) or CharacterDirectoryResolver()
        item = identity.enrich(item)
        names = identity.display_name(item)
        zh_tw = item.get("name_zh_tw") or item.get("name_cn") or "未知"
        name_suffix = f"{names} / {zh_tw} / {item.get('name_en') or '未知'}"
        rows = [
            ("名称（简体别名 / 繁中 / 英文）", name_suffix),
            ("稀有度", str(item.get("rare") or "未知")),
            ("属性", str(item.get("element") or "未知")),
            ("武器", str(item.get("weapon") or "未知")),
            ("爆裂阶段", str(item.get("burst") or "未知")),
            ("企业", str(item.get("corporation") or "未知")),
        ]
        path = self.renderer.render(names or name, "妮姬基础资料", rows)
        yield event.image_result(path)

    @staticmethod
    def _daily_error_result(account_name: str, prefix: str, exc: Exception) -> DailyTaskResult:
        """把异常映射到保守状态，避免所有异常都显示为泛化失败。"""
        return DailyRunner.daily_error_result(account_name, prefix, exc)

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

    async def _read_only_daily_recovery(self, account: dict, account_name: str) -> DailyTaskResult:
        """恢复未决任务时只读核验，绝不重放签到写操作。"""
        return await self.daily_runner.read_only_daily_recovery(account, account_name)

    @staticmethod
    def _daily_identity(account: dict) -> str:
        """构造不依赖 QQ 的稳定游戏账号作用域。"""
        return DailyRunner.daily_identity(account)

    @classmethod
    def _daily_run_key(cls, day: str, account: dict, action: str) -> str:
        return DailyRunner.daily_run_key(day, account, action)

    def _legacy_daily_guard(self, day: str, qq_id: str, action: str, account_name: str) -> DailyTaskResult | None:
        """发现旧 QQ 作用域记录时显式阻断，不把它静默当成新账号结果。"""
        return self.daily_runner.legacy_daily_guard(day, qq_id, action, account_name)

    async def _run_daily_for_account(self, account: dict, day: str) -> DailyTaskResult:
        return await self.daily_runner.run_daily_for_account(account, day)

    async def _run_all_daily(
        self,
        day: str,
        stagger: bool = False,
        automatic: bool = False,
    ) -> list[DailyTaskResult]:
        return await self.daily_runner.run_all_daily(day, stagger=stagger, automatic=automatic)

    async def _send_summary(self, day: str) -> None:
        group_umo = self.store.get_setting("summary_group_umo", "")
        if not group_umo:
            logger.warning("[NIKKE] 尚未配置每日汇总群")
            return
        # 只读取自动批次结果；旧的无 scope 键和管理员手动结果都不作为自动汇总来源。
        stored = self.store.get_setting(f"daily_results:{day}:automatic", [])
        results = [DailyTaskResult.from_storage(item) for item in stored] if isinstance(stored, list) else []
        if not results or any(result is None for result in results):
            results = await self._run_all_daily(day, automatic=True)
        path = self.renderer.render_summary([result.summary_row() for result in results])
        await self.context.send_message(group_umo, MessageChain([Image.fromFileSystem(path)]))

    async def _daily_status(self, event: AstrMessageEvent):
        """只读查询当前账号的每日签到状态。"""
        try:
            account = self._account_or_error(event)
            await self.client.get_profile(account)
            status = await self.client.get_daily_signin(account)
            if not status["found"]:
                result = DailyTaskResult("", DailyTaskStatus.UNAVAILABLE, "未找到签到任务")
            elif status["completed"]:
                result = DailyTaskResult("", DailyTaskStatus.ALREADY_DONE, "今日已签到")
            else:
                result = DailyTaskResult("", DailyTaskStatus.PENDING, "今日待签到")
            yield event.plain_result(result.detail)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            yield event.plain_result(f"查询失败：{exc}")

    async def daily(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """直接签到、只读查询，或设置自己的定时签到偏好。"""
        action_key = action.strip().casefold()
        if action_key in {"状态", "status"}:
            async for result in self._daily_status(event):
                yield result
            return
        if action_key in {"自动", "auto"}:
            value_key = value.strip().casefold()
            if value_key not in {"开", "on", "1", "关", "off", "0"}:
                yield event.plain_result("用法：/妮姬 日常 自动 开|关")
                return
            try:
                account = self._account_or_error(event)
            except ValueError as exc:
                yield event.plain_result(str(exc))
                return
            enabled = value_key in {"开", "on", "1"}
            self.store.set_auto_daily(account["qq_id"], enabled)
            global_state = "全局签到写操作当前关闭；设置已保存，暂不会提交。" if not bool(
                self.config.get("enable_daily_actions", False)
            ) else "仍需保持每日汇总开启，定时任务才会处理此账号。"
            yield event.plain_result(
                f"自动签到已{'开启' if enabled else '关闭'}。{global_state}"
            )
            return
        if action_key:
            yield event.plain_result("用法：/妮姬 签到 [状态] 或 /妮姬 日常 自动 开|关")
            return
        if not bool(self.config.get("enable_daily_actions", False)):
            yield event.plain_result("签到写操作当前由管理员关闭；可使用 /妮姬 签到 状态 只读查询。")
            return
        try:
            account = self._account_or_error(event)
            result = await self._run_daily_for_account(account, datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
            yield event.plain_result(f"{result.account_name}：{result.detail}")
        except Exception as exc:
            yield event.plain_result(f"签到失败：{exc}")

    async def claim(self, event: AstrMessageEvent):
        """兼容旧版英文签到指令。"""
        async for result in self.daily(event):
            yield result

    @staticmethod
    def _mask_cdk(code: str) -> str:
        return code[:2] + "***" + code[-2:] if len(code) > 4 else "***"

    async def cdk(self, event: AstrMessageEvent, code: str):
        """使用当前绑定账号兑换国际服CDK。"""
        if not bool(self.config.get("enable_cdk_redemption", False)):
            yield event.plain_result("CDK真实兑换当前由管理员关闭。")
            return
        normalized = code.strip()
        if not CDK_PATTERN.fullmatch(normalized):
            yield event.plain_result("兑换码格式无效：仅支持4至64位字母、数字、下划线或连字符。")
            return
        qq_id = self._qq_id(event)
        masked = self._mask_cdk(normalized)
        try:
            account = self._account_or_error(event)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        game_uid = str(account.get("game_uid") or account.get("uid") or "").strip()
        if not game_uid:
            yield event.plain_result("账号缺少稳定游戏身份，未执行兑换。")
            return
        account_key = f"{qq_id}:{game_uid}"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        run_key = f"cdk:{qq_id}:{game_uid}:{digest}"
        retryable = {"failed", "expired"}
        existing = self.store.get_run(run_key)
        if existing and existing["status"] not in retryable:
            if existing["status"] == "running":
                changed = self.store.mark_stale_running_unknown(
                    run_key, stale_after=120, detail="兑换结果未确认，请先检查官方兑换历史。")
                current = self.store.get_run(run_key)
                if changed or (current and current["status"] == "unknown"):
                    yield event.plain_result("兑换结果未确认，请先检查官方兑换历史，勿重复提交。")
                else:
                    yield event.plain_result(f"兑换码 {masked} 正在处理，请勿重复提交。")
                return
            yield event.plain_result(existing["detail"] or f"兑换码 {masked} 已处理。")
            return
        if existing:
            if not self.store.retry_run(run_key, retryable):
                yield event.plain_result(f"兑换码 {masked} 正在处理，请稍后再试。")
                return
        elif not self.store.claim_run(run_key, qq_id, "cdk"):
            yield event.plain_result(f"兑换码 {masked} 正在处理，请勿重复提交。")
            return
        try:
            result = await self.cdk_service.redeem_single(account, normalized, account_key=account_key)
            detail = f"兑换码 {masked}：{result.message}"
            if result.success:
                status = "success"
            elif result.is_unknown:
                status = "unknown"
            elif result.is_rate_limited or not getattr(result, "terminal", True):
                status = "failed"
            else:
                status = "terminal"
            # 上游消息可能回显完整兑换码，仅持久化固定状态说明。
            stored_detail = {"success": "兑换成功", "unknown": "结果未确认，请核对官方历史",
                             "failed": "请求失败，可稍后重试", "terminal": "官方已拒绝此码"}[status]
            self.store.finish_run(run_key, status, f"兑换码 {masked}：{stored_detail}")
            yield event.plain_result(detail)
        except CookieExpired:
            self.store.mark_cookie_invalid(qq_id)
            self.store.finish_run(run_key, "expired", "登录状态已失效")
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except asyncio.CancelledError:
            self.store.finish_run(run_key, "unknown", "兑换中断，结果未确认，请先检查官方历史")
            raise
        except Exception as exc:
            self.store.finish_run(run_key, "failed", f"兑换码 {masked}：请求失败，可稍后重试")
            logger.warning(f"[NIKKE] CDK兑换失败: {type(exc).__name__}")
            yield event.plain_result(f"兑换码 {masked}：请求失败，可稍后重试。")

    async def cdk_batch(self, event: AstrMessageEvent, raw_codes: str):
        """批量兑换多个 CDK。"""
        if not bool(self.config.get("enable_cdk_redemption", False)):
            yield event.plain_result("CDK真实兑换当前由管理员关闭。")
            return
        codes = CdkInputParser.parse(raw_codes, max_items=10)
        if not codes:
            yield event.plain_result("未检测到有效的兑换码。支持空格/换行/逗号分隔，单次最多10个。")
            return
        try:
            account = self._account_or_error(event)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        qq_id = self._qq_id(event)
        game_uid = str(account.get("game_uid") or account.get("uid") or "default").strip()
        account_key = f"{qq_id}:{game_uid}"
        batch_res = await self.cdk_service.redeem_batch(account, codes, account_key=account_key, store=self.store, qq_id=qq_id)
        lines = [f"【CDK 批量兑换结果】共 {len(batch_res.results)} 项："]
        for res in batch_res.results:
            masked = self._mask_cdk(res.code)
            icon = "✓" if res.success else ("?" if res.is_unknown else "✗")
            lines.append(f"{icon} {masked}：{res.message}")
        if batch_res.stopped_by_cookie:
            self.store.mark_cookie_invalid(qq_id)
            lines.append("\n⚠️ 登录状态已失效，已中止剩余兑换。请重新绑定。")
        elif batch_res.stopped_by_rate_limit:
            lines.append("\n⚠️ 遇到官方频控限制，已中止剩余兑换，请稍后再试。")
        yield event.plain_result("\n".join(lines))

    async def cdk_available(self, event: AstrMessageEvent):
        """查询官方可用 CDK 列表。"""
        try:
            account = self._account_or_error(event)
            items = await self.client.get_cdk_redemption(account)
            if not items:
                yield event.plain_result("官方暂无可查询的可用 CDK 列表。")
                return

            available_items = [
                item
                for item in items
                if isinstance(item, dict)
                and item.get("status") in (None, 0, "0")
            ]
            if not available_items:
                yield event.plain_result("官方暂无可查询的可用 CDK 列表。")
                return

            lines = ["【官方可用 CDK 列表】"]
            for item in available_items[:15]:
                code = str(
                    item.get("cdk")
                    or item.get("cdkey")
                    or item.get("code")
                    or item.get("title")
                    or "未知"
                )
                desc = str(item.get("desc") or item.get("reward") or "").strip()
                expire = str(item.get("expire_time") or item.get("end_time") or "").strip()
                extra = f" ({desc})" if desc else ""
                exp_str = f" [截止: {expire}]" if expire else ""
                lines.append(f"• {code}{extra}{exp_str}")
            yield event.plain_result("\n".join(lines))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            yield event.plain_result(f"获取可用 CDK 失败：{exc}")

    async def cdk_history(self, event: AstrMessageEvent):
        """查询官方 CDK 历史兑换记录。"""
        try:
            account = self._account_or_error(event)
            items = await self.client.get_cdk_redemption_history(account)
            if not items:
                yield event.plain_result("官方暂无 CDK 兑换历史记录。")
                return
            lines = ["【CDK 兑换历史记录】"]
            for item in items[:15]:
                code = str(
                    item.get("cdk")
                    or item.get("cdkey")
                    or item.get("code")
                    or "未知"
                )
                masked = self._mask_cdk(code)
                status = str(item.get("status") or item.get("result") or item.get("msg") or "已兑换")
                time_str = str(item.get("redeemed_at") or item.get("created_at") or item.get("time") or "").strip()
                t = f" [{time_str}]" if time_str else ""
                lines.append(f"• {masked}: {status}{t}")
            yield event.plain_result("\n".join(lines))
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            yield event.plain_result(f"获取 CDK 历史失败：{exc}")

    async def campaign(self, event: AstrMessageEvent, stage_str: str = "", mode_str: str = ""):
        """查询主线战役关卡的历史通关阵容。"""
        query = f"{stage_str} {mode_str}".strip()
        if not query:
            yield event.plain_result("用法：/妮姬 战役 [普通/困难] <关卡名>（例如：46-40、困难 35-36）")
            return
        stage = self.campaign_resolver.resolve_query(query)
        if not stage:
            yield event.plain_result(f"未找到关卡：{query}。目前仅支持已收录关卡（如普通46章、困难35章）。")
            return
        handle = self.feedback_manager.start_delayed_feedback(
            lambda: self._send_delayed_notice(event, "正在查询战役通关阵容...")
        ) if hasattr(self, "feedback_manager") and self.feedback_manager else None
        try:
            account = self._account_or_error(event)
            raw = await self.client.get_main_quest_clear_lineup(
                account, stage_id=stage.stage_id, area_id=account.get("area_id", 0)
            )
            if self._directory and not self.campaign_builder._directory_by_tid:
                self.campaign_builder.update_directory(self._directory)
            record = self.campaign_builder.build(
                stage=stage,
                response=raw,
                commander_name=account.get("nickname") or account.get("role_name") or "指挥官",
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            if record.status == ClearLineupStatus.RATE_LIMITED:
                yield event.plain_result(record.status_message)
                return
            if record.status == ClearLineupStatus.ERROR:
                yield event.plain_result(record.status_message)
                return
            path = await self._render_campaign_record(record)
            yield event.image_result(path)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            yield event.plain_result(f"战役查询失败：{safe_exception_message(exc)}")
        except Exception as exc:
            logger.error("[NIKKE] 战役查询异常: %s", safe_exception_message(exc))
            yield event.plain_result(f"战役查询异常：{safe_exception_message(exc)}")
        finally:
            if handle:
                await handle.cancel()

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
        cat_key = category.strip().lower()
        mapping = {
            "练度": "progression",
            "progression": "progression",
            "红球": "red_orbs",
            "red球": "red_orbs",
            "red_orb": "red_orbs",
            "red_orbs": "red_orbs",
            "珍藏品": "favorite",
            "收藏品": "favorite",
            "favorite": "favorite",
            "favorite_item": "favorite",
            "充能": "arena_charge",
            "竞技场": "arena_charge",
            "竞技场充能": "arena_charge",
            "arena_charge": "arena_charge",
            "洗词条": "overload",
            "词条": "overload",
            "overload": "overload",
            "pvp": "pvp",
            "配队": "pvp",
            "pvp配队": "pvp",
            "竞技场配队": "pvp",
        }
        if not cat_key or cat_key not in mapping:
            yield event.plain_result(
                "【NIKKE 常用攻略一图流】\n\n"
                "支持查看以下分类攻略图：\n"
                "• /妮姬 攻略 练度 — 角色培养与技能升级一图流\n"
                "• /妮姬 攻略 红球 — 同步器等级与红球消耗一览表\n"
                "• /妮姬 攻略 珍藏品 — 珍藏品养成与材料汇总\n"
                "• /妮姬 攻略 充能 — 竞技场爆裂充能速查表\n\n"
                "• /妮姬 攻略 洗词条 — Overload 词条教学\n"
                "• /妮姬 攻略 PVP — 竞技场配队参考\n\n"
                "仅发送 registry 中已登记的授权素材或白名单 HTTPS 链接。"
            )
            return

        folder_name = mapping[cat_key]
        if not page.isascii() or not page.isdigit() or not 1 <= int(page) <= 10000:
            yield event.plain_result("页码应为正整数，例如：/妮姬 攻略 练度 2")
            return
        page_number = int(page)
        from .features.guide.registry import GuideRegistry
        try:
            registry = GuideRegistry(self.plugin_dir / "assets" / "guides")
            entries = registry.page(folder_name, page=page_number)
        except (ValueError, OSError):
            yield event.plain_result("攻略索引暂不可用，请管理员核对授权和文件配置。")
            return
        if entries:
            total = sum(entry.category == folder_name for entry in registry.entries)
            yield event.plain_result(f"【{category}】第 {page_number}/{(total + 2)//3} 页；使用 /妮姬 攻略 {category} <页码> 翻页。")
            for entry in entries:
                yield event.plain_result(entry.caption())
                for image in entry.files[:10]:
                    yield event.image_result(str(image))
                for link in entry.links:
                    yield event.plain_result(link)
            return
        if page_number > 1 or any(entry.category == folder_name for entry in registry.entries):
            yield event.plain_result("该攻略页不存在。")
            return
        yield event.plain_result(f"暂未收录【{category}】攻略图，当前保留占位，等待后续登记素材。")

    async def push(self, event: AstrMessageEvent, state: str):
        """开启或关闭每日群汇总。"""
        enabled = state.lower() in {"on", "开", "开启", "1"}
        if state.lower() not in {"on", "off", "开", "关", "开启", "关闭", "1", "0"}:
            yield event.plain_result("用法：/妮姬 账号 汇总 开|关")
            return
        changed = self.store.set_push(self._qq_id(event), enabled)
        yield event.plain_result(("每日汇总已开启。" if enabled else "每日汇总已关闭。") if changed else "请先绑定账号。")

    async def admin(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """管理员配置与运行入口。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可使用管理指令。")
            return
        action_key = action.strip().casefold()
        if action_key in {"设群", "group"}:
            async for result in self.group_set(event):
                yield result
            return
        if action_key in {"任务时间", "schedule"}:
            async for result in self.schedule(event, value):
                yield result
            return
        if action_key in {"汇总时间", "summary"}:
            async for result in self.summary(event, value):
                yield result
            return
        if action_key in {"执行", "run"}:
            async for result in self.run(event):
                yield result
            return
        if action_key in {"健康", "health"}:
            async for result in self.health(event):
                yield result
            return
        yield event.plain_result("用法：/妮姬 管理 [设群|任务时间 HH:MM|汇总时间 HH:MM|执行|健康]")

    async def group_set(self, event: AstrMessageEvent, action: str = "set"):
        """管理员将当前会话设为每日汇总目标。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可配置汇总群。")
            return
        if action.strip().casefold() not in {"", "set", "设群"}:
            yield event.plain_result("用法：/妮姬 管理 设群")
            return
        self.store.set_setting("summary_group_umo", event.unified_msg_origin)
        yield event.plain_result(f"每日汇总目标已设为当前会话：{event.unified_msg_origin}")

    @staticmethod
    def _parse_clock(value: str) -> tuple[int, int]:
        hour, minute = value.split(":", 1)
        h, m = int(hour), int(minute)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("时间范围错误")
        return h, m

    async def schedule(self, event: AstrMessageEvent, clock: str):
        """管理员设置每日任务开始时间。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可修改时间。")
            return
        try:
            h, m = self._parse_clock(clock)
            self.store.set_setting("daily_hour", h)
            self.store.set_setting("daily_minute", m)
            yield event.plain_result(f"每日任务时间已设为 {h:02d}:{m:02d}。")
        except Exception:
            yield event.plain_result("用法：/妮姬 管理 任务时间 HH:MM")

    async def summary(self, event: AstrMessageEvent, clock: str):
        """管理员设置每日汇总时间。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可修改时间。")
            return
        try:
            h, m = self._parse_clock(clock)
            self.store.set_setting("summary_hour", h)
            self.store.set_setting("summary_minute", m)
            yield event.plain_result(f"每日汇总时间已设为 {h:02d}:{m:02d}。")
        except Exception:
            yield event.plain_result("用法：/妮姬 管理 汇总时间 HH:MM")

    async def run(self, event: AstrMessageEvent):
        """管理员立即执行并发送汇总。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可执行全量任务。")
            return
        day = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        results = await self._run_all_daily(day)
        path = self.renderer.render_summary(results)
        yield event.image_result(path)

    async def health(self, event: AstrMessageEvent):
        """管理员查看插件健康状态；诊断只读，不执行缓存清理。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可查看。")
            return
        accounts = self.store.list_accounts(with_cookie=False)
        diagnostics = format_runtime_health(collect_runtime_health(self.data_dir))
        yield event.plain_result(
            f"NIKKE插件 {PLUGIN_VERSION}\n账号：{len(accounts)}\n目录：{len(self._directory)}\n"
            f"绑定服务：{self.web_host}:{self.web_port}\n"
            f"自动签到：{'启用' if self.config.get('enable_daily_actions', False) else '关闭'}\n"
            f"CDK兑换：{'启用' if self.config.get('enable_cdk_redemption', False) else '关闭'}\n"
            f"{diagnostics}"
        )

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