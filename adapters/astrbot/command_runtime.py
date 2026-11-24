# SPDX-License-Identifier: GPL-3.0-or-later
"""AstrBot 命令路由与历史别名兼容。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ..._version import PLUGIN_VERSION
from ...application.commands.help import help_category, help_detail, help_home
from .collections import AstrBotAdapterCollection, PluginCommandHandlers
from .command_parser import normalize_nikke_prefix, parse_nikke_message

__all__ = ["NikkeCommandRuntime", "normalize_nikke_prefix"]

_ANNOUNCEMENT_FILTERS = {
    "语言": "locale", "language": "locale", "locale": "locale",
    "分类": "category", "category": "category",
    "搜索": "query", "search": "query",
}


class NikkeCommandRuntime:
    """只保留命令解析、legacy alias 与 AstrBot 结果适配。"""

    def __init__(
        self,
        *,
        adapters: AstrBotAdapterCollection,
        handlers: PluginCommandHandlers,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self._adapters = adapters
        self._handlers = handlers
        self._config: Mapping[str, Any] = config if config is not None else {}

    @staticmethod
    def _is_admin(event: AstrMessageEvent) -> bool:
        return bool(event.is_admin())

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
        # 宿主按空白切分且只绑定固定个数参数；原始消息可还原多词、换行与空格分隔的尾参。
        parsed = parse_nikke_message(str(getattr(event, "message_str", "") or ""))
        if parsed and parsed.command.casefold() == command.strip().casefold():
            arg1, arg2 = parsed.arg1, parsed.tail
        key = command.strip().casefold()

        if key in {"竞技场", "arena"}:
            if self._handlers.arena is None:
                yield event.plain_result("竞技场功能当前未启用。")
                return
            async for result in self._dispatch(event, self._handlers.arena, action=arg1, value=arg2):
                yield result
            return
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
            include_admin = self._is_admin(event)
            arena_handler = self._handlers.arena
            arena_enabled = bool(arena_handler and arena_handler.enabled)
            web_routes = getattr(arena_handler, "web_routes", None)
            community_enabled = self._writes_enabled() and bool(getattr(self._handlers.daily, "_extra_automation", None))
            renewal_enabled = self._writes_enabled() and bool(getattr(self._handlers.account, "_session_handler", None))
            if arg1.strip().casefold() in {"详解", "detail"}:
                yield event.plain_result(help_detail(
                    arg2, include_admin=include_admin, arena_enabled=arena_enabled,
                    web_enabled=bool(web_routes and web_routes.active()),
                    community_enabled=community_enabled,
                    renewal_enabled=renewal_enabled,
                ))
            elif not arg1.strip():
                yield event.plain_result(help_home(PLUGIN_VERSION, include_admin=include_admin, arena=arena_enabled))
            else:
                yield event.plain_result(help_category(
                    arg1, PLUGIN_VERSION, include_admin=include_admin, arena=arena_enabled,
                    web_enabled=bool(web_routes and web_routes.active()),
                    community_enabled=community_enabled, renewal_enabled=renewal_enabled))
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
                event, self._handlers.daily, action=arg1, value=arg2,
                scope="signin" if key == "签到" else "community"
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
                    event, self._handlers.calendar, horizon=arg1, page=arg2
                ):
                    yield result
            return
        if key in {"公告", "news", "announcement"}:
            async for result in self._announcement(event, arg1, arg2):
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
                "member" if arg1 in {"我的", "my"} else ("overview" if not arg1 else "invalid")
            )
            async for result in self._dispatch(
                event, self._handlers.raid, operation=operation, page=arg2 or "1"
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

    def _writes_enabled(self) -> bool:
        """写操作总开关；关闭时帮助详解不展示依赖写操作的教学主题。"""
        return bool(self._config.get("enable_daily_actions", False))

    async def _announcement(self, event: AstrMessageEvent, action: str, value: str = ""):
        key = action.strip().casefold()
        parameters: dict[str, str]
        if action in {"订阅", "取消订阅"}:
            operation = "unsubscribe" if action == "取消订阅" else "subscribe"
            target = str(getattr(event, "unified_msg_origin", "") or "")
            parameters = {"operation": operation, "target": target}
        elif key in _ANNOUNCEMENT_FILTERS:
            parameters = {"operation": "view", _ANNOUNCEMENT_FILTERS[key]: value.strip()}
        elif key in {"诊断", "diagnostic", "diagnostics"}:
            parameters = {"operation": "diagnostic"}
        elif key in {"深度刷新", "rescan", "deep_rescan"}:
            parameters = {"operation": "deep_rescan", "locale": value.strip() or "en"}
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
            name = " ".join(part for part in (arg1.strip(), arg2.strip()) if part)
            async for result in self._dispatch(
                event,
                self._handlers.character,
                operation=operation,
                name=name,
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
