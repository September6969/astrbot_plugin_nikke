"""新版帮助分类、历史入口和发布门禁。"""

import pytest

from astrbot_plugin_nikke.application.commands.help import help_category, help_detail, help_home
from astrbot_plugin_nikke.features.help.catalog import CATEGORIES, TOPICS
from test_command_routing_contract import Event, _plugin_with_recorders


def test_new_home_categories_and_legacy_shortcuts():
    text = help_home("test", include_admin=False)
    for group in CATEGORIES:
        assert (group.name + " —" in text) is (group.name not in {"管理", "竞技场"})
    assert "竞技场 —" in help_home("test", include_admin=False, arena=True)
    assert "管理 —" in help_home("test", include_admin=True)
    assert len(text) < 250


def test_every_static_topic_has_navigation():
    covered = {name for group in CATEGORIES for name in group.topics}
    assert {item.name for item in TOPICS} - covered == {"入门"}


@pytest.mark.parametrize("enabled", [False, True])
def test_category_and_detail_share_feature_gates(enabled):
    options = dict(include_admin=False, web_enabled=enabled,
                   community_enabled=enabled, renewal_enabled=enabled)
    account = help_category("账号", "test", arena=enabled, **options)
    welfare = help_category("福利", "test", arena=enabled, **options)
    arena = help_category("竞技场", "test", arena=enabled, **options)
    index = help_detail("", arena_enabled=enabled, **options)
    assert ("账号 自动续期" in account) is enabled
    assert ("日常 任务 执行" in welfare) is enabled
    assert ("竞技场 编辑" in arena) is enabled
    assert ("竞技场 解队" in arena) is enabled
    for name in ("竞技场", "日常任务", "账号续期"):
        assert (name in index) is enabled


def test_arena_without_web_keeps_single_team():
    text = help_category("竞技场", "test", include_admin=False, arena=True)
    assert "竞技场 解队" in text and "竞技场 沙盒" in text
    assert "竞技场 编辑" not in text and "竞技场 三队" not in text


def test_admin_announcement_subscription_does_not_leak():
    assert "公告 订阅" not in help_category("活动", "test", include_admin=False)
    assert "公告 订阅" in help_category("管理", "test", include_admin=True)
    assert "公告 订阅" not in help_detail(
        "公告订阅", include_admin=False, arena_enabled=False, web_enabled=False,
        community_enabled=False, renewal_enabled=False)


def test_legacy_categories():
    assert "/妮姬 塔罗 [单抽|三张|今日|状态|帮助]" in help_category(
        "查询", "test", include_admin=False)
    assert "/妮姬 兑换" in help_category("daily", "test", include_admin=False)
    assert "汇总" in help_category("push", "test", include_admin=False)


@pytest.mark.asyncio
async def test_new_category_routes_without_business_calls():
    plugin, recorders = _plugin_with_recorders()
    result = [item async for item in plugin.nikke(Event(), "帮助", "养成")]
    assert "查询 练度" in result[0][1]
    assert all(not handler.contexts for handler in recorders.values())
