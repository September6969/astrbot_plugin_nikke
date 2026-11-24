# SPDX-License-Identifier: GPL-3.0-or-later
"""14 超限洗词条助手：锁定保护、非法词条与可复现模拟。"""

from __future__ import annotations

import pytest

from astrbot_plugin_nikke.features.overload_advice.advisor import (
    KNOWN_LABELS,
    OverloadAdviceError,
    OverloadOption,
    advise,
    parse_options,
    parse_targets,
    render_advice,
    simulate,
)


def options() -> tuple[OverloadOption, ...]:
    return parse_options(
        (
            {"slot": "head", "position": 1, "label": "攻击力增加", "tier": 15, "locked": True},
            {"slot": "head", "position": 2, "label": "防御力增加", "tier": 4},
            {"slot": "torso", "position": 1, "label": "暴擊傷害增加", "tier": 9},
        )
    )


def test_advice_keeps_targets_and_marks_lock_choices() -> None:
    advice = advise(options(), parse_targets("攻击力增加,暴击伤害增加"))
    by_key = {(item.option.slot, item.option.position): item for item in advice.options}

    assert by_key[("head", 1)].action == "保留"
    assert by_key[("head", 1)].lock is True
    assert by_key[("torso", 1)].action == "保留"
    assert by_key[("head", 2)].action == "重洗"
    assert by_key[("head", 2)].lock is False
    assert advice.probability is None
    assert "官方未提供可核验的洗词条概率" in render_advice(advice)


def test_full_tier_non_target_still_needs_reroll_for_target() -> None:
    advice = advise(options(), ("攻击力增加",))
    max_tier = next(item for item in advice.options if item.option.label == "防御力增加")
    assert max_tier.option.tier == 4  # 输入是 4 阶，确认未命中目标仍需重洗
    assert max_tier.action == "重洗"

    only_max = parse_options(({"slot": "arm", "position": 1, "label": "防御力增加", "tier": 15},))
    result = advise(only_max, ("攻击力增加",))
    assert result.options[0].action == "重洗"
    assert "满级但非目标词条" in result.options[0].reasons[0]


def test_probability_only_shown_with_verifiable_table() -> None:
    table = {
        "source_url": "https://example.invalid/probability.json",
        "checked_at": "2026-09-21",
        "rates": {"攻击力增加": 10, "暴击伤害增加": 5},
    }
    advice = advise(options(), ("攻击力增加", "暴击伤害增加"), probability_table=table)
    assert advice.probability is not None
    assert "攻击力增加 10%" in advice.probability
    assert "HTTPS" not in advice.probability

    broken = advise(options(), ("攻击力增加",), probability_table={"rates": {"攻击力增加": 10}})
    assert broken.probability is None
    assert "按缺失处理" in broken.probability_note


def test_illegal_options_and_targets_are_rejected() -> None:
    with pytest.raises(OverloadAdviceError, match="未知装备位"):
        parse_options(({"slot": "weapon", "position": 1, "label": "攻击力增加", "tier": 1},))
    with pytest.raises(OverloadAdviceError, match="1–3"):
        parse_options(({"slot": "head", "position": 4, "label": "攻击力增加", "tier": 1},))
    with pytest.raises(OverloadAdviceError, match="1–15"):
        parse_options(({"slot": "head", "position": 1, "label": "攻击力增加", "tier": 16},))
    with pytest.raises(OverloadAdviceError, match="重复"):
        parse_options(
            (
                {"slot": "head", "position": 1, "label": "攻击力增加", "tier": 1},
                {"slot": "head", "position": 1, "label": "防御力增加", "tier": 2},
            )
        )
    with pytest.raises(OverloadAdviceError, match="未知目标词条"):
        parse_targets("并不存在的词条")
    assert set(parse_targets(["攻擊力增加"])) == {"攻击力增加"}


def test_locked_options_never_reroll_and_simulation_is_reproducible() -> None:
    source = (
        {"slot": "head", "position": 1, "label": "攻击力增加", "tier": 15, "locked": True},
        {"slot": "head", "position": 2, "label": "防御力增加", "tier": 2},
        {"slot": "torso", "position": 1, "label": "命中率增加", "tier": 3},
    )
    parsed = parse_options(source)
    targets = ("攻击力增加", "暴击伤害增加")

    first = simulate(parsed, targets, attempts=200, seed=7)
    second = simulate(parsed, targets, attempts=200, seed=7)

    assert first == second
    locked_after = next(item for item in first.final if item.locked)
    assert locked_after == parsed[0]
    # 非目标锁定词条不应阻止模拟达到“其余可洗词条均命中目标”。
    assert first.success is True
    assert first.attempts < 200
    assert "配置化假设" in first.assumption

    not_locked = parse_options(
        ({"slot": "head", "position": 1, "label": "防御力增加", "tier": 5},)
    )
    reference = advise(not_locked, ("攻击力增加",))
    # 建议保留未锁定的目标词条；重洗项在模拟中才可能改变。
    assert reference.options[0].action == "重洗"

    impossible = simulate(
        parsed,
        ("攻击力增加",),
        attempts=5,
        seed=1,
        distribution={"防御力增加": 1.0},
    )
    assert impossible.success is False
    assert len(impossible.final) == len(parsed)


def test_known_labels_are_the_verified_registry_labels() -> None:
    assert "攻击力增加" in KNOWN_LABELS
    assert "优越代码伤害增加" in KNOWN_LABELS
    assert len(KNOWN_LABELS) == 9


def test_tier_warnings_four_piece_counts_module_costs_and_os_randomness() -> None:
    opts = parse_options(
        (
            {"slot": "head", "position": 1, "label": "攻击力增加", "tier": 3, "locked": True},
            {"slot": "head", "position": 2, "label": "防御力增加", "tier": 4},
            {"slot": "torso", "position": 1, "label": "攻击力增加", "tier": 11},
        )
    )
    result = advise(
        opts,
        ("攻击力增加", "优越代码伤害增加"),
        target_counts={"攻击力增加": 4, "优越代码伤害增加": 4},
    )
    assert dict(result.matched_counts) == {"攻击力增加": 2, "优越代码伤害增加": 0}
    assert any("仅 3/15 阶" in w for w in result.lock_warnings)
    assert any("消耗 2 个定制模块" in w for w in result.lock_warnings)
    rendered = render_advice(result)
    assert "当前四件套命中汇总：攻击力增加 2/4 条" in rendered

    sim = simulate(opts, ("攻击力增加",), attempts=10)
    assert sim.seed is None
    assert "系统随机" in sim.assumption
    assert sim.modules_spent >= 1
    with_sim = render_advice(advise(opts, ("攻击力增加",)))
    assert "锁定与模块提醒" in with_sim
