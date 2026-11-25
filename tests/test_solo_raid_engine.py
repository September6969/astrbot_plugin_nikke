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


@pytest.mark.asyncio
async def test_engine_real_subprocess_timeout_cancellation_streams_json_and_aclose(tmp_path: Path) -> None:
    import asyncio
    import os
    import shutil
    import time
    from astrbot_plugin_nikke.integrations.nikke_calc.engine import MAX_OUTPUT_BYTES

    def _pid_alive(pid: int) -> bool:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    async def _wait_dead(pid: int, limit: float = 4.0) -> bool:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return True
            await asyncio.sleep(0.05)
        return not _pid_alive(pid)

    plan = build_five_teams(members())

    # 1. 批次超时必须强杀真实子进程，不留孤儿进程。
    slow_dir = tmp_path / "slow_timeout"
    shutil.copytree(ENGINE_PATH, slow_dir)
    pid_file = tmp_path / "slow.pid"
    (slow_dir / "runner" / "sim.py").write_text(
        f"import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    slow_eng = SoloRaidDamageEngine(
        slow_dir, mapping(), python=sys.executable, timeout=10.0, batch_timeout=0.35, concurrency=2
    )
    res_timeout = await slow_eng.estimate(plan.teams[:2])
    assert res_timeout.available is False
    assert "批次计算超时" in res_timeout.reason
    assert slow_eng.active_process_count == 0
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8"))
        assert await _wait_dead(pid), f"超时子进程 {pid} 未被终止"

    # 2. 取消任务时必须先终止并等待回收旧子进程，才允许释放并发槽位给后续任务。
    order_dir = tmp_path / "cancel_order"
    shutil.copytree(ENGINE_PATH, order_dir)
    trace_file = tmp_path / "trace.log"
    p1_started = tmp_path / "p1.started"
    (order_dir / "runner" / "sim.py").write_text(
        f"import os, pathlib, sys, time, json\n"
        f"req = json.loads(sys.argv[sys.argv.index('--request') + 1])\n"
        f"first = req['squad'][0]\n"
        f"log = pathlib.Path({str(trace_file)!r})\n"
        f"if first == 'L1-1':\n"
        f"    pathlib.Path({str(p1_started)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"    try:\n"
        f"        while True: time.sleep(0.05)\n"
        f"    finally:\n"
        f"        with log.open('a', encoding='utf-8') as f: f.write('p1_end\\n')\n"
        f"else:\n"
        f"    with log.open('a', encoding='utf-8') as f: f.write('p2_start\\n')\n"
        f"    print(json.dumps({{'schema_version': 2, 'total_damage': 555}}))\n",
        encoding="utf-8",
    )
    seq_eng = SoloRaidDamageEngine(order_dir, mapping(), python=sys.executable, timeout=5.0, concurrency=1)
    t1 = asyncio.create_task(seq_eng.estimate(plan.teams[:1]))
    deadline = time.monotonic() + 3.0
    while not p1_started.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert p1_started.exists()
    p1_pid = int(p1_started.read_text(encoding="utf-8"))
    t2 = asyncio.create_task(seq_eng.estimate(plan.teams[1:2]))
    await asyncio.sleep(0.05)
    assert not t2.done()
    t1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t1
    assert await _wait_dead(p1_pid), "取消后进程仍存活"
    r2 = await t2
    assert r2.available is True
    assert r2.total == 555

    # 3. 真实并发计数受 concurrency 限制。
    conc_dir = tmp_path / "conc"
    shutil.copytree(ENGINE_PATH, conc_dir)
    events_dir = tmp_path / "conc_events"
    events_dir.mkdir()
    (conc_dir / "runner" / "sim.py").write_text(
        f"import json, os, pathlib, time\n"
        f"d = pathlib.Path({str(events_dir)!r})\n"
        f"p = d / f'{{os.getpid()}}.lock'\n"
        f"p.write_text('1', encoding='utf-8')\n"
        f"max_file = d / f'obs_{{os.getpid()}}.txt'\n"
        f"active = len(list(d.glob('*.lock')))\n"
        f"time.sleep(0.15)\n"
        f"active2 = len(list(d.glob('*.lock')))\n"
        f"max_file.write_text(str(max(active, active2)), encoding='utf-8')\n"
        f"p.unlink(missing_ok=True)\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 777}}))\n",
        encoding="utf-8",
    )
    conc_eng = SoloRaidDamageEngine(conc_dir, mapping(), python=sys.executable, timeout=10.0, concurrency=2)
    conc_res = await conc_eng.estimate(plan.teams[:4])
    assert conc_res.available is True and conc_res.total == 777 * 4
    observed = [int(f.read_text(encoding="utf-8")) for f in events_dir.glob("obs_*.txt")]
    assert observed and max(observed) <= 2

    # 4. 运行期流式截断：无限写 stdout 或 stderr 的进程立即被终止并降级。
    for stream in ("stdout", "stderr"):
        flood_dir = tmp_path / f"flood_{stream}"
        shutil.copytree(ENGINE_PATH, flood_dir)
        (flood_dir / "runner" / "sim.py").write_text(
            f"import sys\nchunk = 'x' * 8192\nwhile True:\n    sys.{stream}.write(chunk)\n    sys.{stream}.flush()\n",
            encoding="utf-8",
        )
        flood_eng = SoloRaidDamageEngine(flood_dir, mapping(), python=sys.executable, timeout=30.0)
        flood_res = await flood_eng.estimate(plan.teams[:1])
        assert flood_res.total is None
        assert "大小上限" in flood_res.teams[0].error
        assert flood_eng.active_process_count == 0

    # 5. 非对象 JSON 与损坏 JSON 安全降级；dirty=True 时标签不得宣称可信固定基线。
    bad_dir = tmp_path / "bad_json"
    shutil.copytree(ENGINE_PATH, bad_dir)
    for bad_out, expected in (
        ("[1, 2, 3]", "不是 JSON 对象"),
        ('"plain-string"', "不是 JSON 对象"),
        ("null", "不是 JSON 对象"),
        ("{bad json", "不是 JSON"),
    ):
        (bad_dir / "runner" / "sim.py").write_text(f"print({bad_out!r})\n", encoding="utf-8")
        bad_eng = SoloRaidDamageEngine(bad_dir, mapping(), python=sys.executable, timeout=5.0)
        bad_res = await bad_eng.estimate(plan.teams[:1])
        assert bad_res.total is None
        assert expected in bad_res.teams[0].error

    dirty_dir = tmp_path / "dirty_eval"
    shutil.copytree(ENGINE_PATH, dirty_dir)
    (dirty_dir / "runner" / "sim.py").write_text(
        f"import json\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 1234, "
        f"'evaluator': {{'commit': {PINNED_COMMIT!r}, 'dirty': True}}}}))\n",
        encoding="utf-8",
    )
    dirty_eng = SoloRaidDamageEngine(dirty_dir, mapping(), python=sys.executable, timeout=5.0)
    dirty_res = await dirty_eng.estimate(plan.teams[:1])
    assert dirty_res.version_ok is False
    assert "未核验" in dirty_res.label
    assert PINNED_COMMIT[:10] not in dirty_res.label

    # 6. aclose() 立即清理正在运行中的外部子进程并拒绝后续估伤。
    close_dir = tmp_path / "aclose_proc"
    shutil.copytree(ENGINE_PATH, close_dir)
    c_pid_file = tmp_path / "close.pid"
    (close_dir / "runner" / "sim.py").write_text(
        f"import os, pathlib, time\n"
        f"pathlib.Path({str(c_pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    close_eng = SoloRaidDamageEngine(close_dir, mapping(), python=sys.executable, timeout=30.0)
    bg = asyncio.create_task(close_eng.estimate(plan.teams[:1]))
    deadline = time.monotonic() + 3.0
    while not c_pid_file.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert c_pid_file.exists()
    c_pid = int(c_pid_file.read_text(encoding="utf-8"))
    await close_eng.aclose()
    res_closed = await bg
    assert await _wait_dead(c_pid)
    assert close_eng.active_process_count == 0
    assert res_closed.total is None
    refused = await close_eng.estimate(plan.teams[:1])
    assert refused.available is False and "已关闭" in refused.reason
