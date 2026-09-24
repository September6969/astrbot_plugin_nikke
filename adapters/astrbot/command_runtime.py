# SPDX-License-Identifier: GPL-3.0-or-later
"""AstrBot 命令路由与历史别名兼容。"""

from __future__ import annotations

from typing import Any

from astrbot.api.event import AstrMessageEvent

from ..._version import PLUGIN_VERSION
from .collections import AstrBotAdapterCollection, PluginCommandHandlers


def normalize_nikke_prefix(text: str) -> str:
    """将 #妮姬 / #nikke 统一预处理规范化为 /妮姬 / /nikke。"""
    stripped = text.strip()
    if stripped.startswith("#妮姬"):
        return "/妮姬" + stripped[len("#妮姬"):]
    if stripped.startswith("#nikke"):
        return "/nikke" + stripped[len("#nikke"):]
    return text


class NikkeCommandRuntime:
    """只保留命令解析、legacy alias 与 AstrBot 结果适配。"""

    def __init__(
        self,
        *,
        adapters: AstrBotAdapterCollection,
        handlers: PluginCommandHandlers,
    ) -> None:
        self._adapters = adapters
        self._handlers = handlers

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        return bool(event.is_admin())

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
            "guide": "查询", "攻略": "查询", "tarot": "查询", "塔罗": "查询",
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

    async def _dispatch(self, event: AstrMessageEvent, handler: Any, **parameters: str):
        async for result in self._adapters.command.dispatch(
            event, handler, **parameters
        ):
            yield result

    async def _account(
        self, event: AstrMessageEvent, operation: str, **parameters: str
    ):
        async for result in self._dispatch(
            event,
            self._handlers.account,
            operation=operation,
            unified_msg_origin=str(getattr(event, "unified_msg_origin", "") or ""),
            **parameters,
        ):
            yield result

    async def nikke(
        self,
        event: AstrMessageEvent,
        command: str = "",
        arg1: str = "",
        arg2: str = "",
    ):
        """按稳定别名表分派中文、英文与旧版平铺命令。"""
        if command.startswith("#"):
            normalized = normalize_nikke_prefix(f"{command} {arg1} {arg2}".strip())
            parts = normalized.lstrip("/").split(maxsplit=3)
            command = parts[1] if len(parts) > 1 else ""
            arg1 = parts[2] if len(parts) > 2 else ""
            arg2 = parts[3] if len(parts) > 3 else ""
        key = command.strip().casefold()

        if key in {"tower", "塔层"}:
            async for result in self._dispatch(
                event, self._handlers.tower, tower=arg1, floor=arg2
            ):
                yield result
            return
        if key in {"voice", "语音"}:
            async for result in self._adapters.voice.voice_settings(event, arg1, arg2):
                yield result
            return
        if key in {"tarot", "塔罗"}:
            async for result in self._dispatch(
                event, self._handlers.tarot, action=arg1, value=arg2
            ):
                yield result
            return
        if key in {"", "帮助", "help"}:
            yield event.plain_result(self._help_text(arg1, self._is_admin(event)))
            return
        if key in {"账号", "account"}:
            async for result in self._account(
                event, "account", action=arg1, value=arg2
            ):
                yield result
            return
        if key in {"我的", "me", "progress"}:
            async for result in self._dispatch(event, self._handlers.profile):
                yield result
            return
        if key in {"查询", "query"}:
            async for result in self.query(event, arg1, arg2):
                yield result
            return
        if key in {"签到", "daily", "claim", "日常", "routine"}:
            async for result in self._dispatch(
                event, self._handlers.daily, action=arg1, value=arg2
            ):
                yield result
            return
        if key in {"兑换", "cdk"}:
            async for result in self._cdk(event, arg1, arg2):
                yield result
            return
        if key in {"战役", "campaign", "关卡", "stage"}:
            async for result in self._dispatch(
                event, self._handlers.campaign, stage=arg1, mode=arg2
            ):
                yield result
            return
        if key in {"日程", "schedule"}:
            if key == "schedule" and ":" in arg1 and self._is_admin(event):
                async for result in self._account(event, "schedule", value=arg1):
                    yield result
            else:
                async for result in self._dispatch(
                    event, self._handlers.calendar, horizon=arg1
                ):
                    yield result
            return
        if key in {"公告", "news", "announcement"}:
            async for result in self._announcement(event, arg1):
                yield result
            return
        if key in {"攻略", "guide", "guides"}:
            async for result in self._dispatch(
                event, self._handlers.guide, category=arg1, page=arg2 or "1"
            ):
                yield result
            return
        if key in {"突袭", "联盟突袭", "raid", "union_raid"}:
            operation = "ranking" if arg1 in {"排名", "ranking"} else (
                "member" if arg1 in {"我的", "my"} else "overview"
            )
            async for result in self._dispatch(
                event, self._handlers.raid, operation=operation
            ):
                yield result
            return
        if key in {"管理", "admin"}:
            async for result in self._dispatch(
                event,
                self._handlers.account,
                operation="admin",
                action=arg1,
                value=arg2,
                unified_msg_origin=str(getattr(event, "unified_msg_origin", "") or ""),
            ):
                yield result
            return
        async for result in self._legacy(event, key, arg1, arg2):
            yield result

    async def query(self, event: AstrMessageEvent, kind: str = "", value: str = ""):
        key = kind.strip().casefold()
        if key in {"练度", "roster", "character"}:
            async for result in self._dispatch(
                event,
                self._handlers.character,
                operation="character" if value else "roster",
                name=value,
            ):
                yield result
            return
        if key in {"资料", "info"}:
            async for result in self._dispatch(
                event, self._handlers.character, operation="info", name=value
            ):
                yield result
            return
        if key in {"战役", "关卡", "campaign", "stage"}:
            async for result in self._dispatch(
                event, self._handlers.campaign, stage=value, mode=""
            ):
                yield result
            return
        if key in {"攻略", "guide"}:
            async for result in self._dispatch(
                event, self._handlers.guide, category=value, page="1"
            ):
                yield result
            return
        if key in {"突袭", "联盟突袭", "raid", "union_raid"}:
            async for result in self._dispatch(
                event, self._handlers.raid, operation="overview"
            ):
                yield result
            return
        yield event.plain_result(
            "用法：/妮姬 查询 练度 [角色名]、/妮姬 查询 资料 <角色名>、"
            "/妮姬 查询 战役 <关卡> 或 /妮姬 攻略"
        )

    async def _cdk(self, event: AstrMessageEvent, action: str, value: str):
        subcommand = action.strip().casefold()
        if subcommand in {"批量", "batch"}:
            if not value:
                yield event.plain_result("用法：/妮姬 兑换 批量 <CDK1> <CDK2> ...")
                return
            parameters = {"operation": "batch", "codes": value}
        elif subcommand in {"可用", "available"}:
            parameters = {"operation": "available"}
        elif subcommand in {"历史", "history"}:
            parameters = {"operation": "history"}
        elif action:
            parameters = {"operation": "single", "code": action}
        else:
            yield event.plain_result(
                "用法：/妮姬 兑换 <CDK> 或 /妮姬 兑换 批量 <CDK...> 或 /妮姬 兑换 可用|历史"
            )
            return
        async for result in self._dispatch(event, self._handlers.cdk, **parameters):
            yield result

    async def _announcement(self, event: AstrMessageEvent, action: str):
        if action in {"订阅", "取消订阅"}:
            operation = "unsubscribe" if action == "取消订阅" else "subscribe"
            target = str(getattr(event, "unified_msg_origin", "") or "")
            parameters = {"operation": operation, "target": target}
        elif action:
            parameters = {"operation": "unsupported"}
        else:
            parameters = {"operation": "view"}
        async for result in self._dispatch(
            event, self._handlers.announcement, **parameters
        ):
            yield result

    async def _legacy(
        self, event: AstrMessageEvent, key: str, arg1: str, arg2: str
    ):
        if key in {"bind", "unbind", "status"}:
            async for result in self._account(event, key):
                yield result
            return
        if key in {"roster", "character", "info"}:
            operation = "roster" if key == "roster" else key
            async for result in self._dispatch(
                event,
                self._handlers.character,
                operation=operation,
                name=arg1,
            ):
                yield result
            return
        if key == "campaign":
            async for result in self._dispatch(
                event, self._handlers.campaign, stage=arg1, mode=arg2
            ):
                yield result
            return
        if key == "raid":
            async for result in self._dispatch(
                event, self._handlers.raid, operation="overview"
            ):
                yield result
            return
        if key == "news":
            async for result in self._dispatch(
                event, self._handlers.announcement, operation="view"
            ):
                yield result
            return
        if key == "guide":
            async for result in self._dispatch(
                event, self._handlers.guide, category=arg1, page="1"
            ):
                yield result
            return
        operations = {
            "push": "push",
            "group": "group_set",
            "summary": "summary",
            "run": "run",
            "health": "health",
        }
        if key in operations:
            parameters = {"state": arg1} if key == "push" else {}
            parameters.update({"value": arg1} if key == "summary" else {})
            parameters.update({"action": arg1} if key == "group" else {})
            async for result in self._account(event, operations[key], **parameters):
                yield result
            return
        yield event.plain_result("未知指令。发送 /妮姬 帮助 查看可用功能。")
