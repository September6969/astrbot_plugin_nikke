# SPDX-License-Identifier: GPL-3.0-or-later
"""统一验证中文、英文、哈希前缀与历史平铺命令的路由合同。"""

from __future__ import annotations

import pytest

from astrbot_plugin_nikke.application.commands.contracts import (
    CommandResult,
    TextReply,
)
from astrbot_plugin_nikke.main import NikkePlugin
from plugin_fixtures import make_plugin_shell


class Event:
    unified_msg_origin = "group:synthetic"

    def get_platform_name(self) -> str:
        return "synthetic-platform"

    def get_sender_id(self) -> str:
        return "synthetic-user"

    def is_admin(self) -> bool:
        return True

    def is_private_chat(self) -> bool:
        return False

    def plain_result(self, text: str):
        return ("plain", text)

    def image_result(self, path: str):
        return ("image", path)


class RecordingHandler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.contexts = []

    async def handle(self, context):
        self.contexts.append(context)
        return CommandResult((TextReply(self.name),))


class VoiceAdapter:
    async def voice_settings(self, event, action: str, value: str):
        yield event.plain_result(f"voice:{action}:{value}")


def _plugin_with_recorders():
    plugin = make_plugin_shell()
    names = (
        "account",
        "announcement",
        "cdk",
        "calendar",
        "campaign",
        "character",
        "daily",
        "guide",
        "profile",
        "raid",
        "tarot",
        "tower",
    )
    recorders = {name: RecordingHandler(name) for name in names}
    for name, handler in recorders.items():
        setattr(plugin.handlers, name, handler)
    plugin.adapters.voice = VoiceAdapter()
    return plugin, recorders


async def _route(plugin: NikkePlugin, command: str, arg1: str = "", arg2: str = ""):
    return [
        result async for result in plugin.nikke(Event(), command, arg1, arg2)
    ]


@pytest.mark.asyncio
async def test_chinese_command_routes_keep_use_case_parameters() -> None:
    cases = (
        ("我的", "", "", "profile", {}),
        ("查询", "练度", "", "character", {"operation": "roster", "name": ""}),
        ("查询", "练度", "拉毗", "character", {"operation": "character", "name": "拉毗"}),
        ("查询", "资料", "爱丽丝", "character", {"operation": "info", "name": "爱丽丝"}),
        ("战役", "", "", "campaign", {"stage": "", "mode": ""}),
        ("战役", "46-40", "困难", "campaign", {"stage": "46-40", "mode": "困难"}),
        ("联盟突袭", "", "", "raid", {"operation": "overview"}),
        ("联盟突袭", "排名", "", "raid", {"operation": "ranking"}),
        ("联盟突袭", "我的", "", "raid", {"operation": "member"}),
        ("塔层", "无限塔", "50", "tower", {"tower": "无限塔", "floor": "50"}),
        ("攻略", "练度", "2", "guide", {"category": "练度", "page": "2"}),
        ("攻略", "", "", "guide", {"category": "", "page": "1"}),
        ("塔罗", "状态", "", "tarot", {"action": "状态", "value": ""}),
        ("签到", "", "", "daily", {"action": "", "value": ""}),
        ("日常", "自动", "开", "daily", {"action": "自动", "value": "开"}),
        ("兑换", "CODE-1", "", "cdk", {"operation": "single", "code": "CODE-1"}),
        ("日程", "7", "", "calendar", {"horizon": "7"}),
        ("公告", "", "", "announcement", {"operation": "view"}),
        ("管理", "健康", "", "account", {"operation": "admin", "action": "健康", "value": "", "unified_msg_origin": "group:synthetic"}),
        ("账号", "绑定", "", "account", {"operation": "account", "action": "绑定", "value": "", "unified_msg_origin": "group:synthetic"}),
    )

    for command, arg1, arg2, expected_handler, expected_parameters in cases:
        plugin, recorders = _plugin_with_recorders()
        assert await _route(plugin, command, arg1, arg2) == [
            ("plain", expected_handler)
        ], command
        context = recorders[expected_handler].contexts[-1]
        assert dict(context.parameters) == expected_parameters, command
        assert context.conversation_id == Event.unified_msg_origin


@pytest.mark.asyncio
async def test_english_and_hash_prefix_routes_are_preserved() -> None:
    routes = (
        ("me", "", "", "profile", {}),
        ("raid", "", "", "raid", {"operation": "overview"}),
        ("character", "Rapi", "", "character", {"operation": "character", "name": "Rapi"}),
        ("schedule", "7", "", "calendar", {"horizon": "7"}),
        ("#妮姬", "我的", "", "profile", {}),
        ("#nikke", "character", "Rapi", "character", {"operation": "character", "name": "Rapi"}),
        ("#妮姬", "查询", "练度 拉毗", "character", {"operation": "character", "name": "拉毗"}),
    )
    for command, arg1, arg2, expected_handler, expected_parameters in routes:
        plugin, recorders = _plugin_with_recorders()
        assert await _route(plugin, command, arg1, arg2) == [
            ("plain", expected_handler)
        ], (command, arg1, arg2)
        assert dict(recorders[expected_handler].contexts[-1].parameters) == expected_parameters

    plugin, _ = _plugin_with_recorders()
    assert await _route(plugin, "voice", "开", "日语") == [
        ("plain", "voice:开:日语")
    ]


@pytest.mark.asyncio
async def test_all_legacy_flat_aliases_remain_routed() -> None:
    cases = (
        ("bind", "", "", "account", {"operation": "bind"}),
        ("unbind", "", "", "account", {"operation": "unbind"}),
        ("status", "", "", "account", {"operation": "status"}),
        ("roster", "", "", "character", {"operation": "roster", "name": ""}),
        ("character", "Rapi", "", "character", {"operation": "character", "name": "Rapi"}),
        ("info", "Rapi", "", "character", {"operation": "info", "name": "Rapi"}),
        ("campaign", "46-40", "hard", "campaign", {"stage": "46-40", "mode": "hard"}),
        ("raid", "", "", "raid", {"operation": "overview"}),
        ("news", "", "", "announcement", {"operation": "view"}),
        ("guide", "progression", "", "guide", {"category": "progression", "page": "1"}),
        ("push", "on", "", "account", {"operation": "push", "state": "on"}),
        ("group", "set", "", "account", {"operation": "group_set", "action": "set"}),
        ("schedule", "7", "", "calendar", {"horizon": "7"}),
        ("summary", "08:30", "", "account", {"operation": "summary", "value": "08:30"}),
        ("run", "", "", "account", {"operation": "run"}),
        ("health", "", "", "account", {"operation": "health"}),
        ("tarot", "status", "", "tarot", {"action": "status", "value": ""}),
    )
    for command, arg1, arg2, expected_handler, expected_parameters in cases:
        plugin, recorders = _plugin_with_recorders()
        assert await _route(plugin, command, arg1, arg2) == [
            ("plain", expected_handler)
        ], command
        context = recorders[expected_handler].contexts[-1]
        parameters = dict(context.parameters)
        for key, value in expected_parameters.items():
            assert parameters[key] == value, (command, key, parameters)


def test_broad_class_level_forwarders_are_absent() -> None:
    from astrbot_plugin_nikke.adapters.astrbot.command_runtime import NikkeCommandRuntime

    assert "__getattr__" not in NikkePlugin.__dict__
    assert "__getattr__" not in NikkeCommandRuntime.__dict__
