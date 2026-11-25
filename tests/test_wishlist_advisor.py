# SPDX-License-Identifier: GPL-3.0-or-later
"""16 愿望单推荐：纯 SSR 准入、160 壁垒仅计 SSR、排除 ABNORMAL、企业 5 席与别名解析。"""

from __future__ import annotations

import pytest

from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.wishlist.advisor import (
    MANUFACTURER_LABELS,
    MANUFACTURER_SLOTS,
    WishlistError,
    normalize_strategy,
    parse_owned,
    recommend,
    render_wishlist,
)

ROWS = (
    {"name_code": 1001, "name_zh_cn": "拉毗", "name_en": "Rapi", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "ELYSION", "pool_status": "ordinary_recruit"},
    {"name_code": 1002, "name_zh_cn": "尼恩", "rare": "SSR", "burst": "Step1", "element": "Wind", "corporation": "ELYSION", "pool_status": "ordinary_recruit"},
    {"name_code": 1003, "name_zh_cn": "阿妮斯", "rare": "SSR", "burst": "Step2", "element": "Iron", "corporation": "TETRA", "pool_status": "ordinary_recruit"},
    {"name_code": 1004, "name_zh_cn": "迪塞尔", "rare": "SR", "burst": "Step2", "element": "Water", "corporation": "ELYSION"},
    {"name_code": 1005, "name_zh_cn": "米哈拉", "rare": "SSR", "burst": "Step3", "element": "Electronic", "corporation": "MISSILIS", "pool_status": "ordinary_recruit"},
    {"name_code": 1006, "name_zh_cn": "联动限定", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "ABNORMAL", "pool_status": "collab"},
    {"name_code": 1007, "name_zh_cn": "未知稀有度", "rare": "UR", "burst": "Step3", "element": "Fire", "corporation": "TETRA"},
    {"name_code": 1008, "name_zh_cn": "饼干", "rare": "SSR", "burst": "Step1", "element": "Iron", "corporation": "TETRA", "pool_status": "ordinary_recruit"},
    {"name_code": 1009, "name_zh_cn": "神罚", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "PILGRIM", "pool_status": "pilgrim_overspec"},
    {"name_code": 1010, "name_zh_cn": "普丽瓦蒂", "rare": "SSR", "burst": "Step3", "element": "Water", "corporation": "ELYSION", "pool_status": "ordinary_recruit"},
    {"name_code": 1011, "name_zh_cn": "丽塔", "rare": "SSR", "burst": "Step1", "element": "Iron", "corporation": "MISSILIS", "pool_status": "ordinary_recruit"},
    {"name_code": 9, "name_zh_cn": "九号", "rare": "SSR", "burst": "Step2", "element": "Wind", "corporation": "MISSILIS", "pool_status": "ordinary_recruit"},
)


def test_only_ssr_admitted_and_sr_does_not_count_toward_160_wall() -> None:
    # 持有 4 名 3 星 SSR + 1 名 3 星 SR（迪塞尔）：SR 不得计入 160 破壁，不得进入愿望单。
    owned = parse_owned("尼恩:3,阿妮斯:3,米哈拉:3,饼干:3,迪塞尔:3,丽塔:2")
    result = recommend(ROWS, owned, "balanced")

    assert result.wall_reached is False
    assert result.wall_progress == "4/5 名 3 星 SSR"
    names = [candidate.name for candidate in result.candidates]
    assert "迪塞尔" not in names
    assert "联动限定" not in names  # ABNORMAL 自动排除
    assert "未知稀有度" not in names
    assert result.abnormal_excluded_count == 1
    assert result.non_ssr_excluded_count == 2

    # 未破 160 墙的 2 星 SSR（丽塔）在 balanced 策略获得最高分。
    assert result.candidates[0].name == "丽塔"
    assert any("2 星 SSR 补到 3 星" in reason for reason in result.candidates[0].reasons)

    text = render_wishlist(result)
    assert "【愿望单推荐 · 均衡】（仅限普通招募 SSR）" in text
    assert "仅统计 3 星 SSR" in text
    assert "ABNORMAL 异界/联动 1 名" in text
    assert "覆盖限制" in text


def test_five_ssr_breaks_160_wall_and_three_strategies_differ() -> None:
    owned = parse_owned("尼恩:3,阿妮斯:3,米哈拉:3,饼干:3,丽塔:3,拉毗:2")
    collection = recommend(ROWS, owned, "collection")
    investment = recommend(ROWS, owned, "investment")

    assert collection.wall_reached is True
    assert collection.wall_progress == "5/5 名 3 星 SSR"
    assert investment.wall_reached is True

    # 收集策略优先未拥有的 SSR，已 3 星 SSR 降权。
    assert not collection.candidates[0].owned
    assert any("已通过 160 壁垒" in reason for reason in collection.candidates[0].reasons)

    # 养成策略把仍可突破的 2 星拉毗排在已 3 星角色之前。
    investment_scores = {candidate.name: candidate.score for candidate in investment.candidates}
    assert investment_scores["拉毗"] > investment_scores["丽塔"]


def test_manufacturer_groups_cap_at_5_slots_and_include_pilgrim() -> None:
    many_elysion = tuple(
        {
            "name_code": 2000 + i,
            "name_zh_cn": f"极乐{i}",
            "rare": "SSR",
            "burst": "Step3",
            "element": "Fire",
            "corporation": "ELYSION",
            "pool_status": "ordinary_recruit",
        }
        for i in range(1, 8)
    ) + (
        {"name_code": 3001, "name_zh_cn": "小红帽", "rare": "SSR", "burst": "Step3", "element": "Iron", "corporation": "PILGRIM", "pool_status": "pilgrim_overspec"},
    )
    result = recommend(many_elysion, (), "collection")
    groups = result.groups()
    assert len(groups[MANUFACTURER_LABELS["ELYSION"]]) == MANUFACTURER_SLOTS
    assert len(groups[MANUFACTURER_LABELS["PILGRIM"]]) == 1
    assert result.candidates[0].corporation == "ELYSION"


def test_parse_owned_resolves_aliases_and_sorts_codes_naturally() -> None:
    resolver = CharacterDirectoryResolver()
    owned = parse_owned("Rapi:2", rows=ROWS, resolver=resolver)
    assert len(owned) == 1
    assert owned[0].name_code == "1001"
    assert owned[0].limit_break == 2

    # 同样分数时，"9" 排在 "1010" 之前（数字自然排序而非字典序）。
    two_units = (
        {"name_code": 1010, "name_zh_cn": "十号", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "MISSILIS", "pool_status": "ordinary_recruit"},
        {"name_code": 9, "name_zh_cn": "九号", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "MISSILIS", "pool_status": "ordinary_recruit"},
    )
    res = recommend(two_units, (), "collection")
    assert [c.name_code for c in res.candidates] == ["9", "1010"]


def test_results_are_deterministic_regardless_of_input_order() -> None:
    owned = parse_owned("拉毗:1")
    first = recommend(ROWS, owned, "balanced")
    second = recommend(tuple(reversed(ROWS)), owned, "balanced")
    assert [candidate.name_code for candidate in first.candidates] == [
        candidate.name_code for candidate in second.candidates
    ]


def test_unknown_strategy_and_bad_limits_are_rejected() -> None:
    with pytest.raises(WishlistError, match="未知策略"):
        normalize_strategy("pvp")
    with pytest.raises(WishlistError, match="1–30"):
        recommend(ROWS, (), "balanced", limit=0)
    with pytest.raises(WishlistError, match="缺少角色元数据"):
        recommend((), (), "balanced")


def test_pool_eligibility_fail_closed_excludes_limited_welfare_new_collab_and_unknown() -> None:
    import json
    from pathlib import Path
    from astrbot_plugin_nikke.features.wishlist.advisor import load_pool_eligibility

    sample_rows = (
        {"name_code": 1, "name_zh_cn": "常规", "rare": "SSR", "burst": "Step1", "element": "Fire", "corporation": "ELYSION"},
        {"name_code": 2, "name_zh_cn": "超限拉毗", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "ELYSION"},
        {"name_code": 3, "name_zh_cn": "夏日限定", "rare": "SSR", "burst": "Step3", "element": "Water", "corporation": "TETRA"},
        {"name_code": 4, "name_zh_cn": "新卡未入普池", "rare": "SSR", "burst": "Step2", "element": "Iron", "corporation": "MISSILIS"},
        {"name_code": 5, "name_zh_cn": "周年白送", "rare": "SSR", "burst": "Step2", "element": "Wind", "corporation": "MISSILIS"},
        {"name_code": 6, "name_zh_cn": "未知新角色", "rare": "SSR", "burst": "Step3", "element": "Iron", "corporation": "TETRA"},
        {"name_code": 7, "name_zh_cn": "未登记角色", "rare": "SSR", "burst": "Step3", "element": "Fire", "corporation": "ELYSION"},
    )
    # 1. 不传 eligibility 且行内无 pool_status：所有未知角色必须 fail-closed 拒绝，绝不默认推荐。
    no_elig = recommend(sample_rows, (), "collection")
    assert no_elig.candidates == ()
    assert no_elig.unknown_excluded_count == len(sample_rows)

    # 2. 传入准入表：只放行 ordinary_recruit 与 pilgrim_overspec；Over-Spec 归入 PILGRIM 独立池。
    elig = {
        "1": "ordinary_recruit",
        "2": {"pool_status": "pilgrim_overspec", "wishlist_group": "PILGRIM"},
        "3": "limited",
        "4": "new_not_yet_ordinary",
        "5": "free_welfare",
        "6": "unknown",
    }
    res = recommend(sample_rows, (), "balanced", eligibility=elig)
    assert [c.name_code for c in res.candidates] == ["1", "2"]
    assert res.candidates[1].corporation == "PILGRIM"
    assert res.limited_excluded_count == 2
    assert res.welfare_excluded_count == 1
    assert res.unknown_excluded_count == 2  # #6 unknown + #7 未登记
    text = render_wishlist(res)
    assert "限定/未入普池 2 名" in text
    assert "免费/解放 1 名" in text
    assert "准入未知（默认拒绝）2 名" in text

    # 3. 仓库自带 wishlist_pool_eligibility.json 覆盖全部 character_master SSR 且真实运行无异常。
    root = Path(__file__).resolve().parents[1]
    real_elig = load_pool_eligibility(root / "assets" / "data" / "wishlist_pool_eligibility.json")
    master = json.loads((root / "assets" / "data" / "character_master.json").read_text(encoding="utf-8"))["characters"]
    master_ssrs = {str(c["name_code"]) for c in master if c.get("rare") == "SSR"}
    assert master_ssrs <= set(real_elig)
    real_res = recommend(master, (), "balanced", eligibility=real_elig, limit=30)
    admitted_codes = {c.name_code for c in real_res.candidates}
    assert "5089" not in admitted_codes  # 马奇玛 collab 排除
    assert "5071" not in admitted_codes  # 泳装尼恩 limited 排除
    assert "5055" not in admitted_codes  # 解放吉尔提 free_welfare 排除
    assert "5129" in [c.name_code for c in real_res.candidates] or real_elig["5129"].wishlist_group == "PILGRIM"

