"""帮助教程与发布权限回归。"""

import pytest

from astrbot_plugin_nikke.features.help.catalog import TOPICS
from astrbot_plugin_nikke.features.help.renderer import detail, home
from test_command_routing_contract import Event, _plugin_with_recorders


@pytest.mark.parametrize("topic", [item.name for item in TOPICS if not item.admin])
def test_each_topic_has_commands_and_stays_compact(topic):
    text = detail(topic, include_admin=False)
    assert "/妮姬 " in text
    assert len(text) < 1000
    assert "管理 健康" not in text


def test_index_hides_admin_and_unreleased_arena():
    text = detail("", include_admin=False)
    assert "管理" not in text
    assert "竞技场" not in text
    assert "管理 健康" not in detail("admin", include_admin=False)
    assert "竞技场 解队" not in detail("竞技场", include_admin=True)
    assert "/妮姬 管理 健康" in detail("管理", include_admin=True)


def test_home_is_short_and_has_three_commands():
    text = home("test", include_admin=False)
    assert len(text) < 250
    assert "帮助 详解 入门" in text
    assert "管理" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("command,action,topic", [
    ("帮助", "详解", "日程"), ("help", "detail", "schedule"),
    ("#妮姬", "帮助", "详解 日程"),
])
async def test_detail_routes_without_business_calls(command, action, topic):
    plugin, recorders = _plugin_with_recorders()
    result = [item async for item in plugin.nikke(Event(), command, action, topic)]
    assert "【日程详解】" in result[0][1]
    assert all(not handler.contexts for handler in recorders.values())
