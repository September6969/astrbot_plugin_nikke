"""竞技场离线输入、机械规则与持有过滤回归。"""

from dataclasses import replace
from pathlib import Path
import json

import pytest

from astrbot_plugin_nikke.core.providers.arena import create_arena_application
from astrbot_plugin_nikke.features.arena.burst import burst_chain
from astrbot_plugin_nikke.features.arena.charge import estimate_speed
from astrbot_plugin_nikke.features.arena.models import ArenaTeam, ArenaRosterSnapshot, Provenance
from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver

GOLDEN = json.loads((Path(__file__).parent / "fixtures/arena/burst_golden.json").read_text(encoding="utf-8"))


@pytest.fixture
def arena():
    return create_arena_application(Path(__file__).resolve().parents[1], account_reader=None,
                                    gateway=None, identity=CharacterDirectoryResolver())


@pytest.mark.parametrize("separator", ["/", "／", "、", ",", "，", "\n"])
def test_input_order_and_separators(arena, separator):
    team = arena.directory.parse_team(separator.join(("红莲", "豺狼", "布兰儿", "桑迪", "特蕾娜")))
    assert team.keys == ("scarlet", "jackal", "blanc", "centi", "trina")


@pytest.mark.parametrize("text", ["", "红莲", "红莲////", "/" * 1001,
                                 "红莲/红莲/布兰儿/桑迪/特蕾娜",
                                 "红莲/豺狼/布兰儿/桑迪/未知",
                                 "红莲/豺狼/布兰儿/桑迪/特",
                                 "红莲/豺狼/布兰儿/桑迪/特蕾娜/桑迪"])
def test_reject_invalid_input(arena, text):
    with pytest.raises(ValueError):
        arena.directory.parse_team(text)


def test_base_and_treasure_cannot_share_slot(arena):
    with pytest.raises(ValueError):
        arena.directory.parse_team("桑迪/桑迪 珍藏/红莲/豺狼/布兰儿")


@pytest.mark.parametrize("stages,valid,positions", [
    ((3, 1, 2, 2, 3), True, (2, 3, 1)),
    ((1, 2, 3, 1, 2), True, (1, 2, 3)),
    ((3, 3, 2, 2, 3), False, ()),
    ((1, 3, 3, 3, 1), False, (1,)),
    ((1, 2, 2, 1, 1), False, (1, 2)),
])
def test_first_matching_position_wins(arena, stages, valid, positions):
    base = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    team = ArenaTeam(tuple(replace(char, burst=stage) for char, stage in zip(base.characters, stages)))
    chain = burst_chain(team)
    assert chain.valid is valid
    assert tuple(step.position for step in chain.steps) == positions


def test_reentry_requires_another_b1(arena):
    team = arena.directory.parse_team("蒂亚/桑迪/红莲/布兰儿/特蕾娜")
    assert not burst_chain(team).valid
    team = arena.directory.parse_team("蒂亚/豺狼/红莲/布兰儿/特蕾娜")
    chain = burst_chain(team)
    assert chain.valid
    assert [step.stage for step in chain.steps] == [1, 1, 2, 3]


def test_adaptive_rapi_and_conditional_star(arena):
    team = arena.directory.parse_team("拉毗：小红帽/桑迪/红莲/布兰儿/特蕾娜")
    assert burst_chain(team).steps[0].character_key == "rapi_red_hood"
    team = arena.directory.parse_team("阿妮斯：超级巨星/豺狼/红莲/布兰儿/特蕾娜")
    assert [step.stage for step in burst_chain(team).steps] == [1, 1, 2, 3]


@pytest.mark.parametrize("missing", range(5))
def test_speed_missing_never_becomes_default(arena, missing):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    curves = {char.key: {2: 25} for char in team.characters}
    del curves[team.keys[missing]]
    assert estimate_speed(team, curves, Provenance("test", "1", "verified", ())).tier is None


@pytest.mark.parametrize("value,tier", [(0, None), (19, None), (20, 2), (40, 2)])
def test_static_speed_threshold(arena, value, tier):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    result = estimate_speed(team, {char.key: {2: value} for char in team.characters},
                            Provenance("test", "1", "verified", ()))
    assert result.tier == tier


def test_deterministic_bounded_and_legal_candidates(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    a = arena.analyzer.analyze(team)
    assert a == arena.analyzer.analyze(team)
    assert 1 <= len(a.recommendations) <= 3
    assert a.searched <= 2048
    assert all(item.chain.valid for item in a.recommendations)
    assert len({item.team.keys for item in a.recommendations}) == len(a.recommendations)


def test_owned_filter_never_adds_unknown_or_treasure(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    owned = frozenset(("scarlet", "jackal", "blanc", "centi", "trina", "noah", "biscuit"))
    snapshot = ArenaRosterSnapshot(owned, "available", 0, "", ())
    result = arena.analyzer.analyze(team, snapshot)
    assert result.recommendations
    assert all(set(item.team.keys) <= owned for item in result.recommendations)
    unavailable = replace(snapshot, status="expired")
    assert not arena.analyzer.analyze(team, unavailable).recommendations


@pytest.mark.parametrize("sample", GOLDEN["cases"])
def test_locked_upstream_burst_golden(arena, sample):
    team = ArenaTeam(tuple(arena.directory.characters[key] for key in sample["ids"]))
    chain = burst_chain(team)
    assert chain.valid == sample["valid"]
    assert [[step.position, step.character_key] for step in chain.steps] == sample["steps"]


def test_owned_flexible_slot_uses_labeled_same_stage_substitute(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    keys = team.keys
    # 仅缺一个非核心 B2 槽，已有的桑迪可按同阶段补位。
    arena.analyzer.templates = [{
        "required": [keys[0]], "archetype": "fixture", "reason": "测试模板",
        "slots": [(keys[0],), (keys[1],), (keys[2],), ("noah",), (keys[4],)],
    }]
    roster = ArenaRosterSnapshot(frozenset(keys), "available", 0, "", ())
    recommendation, = arena.analyzer.analyze(team, roster).recommendations
    assert recommendation.team.keys == keys
    assert "替补尚未验证" in recommendation.warnings[0]
    assert "P4" in recommendation.warnings[0]


def test_duplicate_team_keeps_best_matching_template(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    template = {"required": [], "archetype": "fixture",
                "slots": [(key,) for key in team.keys]}
    arena.analyzer.templates = [
        dict(template, priority=5, reason="低分依据"),
        dict(template, priority=25, reason="高分依据"),
    ]
    item, = arena.analyzer.analyze(team).recommendations
    assert item.score == 25
    assert any(evidence.text == "高分依据" for evidence in item.evidence)


def test_three_teams_keep_alternative_with_same_burst_core(arena):
    from types import SimpleNamespace
    from astrbot_plugin_nikke.features.arena.models import Recommendation
    from astrbot_plugin_nikke.features.arena.optimizer import ThreeTeamOptimizer

    characters = list(arena.directory.characters.values())[:15]
    characters = [replace(char, burst=(1, 2, 3, 3, 3)[index % 5],
                          reenter=False, conditional_reenter=False, adaptive_b1=False)
                  for index, char in enumerate(characters)]
    teams = tuple(ArenaTeam(tuple(characters[index:index + 5])) for index in (0, 5, 10))
    conflicting = ArenaTeam(teams[0].characters[:4] + (characters[9],))

    def recommendation(team, score):
        return Recommendation(team, burst_chain(team),
                              estimate_speed(team, {}, arena.analyzer.provenance), score, (), ())

    by_enemy = dict(zip(teams, [
        (recommendation(conflicting, 10), recommendation(teams[0], 5)),
        (recommendation(teams[1], 5),),
        (recommendation(teams[2], 5),),
    ]))
    engine = SimpleNamespace(analyze=lambda team, *_args, **_kwargs:
                             SimpleNamespace(recommendations=by_enemy[team]),
                             with_history=lambda item, _enemy: item)
    result = ThreeTeamOptimizer(engine).solve(teams, budget=1)
    assert tuple(item.team for item in result.teams) == teams
    assert result.searched == 1
