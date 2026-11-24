# SPDX-License-Identifier: GPL-3.0-or-later
"""22 外部 MIT 估伤引擎：JSON 合同、版本出处、缺映射与失败边界（合成引擎桩）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from astrbot_plugin_nikke.features.solo_raid.builder import Member, build_five_teams
from astrbot_plugin_nikke.integrations.nikke_calc.engine import (
    ENGINE_REPO,
    PINNED_COMMIT,
    EngineNameMappingError,
    SoloRaidDamageEngine,
    load_name_mapping,
)

ENGINE_PATH = Path(__file__).resolve().parent / "fixtures" / "fake_nikke_calc"


def members() -> tuple[Member, ...]:
    rows: list[Member] = []
    for index in range(1, 6):
        rows.append(Member(f"1-{index}", f"L1-{index}", "Step1"))
        rows.append(Member(f"2-{index}", f"L2-{index}", "Step2"))
    for index in range(1, 16):
        rows.append(Member(f"3-{index}", f"L3-{index}", "Step3"))
    return tuple(rows)


def mapping() -> dict[str, str]:
    return {member.name: member.name for member in members()}


def engine(**kwargs) -> SoloRaidDamageEngine:
    return SoloRaidDamageEngine(
        ENGINE_PATH,
        mapping(),
        python=sys.executable,
        timeout=30,
        work_dir=Path("output") / ".engine-runs",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_engine_returns_per_team_and_total_with_pinned_version() -> None:
    plan = build_five_teams(members())
    result = await engine().estimate(plan.teams, boss_element="风压")

    assert result.available is True
    assert result.total is not None
    assert len(result.teams) == 5
    assert all(item.damage is not None and item.damage > 0 for item in result.teams)
    assert result.commit == PINNED_COMMIT
    assert result.dirty is False
    assert result.version_ok is True
    assert "MIT" in result.label
    assert ENGINE_REPO in result.note and PINNED_COMMIT in result.note
    assert "不是官方伤害数值" in result.note


@pytest.mark.asyncio
async def test_missing_mapping_or_engine_is_explicit_and_never_fabricates() -> None:
    plan = build_five_teams(members())
    no_mapping = SoloRaidDamageEngine(
        ENGINE_PATH, {}, python=sys.executable, work_dir=Path("output") / ".engine-runs"
    )
    result = await no_mapping.estimate(plan.teams)
    assert result.available is False
    assert result.total is None
    assert "名称映射" in result.reason

    missing_path = SoloRaidDamageEngine(
        ENGINE_PATH / "missing", mapping(), python=sys.executable,
        work_dir=Path("output") / ".engine-runs",
    )
    result = await missing_path.estimate(plan.teams)
    assert result.available is False
    assert result.total is None
    assert "未找到" in result.reason


@pytest.mark.asyncio
async def test_partial_team_failure_keeps_total_unknown_and_reports_reason() -> None:
    plan = build_five_teams(members())
    broken = mapping()
    first_team_code = plan.teams[0].members[0].name_code
    broken.pop(next(key for key in broken if key == plan.teams[0].members[0].name))
    result = await engine_with_mapping(broken).estimate(plan.teams)
    assert result.available is True
    assert result.total is None
    assert any("缺少引擎官方名映射" in item.error for item in result.teams)
    assert "部分队伍无法估伤" in result.note
    assert first_team_code  # 说明失败按队报告，未伪造 0


def engine_with_mapping(values: dict[str, str]) -> SoloRaidDamageEngine:
    return SoloRaidDamageEngine(
        ENGINE_PATH, values, python=sys.executable, timeout=30,
        work_dir=Path("output") / ".engine-runs",
    )


def test_name_mapping_requires_mit_engine_provenance(tmp_path=None) -> None:
    import json
    import tempfile

    payload = {
        "schema_version": 1,
        "engine_repo": ENGINE_REPO,
        "engine_commit": PINNED_COMMIT,
        "source_url": f"https://github.com/{ENGINE_REPO}/tree/{PINNED_COMMIT}",
        "names": {"L1": "L1"},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        path = Path(handle.name)
    try:
        assert load_name_mapping(path) == {"L1": "L1"}
        payload["engine_commit"] = "short"
        handle = Path(handle.name)
        handle.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(EngineNameMappingError, match="40 位"):
            load_name_mapping(handle)
    finally:
        path.unlink(missing_ok=True)


def test_real_engine_name_mapping_uses_stable_resource_and_name_codes() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "assets" / "data" / "solo_raid_engine_names.json"
    mapping = load_name_mapping(path)
    assert mapping["10"] == "라피"
    assert mapping["3001"] == "라피"
    assert mapping["Rapi"] == "라피"
    assert len(mapping) > 800
    # 明确不存在的角色不会被按译名猜出。
    assert "not-a-real-nikke" not in mapping
