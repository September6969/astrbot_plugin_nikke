# SPDX-License-Identifier: GPL-3.0-or-later
"""16 愿望单推荐：低练、缺人、策略差异、确定性与排除规则。"""

from __future__ import annotations

import pytest

from astrbot_plugin_nikke.features.wishlist.advisor import (
    WishlistError,
    normalize_strategy,
    parse_owned,
    recommend,
    render_wishlist,
)

ROWS = (
    {"name_code": 1001, "name_zh_cn": "拉毗", "rare": "SSR", "burst": "Step3", "element": "Fire"},
    {"name_code": 1002, "name_zh_cn": "尼恩", "rare": "SSR", "burst": "Step1", "element": "Wind"},
    {"name_code": 1003, "name_zh_cn": "阿妮斯", "rare": "SSR", "burst": "Step2", "element": "Iron"},
    {"name_code": 1004, "name_zh_cn": "迪塞尔", "rare": "SR", "burst": "Step2", "element": "Water"},
    {"name_code": 1005, "name_zh_cn": "米哈拉", "rare": "SSR", "burst": "Step3", "element": "Electric"},
    {"name_code": 1006, "name_zh_cn": "联动限定", "rare": "SSR", "burst": "Step3", "element": "Fire"},
    {"name_code": 1007, "name_zh_cn": "未知稀有度", "rare": "UR", "burst": "Step3", "element": "Fire"},
    {"name_code": 1008, "name_zh_cn": "饼干", "rare": "SSR", "burst": "Step1", "element": "Iron"},
)


def test_low_investment_and_missing_roles_are_explained() -> None:
    owned = parse_owned("拉毗:0,迪塞尔:2")
    result = recommend(ROWS, owned, "balanced")

    assert result.wall_reached is False
    assert "0/5" in result.wall_progress
    assert result.missing_roles == ("B1",)
    names = [candidate.name for candidate in result.candidates]
    assert "尼恩" in names  # 缺 B1 且未拥有
    # 缺 B1 时优先补功能位；2 星补 3 星仍进入候选并给出理由。
    assert result.candidates[0].name == "尼恩"
    disel = next(candidate for candidate in result.candidates if candidate.name == "迪塞尔")
    assert any("2 星补到 3 星" in reason for reason in disel.reasons)

    text = render_wishlist(result)
    assert "【愿望单推荐 · 均衡】" in text
    assert "缺少定位：B1" in text
    assert "覆盖限制" in text


def test_three_strategies_produce_different_priorities() -> None:
    owned = parse_owned("尼恩:3,阿妮斯:3,迪塞尔:3,米哈拉:3,饼干:3,拉毗:2")
    collection = recommend(ROWS, owned, "collection")
    investment = recommend(ROWS, owned, "investment")

    assert collection.wall_reached is True
    assert investment.wall_reached is True
    collection_names = [candidate.name for candidate in collection.candidates]
    assert "联动限定" in collection_names  # 收集：未拥有优先
    assert any("已通过 160 壁垒" in reason for reason in collection.candidates[0].reasons)
    # 养成策略把仍可突破的 2 星拉毗排到未拥有的联动限定之前。
    assert any("可继续突破" in reason for reason in investment.candidates[0].reasons)

    # 养成策略对已 3 星角色降低收集权重，但仍保留在候选中用于说明。
    investment_scores = {candidate.name: candidate.score for candidate in investment.candidates}
    assert investment_scores["联动限定"] < max(investment_scores.values())


def test_exclusions_and_unverifiable_metadata_are_filtered_with_note() -> None:
    result = recommend(ROWS, (), "collection", exclusions=("1006",))
    names = [candidate.name for candidate in result.candidates]
    assert "联动限定" not in names
    assert "未知稀有度" not in names  # 缺少稳定稀有度不猜测入池
    assert "可入池" in result.coverage_note


def test_results_are_deterministic_regardless_of_input_order() -> None:
    owned = parse_owned("拉毗:1")
    first = recommend(ROWS, owned, "balanced")
    second = recommend(tuple(reversed(ROWS)), owned, "balanced")
    assert [candidate.name_code for candidate in first.candidates] == [
        candidate.name_code for candidate in second.candidates
    ]
    assert [candidate.score for candidate in first.candidates] == [
        candidate.score for candidate in second.candidates
    ]


def test_groups_follow_burst_stage_and_parse_owned_merges_duplicates() -> None:
    owned = parse_owned("拉毗,拉毗:2,迪塞尔(3星)")
    assert len(owned) == 2
    by_name = {item.name: item for item in owned}
    assert by_name["拉毗"].limit_break == 2
    assert by_name["迪塞尔"].limit_break == 3

    result = recommend(ROWS, owned, "collection")
    groups = result.groups()
    assert set(groups) <= {"B1", "B2", "B3"}
    assert all(
        candidate.group == group
        for group, candidates in groups.items()
        for candidate in candidates
    )


def test_unknown_strategy_and_bad_limits_are_rejected() -> None:
    with pytest.raises(WishlistError, match="未知策略"):
        normalize_strategy("pvp")
    with pytest.raises(WishlistError, match="1–30"):
        recommend(ROWS, (), "balanced", limit=0)
    with pytest.raises(WishlistError, match="缺少角色元数据"):
        recommend((), (), "balanced")
