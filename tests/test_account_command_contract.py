# SPDX-License-Identifier: GPL-3.0-or-later
"""账号与管理命令边界的行为及路由合同。"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase

from astrbot_plugin_nikke.application.commands.account import (
    AccountCommandHandler,
    RuntimeHealthDetails,
)
from astrbot_plugin_nikke.features.account.application import AccountApplication
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    ImageReply,
    TextReply,
)


class FakeStore:
    def __init__(self) -> None:
        self.bind_sessions: list[tuple[str, str, int]] = []
        self.accounts: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[Any, ...]] = []

    def create_bind_session(self, token: str, qq_id: str, ttl: int = 600) -> None:
        self.bind_sessions.append((token, qq_id, ttl))

    def get_account(self, qq_id: str, with_cookie: bool = True):
        self.writes.append(("get_account", qq_id, with_cookie))
        return self.accounts.get(qq_id)

    def delete_account(self, qq_id: str) -> bool:
        self.writes.append(("delete_account", qq_id))
        return self.accounts.pop(qq_id, None) is not None

    def set_push(self, qq_id: str, enabled: bool) -> bool:
        self.writes.append(("set_push", qq_id, enabled))
        return qq_id in self.accounts

    def set_setting(self, key: str, value: Any) -> None:
        self.writes.append(("set_setting", key, value))

    def list_accounts(self, with_cookie: bool = True):
        self.writes.append(("list_accounts", with_cookie))
        return list(self.accounts.values())


def context(
    *,
    actor_id: str = "12345678",
    admin: bool = False,
    private: bool = True,
    **parameters: str,
) -> CommandContext:
    return CommandContext(
        actor_id=actor_id,
        is_admin=admin,
        is_private_chat=private,
        parameters=parameters,
    )


class AccountCommandContractTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.application = AccountApplication(
            self.store, token_factory=lambda _: "T" * 40
        )
        self.health = RuntimeHealthDetails(
            plugin_version="0.9.test",
            directory_count=7,
            web_host="127.0.0.1",
            web_port=6210,
            daily_actions_enabled=False,
            cdk_redemption_enabled=False,
            diagnostics="状态：正常",
        )
        self.run_calls = 0

        async def render_summary() -> str:
            self.run_calls += 1
            return "summary.png"

        self.handler = AccountCommandHandler(
            application=self.application,
            public_base_url="https://bot.example.com/",
            allow_group_bind=False,
            runtime_health=lambda: self.health,
            render_manual_summary=render_summary,
        )

    async def test_private_bind_keeps_ten_minute_one_time_session_contract(self) -> None:
        result = await self.handler.handle(
            context(operation="bind", actor_id="qq-owner", private=True)
        )

        self.assertEqual(self.store.bind_sessions, [("T" * 40, "qq-owner", 600)])
        self.assertIn("https://bot.example.com/bind/" + "T" * 40, result.messages[0].text)
        self.assertIn("仅可使用一次", result.messages[0].text)

    async def test_group_bind_is_rejected_before_creating_a_session(self) -> None:
        result = await self.handler.handle(
            context(operation="bind", private=False)
        )

        self.assertEqual(
            result.messages,
            (TextReply("为防止绑定链接被他人抢先使用，请私聊机器人发送 /妮姬 账号 绑定。"),),
        )
        self.assertEqual(self.store.bind_sessions, [])

    async def test_explicit_group_bind_configuration_preserves_group_flow(self) -> None:
        handler = AccountCommandHandler(
            application=self.application,
            public_base_url="https://bot.example.com",
            allow_group_bind=True,
            runtime_health=lambda: self.health,
            render_manual_summary=self.handler._render_manual_summary,
        )

        result = await handler.handle(
            context(operation="bind", actor_id="group-owner", private=False)
        )

        self.assertIn("/bind/" + "T" * 40, result.messages[0].text)
        self.assertEqual(self.store.bind_sessions, [("T" * 40, "group-owner", 600)])

    async def test_status_reads_only_non_secret_account_fields(self) -> None:
        self.store.accounts["qq-owner"] = {
            "nickname": "妮姬昵称",
            "role_name": "指挥官",
            "area_id": "3",
            "cookie_valid": 1,
            "push_enabled": 1,
            "auto_daily_enabled": 0,
        }

        result = await self.handler.handle(context(operation="status", actor_id="qq-owner"))

        self.assertIn("已绑定：妮姬昵称", result.messages[0].text)
        self.assertIn("每日汇总：开启", result.messages[0].text)
        self.assertIn(("get_account", "qq-owner", False), self.store.writes)

    async def test_unbind_and_push_keep_bound_account_feedback(self) -> None:
        removed = await self.handler.handle(context(operation="unbind"))
        missing = await self.handler.handle(context(operation="push", state="开"))

        self.assertEqual(removed.messages, (TextReply("当前QQ尚未绑定。"),))
        self.assertEqual(missing.messages, (TextReply("请先绑定账号。"),))
        self.assertEqual(
            self.store.writes[-1], ("set_push", "12345678", True)
        )

    async def test_admin_gate_blocks_all_admin_effects(self) -> None:
        result = await self.handler.handle(
            context(operation="admin", action="执行", unified_msg_origin="group:1")
        )

        self.assertEqual(result.messages, (TextReply("仅管理员可使用管理指令。"),))
        self.assertEqual(self.run_calls, 0)
        self.assertEqual(self.store.writes, [])

    async def test_direct_admin_aliases_keep_operation_specific_permissions(self) -> None:
        cases = (
            ("group_set", {"action": "set"}, "仅管理员可配置汇总群。"),
            ("schedule", {"value": "07:05"}, "仅管理员可修改时间。"),
            ("summary", {"value": "07:05"}, "仅管理员可修改时间。"),
            ("run", {}, "仅管理员可执行全量任务。"),
            ("health", {}, "仅管理员可查看。"),
        )
        for operation, parameters, expected in cases:
            with self.subTest(operation=operation):
                result = await self.handler.handle(
                    context(operation=operation, **parameters)
                )
                self.assertEqual(result.messages, (TextReply(expected),))
        self.assertEqual(self.store.writes, [])
        self.assertEqual(self.run_calls, 0)

    async def test_push_rejects_unknown_values_without_storage_write(self) -> None:
        result = await self.handler.handle(
            context(operation="push", state="maybe")
        )

        self.assertEqual(
            result.messages, (TextReply("用法：/妮姬 账号 汇总 开|关"),)
        )
        self.assertEqual(self.store.writes, [])

    async def test_admin_group_and_schedule_updates_keep_validation(self) -> None:
        group = await self.handler.handle(
            context(
                operation="admin",
                action="设群",
                admin=True,
                unified_msg_origin="group:example",
            )
        )
        valid = await self.handler.handle(
            context(operation="admin", action="任务时间", value="07:05", admin=True)
        )
        invalid = await self.handler.handle(
            context(operation="schedule", value="24:00", admin=True)
        )

        self.assertIn("group:example", group.messages[0].text)
        self.assertIn(("set_setting", "summary_group_umo", "group:example"), self.store.writes)
        self.assertEqual(valid.messages, (TextReply("每日任务时间已设为 07:05。"),))
        self.assertEqual(
            self.store.writes[-2:],
            [("set_setting", "daily_hour", 7), ("set_setting", "daily_minute", 5)],
        )
        self.assertEqual(
            invalid.messages, (TextReply("用法：/妮姬 管理 任务时间 HH:MM"),)
        )

    async def test_run_returns_image_only_after_admin_authorization(self) -> None:
        result = await self.handler.handle(context(operation="run", admin=True))

        self.assertEqual(result.messages, (ImageReply("summary.png"),))
        self.assertEqual(self.run_calls, 1)

    async def test_health_uses_non_cookie_account_listing_and_runtime_snapshot(self) -> None:
        self.store.accounts["one"] = {"qq_id": "one"}

        result = await self.handler.handle(context(operation="health", admin=True))

        self.assertIn("账号：1", result.messages[0].text)
        self.assertIn("127.0.0.1:6210", result.messages[0].text)
        self.assertIn("状态：正常", result.messages[0].text)
        self.assertIn(("list_accounts", False), self.store.writes)


class MainAccountCommandDelegationTests(IsolatedAsyncioTestCase):
    async def test_legacy_command_methods_only_dispatch_to_account_handler(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        source = inspect.getsource(NikkePlugin)
        tree = ast.parse(source)
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        expected = {
            "account", "bind", "unbind", "status", "push", "admin",
            "group_set", "schedule", "summary", "run", "health",
        }

        for name in expected:
            method = methods[name]
            attrs = [node.attr for node in ast.walk(method) if isinstance(node, ast.Attribute)]
            self.assertNotIn("store", attrs, f"{name} 仍直接访问存储")
            self.assertIn("_dispatch_account_command", attrs, f"{name} 未委派账号命令 handler")

        plugin = NikkePlugin.__new__(NikkePlugin)
        calls: list[dict[str, str]] = []

        class Adapter:
            async def dispatch(self, event, handler, **parameters):
                calls.append(parameters)
                yield "delegated"

        plugin.command_adapter = Adapter()
        plugin.account_command_handler = object()
        event = SimpleNamespace(unified_msg_origin="group:example")
        result = [item async for item in plugin.account(event, "绑定", "")]

        self.assertEqual(result, ["delegated"])
        self.assertEqual(
            calls,
            [{
                "operation": "account",
                "action": "绑定",
                "value": "",
                "state": "",
                "unified_msg_origin": "group:example",
            }],
        )
