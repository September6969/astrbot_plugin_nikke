# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 机器人短入口：私聊链接、群聊拒绝、只读状态。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.application.commands.toolbox import ToolboxCommandHandler
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event


class PrivateEvent(Event):
    def is_private_chat(self) -> bool:
        return True


class FakeWeb:
    def __init__(self) -> None:
        self.actors: list[str] = []

    def create_link(self, actor_id: str) -> str:
        self.actors.append(actor_id)
        return f"https://example.test/shiftypad/{'a' * 40}"


class FakeReadonly:
    def __init__(self, bound: bool = False) -> None:
        self.bound = bound

    def status(self, _actor: str):
        if not self.bound:
            return {"status": "unbound", "can_sync": False}
        return {
            "status": "stale",
            "binding": {
                "nickname": "公开昵称",
                "identity": {"uid": "123456789", "server": "na"},
                "last_sync_at": "2026-11-23T00:00:00+00:00",
            },
            "last_error": "PRIVATE: 公开开关已关闭",
        }


async def route(plugin, event, command, arg1="", arg2=""):
    results = [item async for item in plugin.nikke(event, command, arg1, arg2)]
    return results[0][1]


def plugin_with_shiftypad(bound: bool = False):
    plugin = make_plugin_shell()
    plugin.config = {}
    web = FakeWeb()
    plugin.handlers.toolbox = ToolboxCommandHandler(
        SimpleNamespace(shiftypad_web=web, shiftypad_readonly=FakeReadonly(bound))
    )
    return plugin, web


@pytest.mark.asyncio
async def test_link_is_private_only_and_targets_current_actor() -> None:
    plugin, web = plugin_with_shiftypad()
    text = await route(plugin, PrivateEvent(), "我的妮姬", "导入")
    assert "10 分钟内有效" in text
    assert "https://example.test/shiftypad/" in text
    assert "只读" in text
    assert "数字 UID 不能直接查询所有账号" in text
    assert web.actors == ["synthetic-user"]

    group_text = await route(plugin, Event(), "我的妮姬", "导入")
    assert "私聊" in group_text
    assert web.actors == ["synthetic-user"]


@pytest.mark.asyncio
async def test_readonly_status_distinguishes_unbound_and_stale() -> None:
    plugin, _ = plugin_with_shiftypad(False)
    text = await route(plugin, Event(), "我的妮姬", "只读")
    assert "尚未建立" in text

    plugin, _ = plugin_with_shiftypad(True)
    text = await route(plugin, Event(), "我的妮姬", "只读")
    assert "公开昵称" in text
    assert "stale" in text
    assert "公开开关已关闭" in text
