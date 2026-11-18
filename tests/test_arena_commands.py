"""竞技场真实路由的模拟消息验收，包含私聊隔离及图片回退。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from astrbot.core.star.filter.command import CommandFilter

from astrbot_plugin_nikke.application.commands.arena import ArenaCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.features.arena.models import ArenaRosterSnapshot
from astrbot_plugin_nikke.features.arena.optimizer import ThreeTeamOptimizer
from astrbot_plugin_nikke.features.arena.roster import ArenaRosterProvider
from test_arena_core import arena
from astrbot_plugin_nikke.main import NikkePlugin
from test_command_routing_contract import Event, _plugin_with_recorders

ENEMY = "红莲/豺狼/布兰儿/桑迪/特蕾娜"


@pytest.mark.asyncio
async def test_group_public_never_reads_personal_roster(arena):
    async def fail(_actor):
        raise AssertionError("群聊不应读取私人名单")
    arena.roster = SimpleNamespace(owned=fail)
    handler = ArenaCommandHandler(arena, enabled=True)
    reply = await handler.handle(CommandContext(actor_id="a", parameters={"action": "解队", "value": ENEMY}))
    assert "全角色沙盒" in reply.messages[0].text
    assert reply.messages[0].text.count("建议 ") == 3


@pytest.mark.asyncio
async def test_private_uses_exact_owned_and_image_failure_reuses_result(arena):
    owned = frozenset(("scarlet", "jackal", "blanc", "centi", "trina", "noah", "biscuit"))
    calls = []
    async def roster(actor):
        calls.append(actor)
        return ArenaRosterSnapshot(owned, "available", 0, "", ())
    async def render(_page, _result):
        raise RuntimeError("synthetic-image-failure")
    arena.roster = SimpleNamespace(owned=roster)
    handler = ArenaCommandHandler(arena, enabled=True, render=render)
    reply = await handler.handle(CommandContext(actor_id="a", is_private_chat=True,
                                               parameters={"action": "解队", "value": ENEMY}))
    assert "竞技场解队" in reply.messages[0].text
    assert calls == ["a"]
    status = await handler.handle(CommandContext(parameters={"action": "数据状态"}))
    assert "图片输出 最近一次回退文本" in status.messages[0].text
    assert f"规则快照日期 {arena.analyzer.snapshot_date}" in status.messages[0].text
    assert "synthetic-image-failure" not in status.messages[0].text


@pytest.mark.asyncio
async def test_unbound_does_not_silently_become_owned_or_sandbox(arena):
    async def roster(_actor):
        return ArenaRosterSnapshot(frozenset(), "unbound", 0, "", ())
    arena.roster = SimpleNamespace(owned=roster)
    handler = ArenaCommandHandler(arena, enabled=True)
    context = CommandContext(actor_id="a", is_private_chat=True, parameters={"action": "解队", "value": ENEMY})
    result = await handler.handle(context)
    assert "个人角色库暂不可读取" in result.messages[0].text
    assert "建议 1" not in result.messages[0].text


@pytest.mark.asyncio
async def test_roster_port_is_lightweight_and_maps_only_codes(arena):
    calls = []
    async def get_roster(account, include_details=True):
        calls.append(include_details)
        return [{"name_code": arena.directory.characters["scarlet"].name_code},
                {"name_code": "unknown", "name": "红莲"}, {"bad": True}]
    provider = ArenaRosterProvider(SimpleNamespace(get_account=lambda actor: {"cookie_valid": True}),
                                   SimpleNamespace(get_roster=get_roster), arena.directory)
    snapshot = await provider.owned("a")
    assert calls == [False]
    assert snapshot.keys == frozenset({"scarlet"})
    assert snapshot.unmapped == 2
    assert snapshot.status == "partial"


@pytest.mark.asyncio
async def test_cancellation_propagates(arena):
    async def roster(actor):
        raise asyncio.CancelledError
    arena.roster = SimpleNamespace(owned=roster)
    with pytest.raises(asyncio.CancelledError):
        await arena.analyze(ENEMY, actor_id="a", owned=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["编辑", "三队", "结果", "我的"])
async def test_private_actions_are_guarded_in_groups(arena, action):
    handler = ArenaCommandHandler(arena, enabled=True)
    result = await handler.handle(CommandContext(actor_id="a", parameters={"action": action}))
    assert "私聊" in result.messages[0].text


@pytest.mark.asyncio
async def test_raw_message_preserves_full_english_names(arena):
    plugin, _ = _plugin_with_recorders()
    plugin.handlers.arena = ArenaCommandHandler(arena, enabled=True)
    event = Event()
    event.message_str = "/妮姬 竞技场 解队 Scarlet / Jackal / Blanc / Centi / Trina"
    results = [item async for item in plugin.nikke(event, "竞技场", "解队", "Scarlet")]
    assert "竞技场解队" in results[0][1]
    assert "红莲/豺狼/布兰儿/桑迪/特蕾娜" in results[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(("message", "expected"), [
    ("妮姬　竞技场　解队　Scarlet ／ Jackal ／ Blanc ／ Centi ／ Trina", "竞技场解队"),
    ("nikke arena solve 红莲／豺狼／布兰儿／桑迪／特蕾娜", "竞技场解队"),
    ("妮姬 竞技场 三队导入\n" + ENEMY + "\n"
     "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂\n阿妮斯/拉毗/尼恩/露菲/哈兰", "第 3 场对位"),
])
async def test_astrbot_filter_delivers_complete_arena_payload(arena, message, expected):
    class FilterEvent(Event):
        is_at_or_wake_command = True

        def get_message_str(self):
            return self.message_str

        def set_extra(self, key, value):
            assert key == "parsed_params"
            self.params = value

    plugin, _ = _plugin_with_recorders()
    plugin.handlers.arena = ArenaCommandHandler(arena, enabled=True)
    event = FilterEvent()
    # 唤醒阶段已去除 / 或 #，但保留原阵容内的空格和换行。
    event.message_str = message
    command_filter = CommandFilter("妮姬", alias={"nikke"}, handler_md=SimpleNamespace(handler=NikkePlugin.nikke))
    assert command_filter.filter(event, None)
    replies = [item async for item in plugin.nikke(event, **event.params)]
    assert expected in replies[0][1]


@pytest.mark.parametrize("objective", ["two", "balanced", "speed"])
def test_three_team_output_unique_and_budgeted(arena, objective):
    groups = [
        ENEMY,
        "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂",
        "阿妮斯/拉毗/尼恩/露菲/哈兰",
    ]
    teams = tuple(arena.directory.parse_team(group) for group in groups)
    result = ThreeTeamOptimizer(arena.analyzer).solve(teams, objective=objective, budget=5000)
    assert result.searched <= 5000
    if result.teams:
        keys = [char.base_key or char.key for item in result.teams for char in item.team.characters]
        assert len(set(keys)) == 15
        assert all(item.chain.valid for item in result.teams)
    else:
        assert any("未找到" in warning for warning in result.warnings)


def test_three_team_rejects_shared_base(arena):
    team = arena.directory.parse_team(ENEMY)
    with pytest.raises(ValueError):
        ThreeTeamOptimizer(arena.analyzer).solve((team, team, team))
