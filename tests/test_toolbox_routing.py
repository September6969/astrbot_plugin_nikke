# SPDX-License-Identifier: GPL-3.0-or-later
"""路由别名与新增日程类型的适配器派发验收。"""

from __future__ import annotations

import pytest

from astrbot_plugin_nikke.application.commands.contracts import CommandResult, TextReply
from plugin_fixtures import make_plugin_shell
from test_command_routing_contract import Event


class RecordingHandler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.contexts = []

    async def handle(self, context):
        self.contexts.append(context)
        return CommandResult((TextReply(self.name),))


def plugin_with_recorders():
    plugin = make_plugin_shell()
    toolbox = RecordingHandler("toolbox")
    raid = RecordingHandler("raid")
    plugin.handlers.toolbox = toolbox
    plugin.handlers.raid = raid
    return plugin, toolbox, raid


async def route(plugin, command, arg1="", arg2=""):
    return [item async for item in plugin.nikke(Event(), command, arg1, arg2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,arg1,arg2,expected_feature",
    (
        ("卡池", "", "", "gacha"),
        ("gacha", "皮肤", "", "gacha"),
        ("新闻", "订阅", "新闻", "news"),
        ("咨询", "拉毗", "作战", "counsel"),
        ("同步器", "计算", "200 210 0 0 0 1 1 1", "sync"),
        ("愿望单", "均衡", "", "wishlist"),
        ("洗词条", "攻击力增加", "头部,1,攻击力增加,15", "overload"),
        ("洗词条模拟", "攻击力增加", "头部,1,防御力增加,4", "overload_sim"),
        ("单人突袭", "赛季", "", "soloraid"),
        ("solo_raid", "我的", "", "soloraid"),
        ("uid", "123456789", "", "uid"),
        ("我的妮姬", "资料", "", "uid"),
        ("养成历史", "", "", "growth"),
        ("九宫格", "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号", "", "grid"),
        ("本命榜", "", "", "grid_rank"),
    ),
)
async def test_tool_aliases_dispatch_to_toolbox(
    command, arg1, arg2, expected_feature
) -> None:
    plugin, toolbox, raid = plugin_with_recorders()
    assert await route(plugin, command, arg1, arg2) == [("plain", "toolbox")]
    parameters = dict(toolbox.contexts[-1].parameters)
    assert parameters["feature"] == expected_feature
    assert parameters["action"] == arg1
    assert parameters["value"] == arg2
    assert raid.contexts == []


@pytest.mark.asyncio
async def test_schedule_command_is_extended_with_board_groups() -> None:
    plugin, toolbox, _ = plugin_with_recorders()
    assert await route(plugin, "日程", "卡池") == [("plain", "toolbox")]
    assert dict(toolbox.contexts[-1].parameters) == {
        "feature": "gacha",
        "action": "卡池",
        "value": "",
    }

    # 非类型参数仍走原日程命令，保持既有行为。
    plugin.handlers.calendar = RecordingHandler("calendar")
    assert await route(plugin, "日程", "14", "2") == [("plain", "calendar")]
    assert dict(plugin.handlers.calendar.contexts[-1].parameters) == {
        "horizon": "14",
        "page": "2",
    }


@pytest.mark.asyncio
async def test_union_raid_entry_stays_separate_from_solo_raid() -> None:
    plugin, toolbox, raid = plugin_with_recorders()
    assert await route(plugin, "突袭") == [("plain", "raid")]
    assert toolbox.contexts == []
    assert await route(plugin, "单人突袭") == [("plain", "toolbox")]
    assert dict(toolbox.contexts[-1].parameters)["feature"] == "soloraid"
