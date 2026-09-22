"""验证 Profile 实际命令入口的双路径合同和单 gateway 责任。"""

import asyncio

from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired
from astrbot_plugin_nikke.main import NikkePlugin


class _Event:
    def get_sender_id(self):
        return "route-user"

    def image_result(self, path):
        return ("image", path)

    def plain_result(self, text):
        return ("plain", text)


class _Store:
    def __init__(self):
        self.invalidated = []

    def get_account(self, qq_id):
        return {"qq_id": qq_id, "cookie": "cookie"}

    def mark_cookie_invalid(self, qq_id):
        self.invalidated.append(qq_id)


class _Client:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def get_profile_dashboard(self, account):
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _LegacyBuilder:
    def __init__(self):
        self.calls = 0

    def build(self, **kwargs):
        self.calls += 1
        return {"route": "legacy"}


class _Application:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def build_dashboard(self, account):
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _Renderer:
    def render_profile(self, dashboard):
        return f"{dashboard['route']}.png"


def _plugin(*, enabled, client_response=None, application_response=None):
    plugin = NikkePlugin.__new__(NikkePlugin)
    plugin.config = {"profile_application_enabled": enabled, "ui_renderer": "pillow"}
    plugin.store = _Store()
    plugin.client = _Client(client_response)
    plugin.profile_builder = _LegacyBuilder()
    plugin.profile_application = _Application(application_response)
    plugin.profile_renderer = _Renderer()
    plugin.feedback_manager = None
    return plugin


def _run_me(plugin):
    async def consume():
        return [item async for item in plugin.me(_Event())]

    return asyncio.run(consume())


def test_disabled_route_uses_legacy_gateway_once():
    plugin = _plugin(
        enabled=False,
        client_response={"basic": {}, "outpost": {}, "roster": []},
        application_response={"route": "new"},
    )

    assert _run_me(plugin) == [("image", "legacy.png")]
    assert plugin.client.calls == 1
    assert plugin.profile_builder.calls == 1
    assert plugin.profile_application.calls == 0


def test_enabled_route_uses_application_gateway_once():
    plugin = _plugin(
        enabled=True,
        client_response=AssertionError("新路由不应直接调用 client"),
        application_response={"route": "new"},
    )

    assert _run_me(plugin) == [("image", "new.png")]
    assert plugin.client.calls == 0
    assert plugin.profile_builder.calls == 0
    assert plugin.profile_application.calls == 1


def test_enabled_route_keeps_cookie_invalidation_at_command_boundary():
    plugin = _plugin(
        enabled=True,
        client_response=AssertionError("新路由不应直接调用 client"),
        application_response=CookieExpired("expired"),
    )

    results = _run_me(plugin)

    assert results == [("plain", "登录状态已失效，请重新发送 /妮姬 账号 绑定。")]
    assert plugin.client.calls == 0
    assert plugin.profile_application.calls == 1
    assert plugin.store.invalidated == ["route-user"]
