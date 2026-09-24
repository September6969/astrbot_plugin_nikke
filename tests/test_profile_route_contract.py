"""验证 Profile 命令已收敛到正式 handler 的唯一 application 路径。"""

from __future__ import annotations
from plugin_fixtures import make_plugin_shell

import ast
import asyncio
import json
from pathlib import Path

from astrbot_plugin_nikke.adapters.astrbot.command_adapter import AstrBotCommandAdapter
from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired
from astrbot_plugin_nikke.main import NikkePlugin


ROOT = Path(__file__).resolve().parents[1]


class _Event:
    def get_platform_name(self):
        return "synthetic-platform"

    def get_sender_id(self):
        return "route-user"

    def is_admin(self):
        return False

    def is_private_chat(self):
        return True

    def image_result(self, path):
        return ("image", path)

    def plain_result(self, text):
        return ("plain", text)


class _Store:
    def __init__(self, account=None):
        self.account = account or {"qq_id": "route-user", "cookie": "cookie"}
        self.invalidated = []
        self.lookup_ids = []

    def get_account(self, qq_id):
        self.lookup_ids.append(qq_id)
        return self.account

    def mark_cookie_invalid(self, qq_id):
        self.invalidated.append(qq_id)


class _Application:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def build_dashboard(self, account):
        self.calls.append(account)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _Renderer:
    def render_profile(self, dashboard):
        return "profile.png"


def _plugin(*, account=None, application_response=None):
    plugin = make_plugin_shell()
    plugin.services.store = _Store(account)
    plugin.services.profile_application = _Application(application_response)
    plugin.services.profile_renderer = _Renderer()
    plugin.services.feedback_manager = None
    plugin.adapters.command = AstrBotCommandAdapter()

    async def no_t2i(page, dashboard):
        assert page == "profile"
        return None

    plugin.presentation.try_t2i = no_t2i
    plugin.handlers.profile = ProfileCommandHandler(
        account_reader=plugin.services.store,
        application=plugin.services.profile_application,
        present=plugin.presentation.render_profile,
        invalidate_cookie=plugin.services.store.mark_cookie_invalid,
    )
    return plugin


def _run_me(plugin):
    async def consume():
        return [item async for item in plugin.me(_Event())]

    return asyncio.run(consume())


def test_profile_route_uses_one_application_path_and_preserves_image_reply():
    plugin = _plugin(application_response=object())

    assert _run_me(plugin) == [("image", "profile.png")]
    assert plugin.services.profile_application.calls == [plugin.services.store.account]
    assert plugin.services.store.lookup_ids == ["route-user"]
    assert not hasattr(plugin, "profile_builder")


def test_unbound_profile_does_not_call_application():
    plugin = _plugin(account=None, application_response=AssertionError("must not run"))
    plugin.services.store.account = None

    result = _run_me(plugin)

    assert result == [("plain", "查询失败：尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")]
    assert plugin.services.profile_application.calls == []
    assert plugin.services.store.invalidated == []


def test_cookie_invalidation_has_one_owner_at_command_boundary():
    plugin = _plugin(application_response=CookieExpired("expired"))

    result = _run_me(plugin)

    assert result == [("plain", "登录状态已失效，请重新发送 /妮姬 账号 绑定。")]
    assert len(plugin.services.profile_application.calls) == 1
    assert plugin.services.store.invalidated == ["route-user"]


def test_main_has_no_profile_builder_branch_or_field_assembly():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    plugin = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
    )
    methods = {node.name for node in plugin.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert "_profile_rows" not in methods
    assert "_build_profile_dashboard" not in methods
    assert "profile_builder" not in source
    assert "profile_application_enabled" not in source
    assert "profile_application_enabled" not in json.loads(
        (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
    )
