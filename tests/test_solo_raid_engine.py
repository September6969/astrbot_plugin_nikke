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


@pytest.mark.asyncio
async def test_engine_never_forges_pinned_commit_strips_secrets_and_verifies_git(tmp_path: Path, monkeypatch) -> None:
    import shutil
    import subprocess
    from astrbot_plugin_nikke.integrations.nikke_calc.engine import MAX_OUTPUT_BYTES

    # 1. 无 evaluator commit 时不得静默回退到 PINNED_COMMIT，且 version_ok 必须为 False。
    no_eval = tmp_path / "no_eval"
    shutil.copytree(ENGINE_PATH, no_eval)
    (no_eval / "runner" / "sim.py").write_text(
        "import json, os\n"
        "assert 'NIKKE_TEST_SECRET' not in os.environ\n"
        "print(json.dumps({'schema_version': 2, 'total_damage': 12345}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NIKKE_TEST_SECRET", "top-secret-token")
    plan = build_five_teams(members())
    unverified_eng = SoloRaidDamageEngine(no_eval, mapping(), python=sys.executable, timeout=10, work_dir=tmp_path / "runs")
    res = await unverified_eng.estimate(plan.teams)
    assert res.available is True
    assert res.commit == ""
    assert res.dirty is None
    assert res.version_ok is False
    assert PINNED_COMMIT[:10] not in res.label

    # 2. 独立 Git 检出：非固定 commit 或 dirty 工作区必须拒绝（fail-closed）。
    git_repo = tmp_path / "git_engine"
    shutil.copytree(ENGINE_PATH, git_repo)
    subprocess.run(["git", "-C", str(git_repo), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(git_repo), "config", "user.name", "Tester"], check=True)
    subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True, capture_output=True)

    git_eng = SoloRaidDamageEngine(git_repo, mapping(), python=sys.executable, timeout=10, work_dir=tmp_path / "runs2")
    rejected = await git_eng.estimate(plan.teams)
    assert rejected.available is False
    assert rejected.version_ok is False
    assert "版本校验失败" in rejected.reason

    # 允许不核验模式运行，但 version_ok 仍为 False，且不会被自报 commit 欺骗。
    untrusted_eng = SoloRaidDamageEngine(
        git_repo, mapping(), python=sys.executable, timeout=10, work_dir=tmp_path / "runs3", allow_unverified=True
    )
    untrusted_res = await untrusted_eng.estimate(plan.teams)
    assert untrusted_res.available is True
    assert untrusted_res.commit != PINNED_COMMIT
    assert untrusted_res.version_ok is False

    # 3. 超过 MAX_OUTPUT_BYTES 的引擎输出必须被拒绝。
    huge = tmp_path / "huge"
    shutil.copytree(ENGINE_PATH, huge)
    (huge / "runner" / "sim.py").write_text(
        f"import sys\nsys.stdout.write('x' * ({MAX_OUTPUT_BYTES} + 100))\n",
        encoding="utf-8",
    )
    huge_eng = SoloRaidDamageEngine(huge, mapping(), python=sys.executable, timeout=10, work_dir=tmp_path / "runs4")
    huge_res = await huge_eng.estimate(plan.teams[:1])
    assert huge_res.total is None
    assert "大小上限" in huge_res.teams[0].error


@pytest.mark.asyncio
async def test_engine_resolves_resource_id_and_electronic_element() -> None:
    from astrbot_plugin_nikke.features.solo_raid.builder import Team

    eng = SoloRaidDamageEngine(
        ENGINE_PATH,
        {"10": "L1-1", "11": "L1-2", "12": "L1-3", "13": "L1-4", "14": "L1-5"},
        python=sys.executable,
        timeout=10,
        work_dir=Path("output") / ".engine-runs",
    )
    team = Team(
        index=1,
        members=tuple(
            Member(f"uncoded-{i}", f"未译名{i}", "Step1", resource_id=str(10 + i))
            for i in range(5)
        ),
        chain_ok=True,
    )
    req = eng._request(team, "Electronic")
    assert req["squad"] == ["L1-1", "L1-2", "L1-3", "L1-4", "L1-5"]
    assert req["enemy"] == {"code": "전격"}
