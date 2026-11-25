# SPDX-License-Identifier: GPL-3.0-or-later
"""12 同步器等级计算：跨阶、库存充足、零产量与非法输入。"""

from __future__ import annotations

from datetime import date

import pytest

from astrbot_plugin_nikke.features.sync.calculator import (
    SyncLevelInputError,
    calculate_sync_plan,
    render_sync_plan,
)
from astrbot_plugin_nikke.features.sync.cost_table import SyncCostTable, SyncCostTableError

SOURCE = "https://example.invalid/synthetic-sync-costs.json"


def table() -> SyncCostTable:
    """合成成本表：每级资源不同，用来验证跨阶累加。"""
    return SyncCostTable.from_records(
        (
            {"level": 200, "core_dust": 900, "credits": 1200, "battle_data": 300},
            {"level": 201, "core_dust": 1000, "credits": 1500, "battle_data": 400},
            {"level": 202, "core_dust": 1100, "credits": 1800, "battle_data": 500},
            {"level": 203, "core_dust": 1200, "credits": 2100, "battle_data": 600},
        ),
        source_url=SOURCE,
        checked_at="2026-09-21",
        label="合成成本表",
    )


def test_cross_tier_costs_are_summed_and_bottleneck_sets_date() -> None:
    plan = calculate_sync_plan(
        current=199,
        target=202,
        inventory={"core_dust": 0, "credits": 3000, "battle_data": 0},
        production={"core_dust": 400, "credits": 1000, "battle_data": 100},
        table=table(),
        today=date(2026, 9, 21),
    )

    # 199 → 202 需要累加 200、201、202 三级成本（跨阶），不能只取目标级。
    assert plan.required == {"core_dust": 3000, "credits": 4500, "battle_data": 1200}
    by_name = {item.resource: item for item in plan.resources}
    assert by_name["core_dust"].days == 8  # ceil(3000 / 400)
    assert by_name["credits"].days == 2    # 缺口 1500 / 1000
    assert by_name["credits"].status == "需要积累"
    assert by_name["battle_data"].days == 12  # ceil(1200 / 100)
    assert plan.overall_days == 12
    assert plan.eta == date(2026, 10, 3)
    assert plan.bottlenecks == ("战斗数据",)
    assert "瓶颈：战斗数据" in render_sync_plan(plan)


def test_sufficient_stock_returns_same_day_and_no_bottleneck() -> None:
    plan = calculate_sync_plan(
        current=199,
        target=200,
        inventory={"core_dust": 10_000, "credits": 10_000, "battle_data": 10_000},
        production={"core_dust": 0, "credits": 0, "battle_data": 0},
        table=table(),
        today=date(2026, 9, 21),
    )
    assert plan.overall_days == 0
    assert plan.eta == date(2026, 9, 21)
    assert plan.bottlenecks == ("芯尘", "信用点", "战斗数据")
    assert all(item.days == 0 for item in plan.resources)


def test_zero_production_with_deficit_cannot_be_estimated() -> None:
    plan = calculate_sync_plan(
        current=199,
        target=200,
        inventory={"core_dust": 100, "credits": 10_000, "battle_data": 10_000},
        production={"core_dust": 0, "credits": 100, "battle_data": 100},
        table=table(),
        today=date(2026, 9, 21),
    )
    assert plan.overall_days is None
    assert plan.eta is None
    assert plan.bottlenecks == ("芯尘",)
    text = render_sync_plan(plan)
    assert "无法估算" in text
    assert "零产量" in text


def test_plan_requires_contiguous_cost_cover() -> None:
    with pytest.raises(SyncLevelInputError, match="未覆盖等级"):
        calculate_sync_plan(
            current=198,
            target=200,
            inventory={},
            production={"core_dust": 1, "credits": 1, "battle_data": 1},
            table=table(),
        )


def test_missing_cost_table_is_explicit_instead_of_guessed() -> None:
    with pytest.raises(SyncLevelInputError, match="缺少可靠等级成本表"):
        calculate_sync_plan(
            current=100,
            target=120,
            inventory={},
            production={},
            table=None,
        )


@pytest.mark.parametrize(
    "kwargs, message",
    (
        ({"current": 0}, "当前等级"),
        ({"target": 100}, "目标等级必须高于"),
        ({"target": 2001}, "目标等级"),
        ({"inventory": {"core_dust": -1}}, "芯尘库存"),
        ({"production": {"credits": -0.5}}, "信用点日产量"),
        ({"production": {"battle_data": float("inf")}}, "战斗数据日产量"),
        ({"production": {"battle_data": "many"}}, "战斗数据日产量"),
    ),
)
def test_invalid_inputs_are_rejected(kwargs, message) -> None:
    base = dict(
        current=199,
        target=200,
        inventory={"core_dust": 0, "credits": 0, "battle_data": 0},
        production={"core_dust": 1, "credits": 1, "battle_data": 1},
        table=table(),
    )
    base.update(kwargs)
    with pytest.raises(SyncLevelInputError, match=message):
        calculate_sync_plan(**base)


def test_cost_table_rejects_gaps_duplicates_and_non_https_sources() -> None:
    with pytest.raises(SyncCostTableError, match="不连续"):
        SyncCostTable.from_records(
            (
                {"level": 200, "core_dust": 1, "credits": 1, "battle_data": 1},
                {"level": 202, "core_dust": 1, "credits": 1, "battle_data": 1},
            ),
            source_url=SOURCE,
            checked_at="2026-09-21",
        )
    with pytest.raises(SyncCostTableError, match="等级重复"):
        SyncCostTable.from_records(
            (
                {"level": 200, "core_dust": 1, "credits": 1, "battle_data": 1},
                {"level": 200, "core_dust": 2, "credits": 2, "battle_data": 2},
            ),
            source_url=SOURCE,
            checked_at="2026-09-21",
        )
    with pytest.raises(SyncCostTableError, match="HTTPS"):
        SyncCostTable.from_records(
            ({"level": 200, "core_dust": 1, "credits": 1, "battle_data": 1},),
            source_url="http://example.invalid/costs.json",
            checked_at="2026-09-21",
        )


def test_manual_cumulative_costs_work_without_a_table() -> None:
    plan = calculate_sync_plan(
        current=199,
        target=202,
        inventory={"core_dust": 0, "credits": 4500, "battle_data": 0},
        production={"core_dust": 400, "credits": 0, "battle_data": 100},
        table=None,
        manual_costs={"core_dust": 3000, "credits": 4500, "battle_data": 1200},
        today=date(2026, 9, 21),
    )
    assert plan.required == {"core_dust": 3000, "credits": 4500, "battle_data": 1200}
    assert plan.overall_days == 12
    assert plan.eta == date(2026, 10, 3)
    assert plan.table is None
    text = render_sync_plan(plan)
    assert "用户手工输入" in text
    assert "https://" not in text  # 用户输入不要求来源 URL
    assert "核验" not in text
    assert "无法估算" not in text


def test_manual_costs_validate_negative_and_missing_values() -> None:
    with pytest.raises(SyncLevelInputError, match="芯尘累计成本"):
        calculate_sync_plan(
            current=199, target=200, inventory={}, production={},
            table=None, manual_costs={"credits": 1, "battle_data": 1},
        )
    with pytest.raises(SyncLevelInputError, match="信用点累计成本"):
        calculate_sync_plan(
            current=199, target=200, inventory={}, production={},
            table=None,
            manual_costs={"core_dust": 1, "credits": -1, "battle_data": 1},
        )


def test_imported_sync_table_loads_and_computes_cross_tier(tmp_path) -> None:
    import json
    from pathlib import Path
    from astrbot_plugin_nikke.features.sync.cost_table import SyncCostTable

    bundled = Path(__file__).resolve().parents[1] / "assets" / "data" / "sync_level_costs.json"
    assert bundled.is_file()
    bundled_table = SyncCostTable.from_file(bundled)
    assert bundled_table.levels[0] == 2 and bundled_table.levels[-1] == 1400
    # Lv.200→201 为单级 10,000 芯尘；Lv.574→600 共 26 级；Lv.1001→1002 为 22,000 芯尘
    assert bundled_table.cost_between(200, 201) == {
        "core_dust": 10_000,
        "credits": 1_694_200,
        "battle_data": 20_944_600,
    }
    assert bundled_table.cost_between(574, 600) == {
        "core_dust": 26 * 15_000,
        "credits": 26 * 9_003_629,
        "battle_data": 26 * 78_347_935,
    }
    assert bundled_table.cost_between(1001, 1002) == {
        "core_dust": 22_000,
        "credits": 12_985_017,
        "battle_data": 119_584_414,
    }

    levels = [
        {
            "level": level,
            "core_dust": 10_000 if level <= 350 else 11_000,
            "credits": 1_694_200,
            "battle_data": 20_944_600,
        }
        for level in range(201, 352)
    ]
    path = tmp_path / "sync-level-costs.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "label": "运营者导入成本表",
                "source_url": "https://example.invalid/tools/sync-level",
                "checked_at": "2026-11-24",
                "levels": levels,
            }
        ),
        encoding="utf-8",
    )
    table = SyncCostTable.from_file(path)
    assert table.levels[0] == 201 and table.levels[-1] == 351
    assert table.cost_between(200, 201) == {"core_dust": 10_000, "credits": 1_694_200, "battle_data": 20_944_600}
    cross = table.cost_between(200, 351)
    assert cross["core_dust"] == 150 * 10_000 + 11_000

    # 库存可立即升两级时应准确给出 reachable_level；超出成本表范围给出手工模式提示。
    plan = calculate_sync_plan(
        current=200,
        target=205,
        inventory={"core_dust": 25_000, "credits": 4_000_000, "battle_data": 50_000_000},
        production={"core_dust": 1_000, "credits": 1_000_000, "battle_data": 1_000_000},
        table=table,
        today=date(2026, 11, 24),
    )
    assert plan.gainable_levels == 2
    assert plan.reachable_level == 202
    assert "现有库存可立即升至：Lv.202（+2 级）" in render_sync_plan(plan)

    with pytest.raises(SyncLevelInputError, match="手工成本模式"):
        calculate_sync_plan(
            current=200, target=400, inventory={}, production={}, table=table
        )


def test_updater_payload_round_trips_into_sync_calculator(tmp_path) -> None:
    from astrbot_plugin_nikke.features.sync.public_source import (
        build_sync_payload,
        parse_sync_ranges,
        write_sync_payload,
    )

    rows = parse_sync_ranges(
        "let n=[{from:201,to:203,credit:1000,battleData:200,coreDust:500}];e.s(["
    )
    payload = build_sync_payload(rows, checked_at="2026-11-24")
    out = tmp_path / "sync.json"
    assert write_sync_payload(out, payload) is True
    loaded = SyncCostTable.from_file(out)
    plan = calculate_sync_plan(
        current=200, target=203,
        inventory={"core_dust": 600, "credits": 1200, "battle_data": 300},
        production={"core_dust": 500, "credits": 1000, "battle_data": 200},
        table=loaded,
        today=date(2026, 11, 24),
    )
    assert plan.gainable_levels == 1
    assert plan.reachable_level == 201
    assert plan.overall_days == 2


def test_bundled_outpost_rates_cases_academy_and_extrapolation() -> None:
    from pathlib import Path
    from astrbot_plugin_nikke.features.sync.calculator import plan_sync_from_inputs
    from astrbot_plugin_nikke.features.sync.outpost import (
        OutpostRateTable,
        extract_account_sync_context,
        infer_academy_boosts,
    )

    root = Path(__file__).resolve().parents[1] / "assets" / "data"
    cost_table = SyncCostTable.from_file(root / "sync_level_costs.json")
    outpost_table = OutpostRateTable.from_file(root / "outpost_rates.json")

    # Lv.400 满学院加成精确校验：9046 * 1 / 10000 * 60 * 1.45 = 78.70 芯尘/小时
    r400 = outpost_table.hourly_rates(400)
    assert r400.estimated_above_400 is False
    assert r400.hourly["core_dust"] == pytest.approx(78.70, abs=0.02)
    assert r400.hourly["credits"] == pytest.approx(51027.75, abs=0.2)

    # Lv.651 已在交叉核验扩展表（1–800）内精确查表，不再线性外推；Lv.850 才标注外推
    boosts, academy_note = infer_academy_boosts(13000, 13003)
    assert boosts == {"credits": 60.0, "battle_data": 45.0, "core_dust": 45.0}
    assert "满级加成" in academy_note
    partial_boosts, partial_note = infer_academy_boosts(9000, 9002)
    assert partial_boosts == {"credits": 60.0, "battle_data": 45.0, "core_dust": 25.0}
    assert "课程 9002" in partial_note
    r533 = outpost_table.hourly_rates(533)
    assert r533.hourly["core_dust"] == pytest.approx(102.22, abs=0.05)
    r651 = outpost_table.hourly_rates(651, academy_boosts=boosts, academy_note=academy_note)
    assert r651.estimated_above_400 is False
    assert r651.hourly["core_dust"] == pytest.approx(113.21, abs=0.05)
    r850 = outpost_table.hourly_rates(850)
    assert r850.estimated_above_400 is True

    # 真实账号 profile 自动提取与背包资源箱 + 歼灭 + 额外日产端到端计算
    profile = {
        "basic": {
            "currencies": [
                {"type": 3000, "value": "8746"},
                {"type": 2000, "value": "8648063"},
                {"type": 1000, "value": "48966309"},
            ]
        },
        "outpost": {
            "synchro_level": 574,
            "outpost_battle_level": 651,
            "tactic_academy_class": 13000,
            "tactic_academy_lesson": 13003,
        },
    }
    ctx = extract_account_sync_context(profile, outpost_table, cost_table)
    assert ctx.synchro_level == 574
    assert ctx.outpost_level == 651
    assert ctx.inventory["core_dust"] == 8746
    assert ctx.gainable_levels == 0
    assert ctx.next_level_missing["core_dust"] == 15_000 - 8746

    plan, outpost_meta = plan_sync_from_inputs(
        current=574,
        target=580,
        inventory=ctx.inventory,
        outpost_level=651,
        academy_class=13000,
        cases={
            "core_dust": {"24h": 5, "1h": 10},
            "credits": {"24h": 2},
            "battle_data": {"24h": 5},
        },
        wipeout_count=1,
        extra_daily={"core_dust": 500},
        table=cost_table,
        outpost_table=outpost_table,
        today=date(2026, 11, 25),
    )
    assert outpost_meta is not None
    assert outpost_meta["case_hours"]["core_dust"] == 130
    assert plan.case_yields["core_dust"] > 10_000
    assert plan.gainable_levels >= 1
    assert plan.gainable_without_cases == 0
    assert "箱子" in render_sync_plan(plan)
