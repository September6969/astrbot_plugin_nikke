# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 综合助手 AstrBot 插件。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register

from ._version import PLUGIN_VERSION
from .card_builder import CharacterCardBuilder
from .asset_manager import AssetManager
from .character_card_renderer import CharacterCardRenderer
from .profile_builder import ProfileBuilder
from .profile_card_renderer import ProfileCardRenderer
from .client import BlaBlaClient, BlaBlaError, CookieExpired
from .renderer import CardRenderer
from .storage import NikkeStore
from .web_service import BindingWebService


@register(
    "astrbot_plugin_nikke",
    "September",
    "NIKKE BlaBlaLink 账号练度、资料查询与每日汇总",
    PLUGIN_VERSION,
    "https://github.com/September6969/astrbot_plugin_nikke",
)
class NikkePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = Path("data") / "nikke"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.extension_zip = self.data_dir / "nikke-bind-extension.zip"
        self.store = NikkeStore(self.data_dir)
        self.client = BlaBlaClient(
            int(self.config.get("request_timeout", 20)),
            lambda message: logger.info(f"[NIKKE诊断] {message}"),
        )
        self.renderer = CardRenderer(self.data_dir / "cards", self.plugin_dir / "fonts")
        self.character_builder = CharacterCardBuilder()
        self.character_renderer = CharacterCardRenderer(
            self.data_dir / "cards",
            self.plugin_dir / "fonts",
            AssetManager(self.data_dir / "cache", self.plugin_dir / "assets", remote=True),
        )
        self.profile_builder = ProfileBuilder()
        self.profile_renderer = ProfileCardRenderer(self.data_dir / "cards", self.plugin_dir / "fonts")
        self.web = BindingWebService(
            self.store,
            self.client,
            self.extension_zip,
            str(self.config.get("binding_api_key", "")),
            public_base_url=str(self.config.get("public_base_url", "https://nikke.irises777.xyz")),
        )
        self.public_base_url = str(
            self.config.get("public_base_url", "https://nikke.irises777.xyz")
        ).rstrip("/")
        self.web_host = str(self.config.get("web_host", "0.0.0.0"))
        self.web_port = int(self.config.get("web_port", 6210))
        self._directory: list[dict] = []
        self._background_tasks: list[asyncio.Task] = []
        self._closing = False
        self._pack_extension()
        self._background_tasks.append(asyncio.create_task(self._start_services()))

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
            await self.web.start(self.web_host, self.web_port)
            logger.info(f"[NIKKE] 绑定服务已监听 {self.web_host}:{self.web_port}")
        except Exception as exc:
            logger.error(f"[NIKKE] 绑定服务启动失败: {exc}")
        try:
            self._directory = await self.client.get_directory()
            logger.info(f"[NIKKE] 已载入 {len(self._directory)} 条妮姬目录")
        except Exception as exc:
            logger.warning(f"[NIKKE] 妮姬目录载入失败: {exc}")
        await self._scheduler_loop()

    async def _scheduler_loop(self) -> None:
        last_daily = ""
        last_summary = ""
        while not self._closing:
            now = datetime.now(timezone(timedelta(hours=8)))
            today = now.strftime("%Y-%m-%d")
            daily_h = int(self.store.get_setting("daily_hour", self.config.get("daily_hour", 8)))
            daily_m = int(self.store.get_setting("daily_minute", self.config.get("daily_minute", 10)))
            summary_h = int(self.store.get_setting("summary_hour", self.config.get("summary_hour", 8)))
            summary_m = int(self.store.get_setting("summary_minute", self.config.get("summary_minute", 30)))
            if (now.hour, now.minute) == (daily_h, daily_m) and last_daily != today:
                last_daily = today
                asyncio.create_task(self._run_all_daily(today, stagger=True))
            if (now.hour, now.minute) == (summary_h, summary_m) and last_summary != today:
                last_summary = today
                asyncio.create_task(self._send_summary(today))
            await asyncio.sleep(20)

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
        return {
            str(item.get("name_code", "")): str(item.get("name_cn") or item.get("name_en") or "")
            for item in self._directory
        }

    def _find_directory(self, query: str) -> list[dict]:
        term = query.strip().casefold()
        if not term:
            return []
        exact = [
            item
            for item in self._directory
            if term in {
                str(item.get("name_cn", "")).strip().casefold(),
                str(item.get("name_en", "")).strip().casefold(),
                str(item.get("name_code", "")).strip().casefold(),
            }
        ]
        if exact:
            return exact
        return [
            item
            for item in self._directory
            if term in str(item.get("name_cn", "")).casefold()
            or term in str(item.get("name_en", "")).casefold()
            or term == str(item.get("name_code", "")).casefold()
        ]

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
                "/妮姬 查询 资料 <角色名>　(/nikke info)"
            ),
            "日常": (
                "【日常】\n"
                "/妮姬 签到　(/nikke daily、/nikke claim)\n"
                "/妮姬 签到 状态 — 只查询、不提交\n"
                "/妮姬 兑换 <CDK>　(/nikke cdk)\n"
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
            "daily": "日常", "push": "日常",
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
        )

    @filter.command("妮姬", alias={"nikke"})
    async def nikke(
        self,
        event: AstrMessageEvent,
        command: str = "",
        arg1: str = "",
        arg2: str = "",
    ):
        """NIKKE 中文精简指令入口。"""
        command_key = command.strip().casefold()
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
        if command_key in {"签到", "daily", "claim"}:
            async for result in self.daily(event, arg1):
                yield result
            return
        if command_key in {"兑换", "cdk"}:
            if not arg1:
                yield event.plain_result("用法：/妮姬 兑换 <CDK>")
                return
            async for result in self.cdk(event, arg1):
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
            "push": (self.push, (event, arg1)),
            "group": (self.group_set, (event, arg1)),
            "schedule": (self.schedule, (event, arg1)),
            "summary": (self.summary, (event, arg1)),
            "run": (self.run, (event,)),
            "health": (self.health, (event,)),
        }
        target = legacy.get(command_key)
        if target:
            handler, args = target
            async for result in handler(*args):
                yield result
            return
        yield event.plain_result("未知指令。发送 /妮姬 帮助 查看可用功能。")

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
        """兼容旧版英文绑定指令。"""
        if not event.is_private_chat() and not bool(self.config.get("allow_group_bind", False)):
            yield event.plain_result("为防止绑定链接被他人抢先使用，请私聊机器人发送 /妮姬 账号 绑定。")
            return
        token = secrets.token_urlsafe(36)
        self.store.create_bind_session(token, self._qq_id(event), 600)
        url = f"{self.public_base_url}/bind/{token}"
        yield event.plain_result(f"安全绑定链接（10分钟、仅可使用一次）：\n{url}\n请勿转发。账号密码只在BlaBlaLink官网输入。")

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
            f"每日汇总：{'开启' if account['push_enabled'] else '关闭'}"
        )

    @staticmethod
    def _profile_rows(account: dict, basic: dict, outpost: dict) -> list[tuple[str, str]]:
        """只使用真实响应已确认存在的字段生成档案行。"""
        rows = [
            ("指挥官", str(basic.get("nickname") or account.get("nickname") or account.get("role_name") or "未知")),
            ("区服", str(account.get("area_id") or "未知")),
            ("同步器", str(outpost.get("synchro_level", 0))),
            ("前哨等级", str(outpost.get("outpost_battle_level", 0))),
            ("普通主线", str(basic.get("progress_normal_campaign", basic.get("progress_campaign_normal", "未知")))),
            ("困难主线", str(basic.get("progress_hard_campaign", basic.get("progress_campaign_hard", "未知")))),
        ]

        optional = (
            ("lv", "指挥官等级"),
            ("team_combat", "部队总战力"),
            ("icon_id", "头像 ID"),
            ("created_at", "注册时间"),
            ("character_count", "持有妮姬"),
            ("character_costume_count", "时装数量"),
            ("progress_tribe_tower", "部落塔进度"),
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
            ("tactic_academy_class", "战术学院班级"),
            ("tactic_academy_lesson", "战术学院课程"),
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
        try:
            account = self._account_or_error(event)
            data = await self.client.get_profile_dashboard(account)
            dashboard = self.profile_builder.build(
                account=account,
                basic=data["basic"],
                outpost=data["outpost"],
                roster=data["roster"],
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            path = await asyncio.to_thread(self.profile_renderer.render_profile, dashboard)
            yield event.image_result(path)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            yield event.plain_result(f"查询失败：{exc}")

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
        yield event.plain_result("用法：/妮姬 查询 练度 [角色名] 或 /妮姬 查询 资料 <角色名>")

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
            logger.warning(f"[NIKKE] roster 查询失败: {type(exc).__name__}: {exc}")
            yield event.plain_result(f"练度查询失败：{exc}")

    async def progress(self, event: AstrMessageEvent):
        """查看同步器、前哨和主线进度。"""
        async for result in self.me(event):
            yield result

    async def character(self, event: AstrMessageEvent, name: str):
        """查询自己指定妮姬的练度。"""
        if not name.strip():
            yield event.plain_result("用法：/妮姬 查询 练度 <角色名>")
            return
        try:
            account = self._account_or_error(event)
            matches = self._find_directory(name)
            if not matches:
                raise ValueError("没有找到该妮姬")
            if len(matches) > 1:
                candidates = "\n".join(
                    f"{index}. {item.get('name_cn') or item.get('name_en') or item.get('name_code')}"
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
            roster = await self.client.get_roster(account, include_details=False)
            held_codes = {str(c.get("name_code", "")) for c in roster}
            if code and code not in held_codes:
                yield event.plain_result(
                    f"你未持有该妮姬：{target.get('name_cn') or target.get('name_en') or code}"
                )
                return
            payload = await self.client.get_character_detail(account, code)
            card = self.character_builder.build(
                account=account,
                directory=target,
                payload=payload,
                fetched_at=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
                plugin_version=PLUGIN_VERSION,
            )
            path = await asyncio.to_thread(self.character_renderer.render_character, card)
            yield event.image_result(path)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            yield event.plain_result(f"查询失败：{exc}")

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
        rows = [
            ("中文 / 英文", f"{item.get('name_cn','')} / {item.get('name_en','')}"),
            ("稀有度", str(item.get("rare") or "未知")),
            ("属性", str(item.get("element") or "未知")),
            ("武器", str(item.get("weapon") or "未知")),
            ("爆裂阶段", str(item.get("burst") or "未知")),
            ("企业", str(item.get("corporation") or "未知")),
        ]
        path = self.renderer.render(item.get("name_cn") or item.get("name_en") or name, "妮姬基础资料", rows)
        yield event.image_result(path)

    async def _run_daily_for_account(self, account: dict, day: str) -> tuple[str, str]:
        qq_id = str(account["qq_id"])
        run_key = f"{day}:{qq_id}:daily"
        if not self.store.claim_run(run_key, qq_id, "daily"):
            return account.get("nickname") or qq_id, "今日已执行"
        try:
            await self.client.get_profile(account)
            if bool(self.config.get("enable_daily_actions", False)):
                signin_key = f"{day}:{qq_id}:signin"
                status = await self.client.get_daily_signin(account)
                if not status["found"]:
                    detail = "登录有效；未找到签到任务"
                elif status["completed"]:
                    detail = "登录有效；今日已经签到"
                elif self.store.claim_run(signin_key, qq_id, "signin"):
                    try:
                        detail = "登录有效；" + await self.client.perform_daily_signin(account)
                        self.store.finish_run(signin_key, "success", detail)
                    except Exception as exc:
                        self.store.finish_run(signin_key, "failed", type(exc).__name__)
                        raise
                else:
                    detail = "登录有效；签到已执行或正在执行"
            else:
                try:
                    status = await self.client.get_daily_signin(account)
                    signin = "已签到" if status["completed"] else "待签到" if status["found"] else "未找到签到任务"
                    detail = f"登录有效；自动签到未启用；当前{signin}"
                except BlaBlaError as exc:
                    detail = f"登录有效；自动签到未启用；{exc}"
            self.store.finish_run(run_key, "success", detail)
            return account.get("nickname") or qq_id, detail
        except CookieExpired:
            self.store.mark_cookie_invalid(qq_id)
            self.store.finish_run(run_key, "expired", "Cookie失效")
            return account.get("nickname") or qq_id, "Cookie失效，请重新绑定"
        except Exception as exc:
            detail = f"失败：{type(exc).__name__}"
            self.store.finish_run(run_key, "failed", detail)
            return account.get("nickname") or qq_id, detail

    async def _run_all_daily(self, day: str, stagger: bool = False) -> list[tuple[str, str]]:
        accounts = self.store.list_accounts(push_only=True, with_cookie=True)
        semaphore = asyncio.Semaphore(max(1, int(self.config.get("max_concurrency", 2))))

        async def run(account):
            if stagger:
                await asyncio.sleep(random.uniform(0, 15 * 60))
            async with semaphore:
                return await self._run_daily_for_account(account, day)

        results = await asyncio.gather(*(run(account) for account in accounts))
        self.store.set_setting(f"daily_results:{day}", results)
        return results

    async def _send_summary(self, day: str) -> None:
        group_umo = self.store.get_setting("summary_group_umo", "")
        if not group_umo:
            logger.warning("[NIKKE] 尚未配置每日汇总群")
            return
        results = self.store.get_setting(f"daily_results:{day}", [])
        if not results:
            results = await self._run_all_daily(day)
        path = self.renderer.render_summary([(str(a), str(b)) for a, b in results])
        await self.context.send_message(group_umo, MessageChain([Image.fromFileSystem(path)]))

    async def _daily_status(self, event: AstrMessageEvent):
        """只读查询当前账号的每日签到状态。"""
        try:
            account = self._account_or_error(event)
            await self.client.get_profile(account)
            status = await self.client.get_daily_signin(account)
            if not status["found"]:
                detail = "未找到签到任务"
            elif status["completed"]:
                detail = "今日已签到"
            else:
                detail = "今日待签到"
            yield event.plain_result(detail)
        except CookieExpired:
            self.store.mark_cookie_invalid(self._qq_id(event))
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            yield event.plain_result(f"查询失败：{exc}")

    async def daily(self, event: AstrMessageEvent, action: str = ""):
        """直接签到，或只读查询签到状态。"""
        action_key = action.strip().casefold()
        if action_key in {"状态", "status"}:
            async for result in self._daily_status(event):
                yield result
            return
        if action_key:
            yield event.plain_result("用法：/妮姬 签到 或 /妮姬 签到 状态")
            return
        if not bool(self.config.get("enable_daily_actions", False)):
            yield event.plain_result("签到写操作当前由管理员关闭；可使用 /妮姬 签到 状态 只读查询。")
            return
        try:
            account = self._account_or_error(event)
            name, detail = await self._run_daily_for_account(account, datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
            yield event.plain_result(f"{name}：{detail}")
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
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", normalized):
            yield event.plain_result("兑换码格式无效：仅支持4至64位字母、数字、下划线或连字符。")
            return
        qq_id = self._qq_id(event)
        masked = self._mask_cdk(normalized)
        try:
            account = self._account_or_error(event)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        run_key = f"cdk:{qq_id}:{digest}"
        retryable = {"failed", "unknown", "expired"}
        existing = self.store.get_run(run_key)
        if existing and existing["status"] not in retryable:
            if existing["status"] == "running":
                if not self.store.retry_run(run_key, retryable, stale_after=120):
                    yield event.plain_result(f"兑换码 {masked} 正在处理，请勿重复提交。")
                    return
            else:
                yield event.plain_result(existing["detail"] or f"兑换码 {masked} 已处理。")
                return
        elif existing:
            if not self.store.retry_run(run_key, retryable, stale_after=120):
                yield event.plain_result(f"兑换码 {masked} 正在处理，请稍后再试。")
                return
        elif not self.store.claim_run(run_key, qq_id, "cdk"):
            yield event.plain_result(f"兑换码 {masked} 正在处理，请勿重复提交。")
            return
        try:
            result = await self.client.redeem_cdk(account, normalized)
            detail = f"兑换码 {masked}：{result.message}"
            self.store.finish_run(run_key, "success" if result.success else ("terminal" if result.terminal else "unknown"), detail)
            yield event.plain_result(detail)
        except CookieExpired:
            self.store.mark_cookie_invalid(qq_id)
            self.store.finish_run(run_key, "expired", "登录状态已失效")
            yield event.plain_result("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except Exception as exc:
            self.store.finish_run(run_key, "failed", f"兑换码 {masked}：请求失败，可稍后重试")
            logger.warning(f"[NIKKE] CDK兑换失败: {type(exc).__name__}")
            yield event.plain_result(f"兑换码 {masked}：请求失败，可稍后重试。")

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
        """管理员查看插件健康状态。"""
        if not self._is_admin(event):
            yield event.plain_result("仅管理员可查看。")
            return
        accounts = self.store.list_accounts(with_cookie=False)
        yield event.plain_result(
            f"NIKKE插件 {PLUGIN_VERSION}\n账号：{len(accounts)}\n目录：{len(self._directory)}\n"
            f"绑定服务：{self.web_host}:{self.web_port}\n"
            f"自动签到：{'启用' if self.config.get('enable_daily_actions', False) else '关闭'}\n"
            f"CDK兑换：{'启用' if self.config.get('enable_cdk_redemption', False) else '关闭'}"
        )

    async def terminate(self):
        self._closing = True
        await self.web.stop()
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        logger.info("[NIKKE] 插件已停止")
