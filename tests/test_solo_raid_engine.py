# SPDX-License-Identifier: GPL-3.0-or-later
"""22 外部 MIT 估伤引擎：JSON 合同、Git 版本可信度、进程树生命周期与故障注入（合成+真实子进程）。"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from astrbot_plugin_nikke.features.solo_raid.builder import Member, Team, build_five_teams
from astrbot_plugin_nikke.integrations.nikke_calc.engine import (
    ENGINE_REPO,
    MAX_OUTPUT_BYTES,
    PINNED_COMMIT,
    VERSION_TRUST_GIT_PINNED,
    VERSION_TRUST_MISMATCH_OR_DIRTY,
    VERSION_TRUST_SELF_REPORTED,
    VERSION_TRUST_UNVERIFIED,
    EngineNameMappingError,
    SoloRaidDamageEngine,
    load_name_mapping,
    load_name_mapping_with_meta,
)

ENGINE_PATH = Path(__file__).resolve().parent / "fixtures" / "fake_nikke_calc"


def _os_pid_alive(pid: int) -> bool:
    """直接询问操作系统 PID 是否仍处于存活态。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint32(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return int(code.value) == 259  # STILL_ACTIVE
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
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.is_file():
        try:
            raw = stat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        rparen = raw.rfind(")")
        if rparen >= 0:
            after = raw[rparen + 2 :].split()
            if after and after[0] in {"Z", "X", "x"}:
                return False
    return True


async def _wait_pids_dead(pids: list[int], limit: float = 5.0) -> list[int]:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _os_pid_alive(pid)]
        if not alive:
            return []
        await asyncio.sleep(0.05)
    return [pid for pid in pids if _os_pid_alive(pid)]


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


def engine_with_mapping(values: dict[str, str]) -> SoloRaidDamageEngine:
    return SoloRaidDamageEngine(
        ENGINE_PATH,
        values,
        python=sys.executable,
        timeout=30,
        work_dir=Path("output") / ".engine-runs",
    )


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "-C", str(repo_dir), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Tester"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-m", "init"], check=True, capture_output=True)


@pytest.mark.asyncio
async def test_engine_returns_per_team_and_total_with_self_reported_distinction() -> None:
    """无 .git 目录时，自报固定 SHA 也绝对不能被视为可信固定基线（P2-01）。"""
    plan = build_five_teams(members())
    result = await engine().estimate(plan.teams, boss_element="风压")

    assert result.available is True
    assert result.total is not None
    assert len(result.teams) == 5
    assert all(item.damage is not None and item.damage > 0 for item in result.teams)
    assert result.commit == PINNED_COMMIT
    assert result.dirty is False
    assert result.version_trust == VERSION_TRUST_SELF_REPORTED
    assert result.version_ok is False
    assert "自报" in result.label
    assert "不适合可信基线对比" in result.note
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
    assert first_team_code


def test_name_mapping_requires_mit_engine_provenance() -> None:
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
        loaded, commit = load_name_mapping_with_meta(path)
        assert loaded == {"L1": "L1"}
        assert commit == PINNED_COMMIT
        assert load_name_mapping(path) == {"L1": "L1"}
        payload["engine_commit"] = "short"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(EngineNameMappingError, match="40 位"):
            load_name_mapping(path)
    finally:
        path.unlink(missing_ok=True)


def test_real_engine_name_mapping_uses_stable_resource_and_name_codes() -> None:
    path = Path(__file__).resolve().parents[1] / "assets" / "data" / "solo_raid_engine_names.json"
    loaded, commit = load_name_mapping_with_meta(path)
    assert commit == PINNED_COMMIT
    assert loaded["10"] == "라피"
    assert loaded["3001"] == "라피"
    assert loaded["Rapi"] == "라피"
    assert len(loaded) > 800
    assert "not-a-real-nikke" not in loaded


@pytest.mark.asyncio
async def test_engine_version_trust_states_git_mismatch_dirty_and_mapping_commit(tmp_path: Path, monkeypatch) -> None:
    plan = build_five_teams(members())

    # 1. 无 evaluator commit 时为 unverified。
    no_eval = tmp_path / "no_eval"
    shutil.copytree(ENGINE_PATH, no_eval)
    (no_eval / "runner" / "sim.py").write_text(
        "import json, os\n"
        "assert 'NIKKE_TEST_SECRET' not in os.environ\n"
        "print(json.dumps({'schema_version': 2, 'total_damage': 12345}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NIKKE_TEST_SECRET", "top-secret-token")
    res = await SoloRaidDamageEngine(no_eval, mapping(), python=sys.executable, timeout=10).estimate(plan.teams[:1])
    assert res.available is True
    assert res.version_trust == VERSION_TRUST_UNVERIFIED
    assert res.version_ok is False
    assert PINNED_COMMIT[:10] not in res.label

    # 2. require_git=True 且无 .git 时直接拒绝。
    req_git_eng = SoloRaidDamageEngine(no_eval, mapping(), python=sys.executable, timeout=10, require_git=True)
    req_res = await req_git_eng.estimate(plan.teams[:1])
    assert req_res.available is False
    assert req_res.version_ok is False
    assert "缺少独立 Git 仓库" in req_res.reason

    # 3. 独立 .git 非固定 commit 或 dirty 工作区：默认拒绝；allow_unverified 时标为 mismatch_or_dirty。
    git_repo = tmp_path / "git_engine"
    shutil.copytree(ENGINE_PATH, git_repo)
    _init_git_repo(git_repo)
    rejected = await SoloRaidDamageEngine(git_repo, mapping(), python=sys.executable, timeout=10, require_git=True).estimate(plan.teams[:1])
    assert rejected.available is False
    assert rejected.version_trust == VERSION_TRUST_MISMATCH_OR_DIRTY
    assert rejected.version_ok is False
    assert "版本校验失败" in rejected.reason

    untrusted_res = await SoloRaidDamageEngine(
        git_repo, mapping(), python=sys.executable, timeout=10, allow_unverified=True, require_git=True
    ).estimate(plan.teams[:1])
    assert untrusted_res.available is True
    assert untrusted_res.version_trust == VERSION_TRUST_MISMATCH_OR_DIRTY
    assert untrusted_res.version_ok is False
    assert "不适合可信基线对比" in untrusted_res.note

    # 4. Git HEAD == PINNED_COMMIT & clean，但 mapping_commit 不一致时必须拒绝（mismatch_or_dirty）。
    actual_head = subprocess.run(
        ["git", "-C", str(git_repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip().casefold()
    mismatch_res = await SoloRaidDamageEngine(
        git_repo,
        mapping(),
        python=sys.executable,
        timeout=10,
        require_git=True,
        mapping_commit="0" * 40,
        allow_unverified=True,
    ).estimate(plan.teams[:1])
    assert mismatch_res.commit == actual_head
    assert mismatch_res.version_trust == VERSION_TRUST_MISMATCH_OR_DIRTY
    assert mismatch_res.version_ok is False


@pytest.mark.asyncio
async def test_engine_process_tree_descendants_pipe_inheritance_timeouts_cancel_aclose_and_failures(tmp_path: Path) -> None:
    """P1-01 全套真实子进程验证：以真实 OS PID 证明无孤儿进程与资源泄漏。"""
    plan = build_five_teams(members())

    def _make_sim(name: str, code: str) -> Path:
        d = tmp_path / name
        shutil.copytree(ENGINE_PATH, d)
        (d / "runner" / "sim.py").write_text(code, encoding="utf-8")
        return d

    # 1 + 2: 父进程正常退出（returncode=0），但派生子进程仍存活且继承 stdout/stderr 管道！
    pipe_pids = tmp_path / "pipe_pids.txt"
    pipe_child_script = tmp_path / "pipe_child.py"
    pipe_child_script.write_text(
        f"import os, pathlib, time\n"
        f"pathlib.Path({str(pipe_pids)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    pipe_dir = _make_sim(
        "parent_exit_pipe_child",
        f"import json, subprocess, sys\n"
        f"subprocess.Popen([sys.executable, {str(pipe_child_script)!r}])\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 4321}}))\n"
        f"sys.stdout.flush()\n",
    )
    t0 = time.monotonic()
    res_pipe = await SoloRaidDamageEngine(
        pipe_dir, mapping(), python=sys.executable, timeout=10.0, pipe_drain_timeout=0.15
    ).estimate(plan.teams[:1])
    elapsed = time.monotonic() - t0
    assert elapsed < 4.0, f"继承 stdout/stderr 的派生进程阻塞了等待：{elapsed:.2f}s"
    assert res_pipe.available is True
    assert res_pipe.total == 4321
    assert pipe_pids.exists()
    descendant_pid = int(pipe_pids.read_text(encoding="utf-8").strip())
    assert await _wait_pids_dead([descendant_pid]) == []

    # 3: 三级派生进程树（parent -> child -> grandchild），且孙进程脱离 stdio 继续驻留。
    tree_pids = tmp_path / "tree_pids.log"
    grand_script = tmp_path / "tree_grand.py"
    grand_script.write_text(
        f"import os, pathlib, time\n"
        f"pathlib.Path({str(tree_pids)!r}).open('a', encoding='utf-8').write(f'grand={{os.getpid()}}\\n')\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    child_script = tmp_path / "tree_child.py"
    child_script.write_text(
        f"import os, pathlib, subprocess, sys, time\n"
        f"pathlib.Path({str(tree_pids)!r}).open('a', encoding='utf-8').write(f'child={{os.getpid()}}\\n')\n"
        f"subprocess.Popen([sys.executable, {str(grand_script)!r}], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    tree_dir = _make_sim(
        "three_level_tree",
        f"import json, os, pathlib, subprocess, sys, time\n"
        f"pathlib.Path({str(tree_pids)!r}).write_text(f'parent={{os.getpid()}}\\n', encoding='utf-8')\n"
        f"subprocess.Popen([sys.executable, {str(child_script)!r}], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"time.sleep(0.4)\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 8888}}))\n",
    )
    res_tree = await SoloRaidDamageEngine(tree_dir, mapping(), python=sys.executable, timeout=10.0).estimate(plan.teams[:1])
    assert res_tree.total == 8888
    raw_lines = tree_pids.read_text(encoding="utf-8").splitlines()
    observed_pids = [int(line.split("=", 1)[1]) for line in raw_lines if "=" in line]
    assert len(observed_pids) == 3, f"未观测到三级进程树: {raw_lines}"
    assert await _wait_pids_dead(observed_pids) == []

    # 4: 批次超时（带派生子进程）。
    batch_pids = tmp_path / "batch_pids.log"
    batch_child = tmp_path / "batch_child.py"
    batch_child.write_text(
        f"import os, pathlib, time\n"
        f"pathlib.Path({str(batch_pids)!r}).open('a', encoding='utf-8').write(f'{{os.getpid()}}\\n')\n"
        f"time.sleep(30)\n",
        encoding="utf-8",
    )
    batch_dir = _make_sim(
        "batch_timeout_tree",
        f"import os, pathlib, subprocess, sys, time\n"
        f"pathlib.Path({str(batch_pids)!r}).open('a', encoding='utf-8').write(f'{{os.getpid()}}\\n')\n"
        f"subprocess.Popen([sys.executable, {str(batch_child)!r}], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"time.sleep(30)\n",
    )
    batch_eng = SoloRaidDamageEngine(batch_dir, mapping(), python=sys.executable, timeout=10.0, batch_timeout=0.45, concurrency=2)
    res_batch = await batch_eng.estimate(plan.teams[:2])
    assert res_batch.available is False and "批次计算超时" in res_batch.reason
    b_pids = [int(x) for x in batch_pids.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(b_pids) >= 2
    assert await _wait_pids_dead(b_pids) == []

    # 5: 单队超时（其余队伍正常完成）。
    single_pids = tmp_path / "single_pid.txt"
    single_dir = _make_sim(
        "single_timeout",
        f"import json, os, pathlib, sys, time\n"
        f"req = json.loads(sys.argv[sys.argv.index('--request') + 1])\n"
        f"if req['squad'][0] == 'L1-1':\n"
        f"    pathlib.Path({str(single_pids)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"    time.sleep(30)\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 1111}}))\n",
    )
    res_single = await SoloRaidDamageEngine(single_dir, mapping(), python=sys.executable, timeout=0.35, batch_timeout=5.0, concurrency=2).estimate(plan.teams[:2])
    assert res_single.available is True
    assert res_single.total is None
    assert "引擎计算超时" in res_single.teams[0].error
    assert res_single.teams[1].damage == 1111
    s_pid = int(single_pids.read_text(encoding="utf-8").strip())
    assert await _wait_pids_dead([s_pid]) == []

    # 6: 连续多次取消任务，仍必须等旧进程树彻底死亡才允许下一队进入信号量。
    cancel_log = tmp_path / "cancel_order.log"
    p1_started = tmp_path / "p1_started.txt"
    cancel_dir = _make_sim(
        "repeated_cancel",
        f"import json, os, pathlib, sys, time\n"
        f"req = json.loads(sys.argv[sys.argv.index('--request') + 1])\n"
        f"if req['squad'][0] == 'L1-1':\n"
        f"    pathlib.Path({str(p1_started)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        f"    time.sleep(30)\n"
        f"pathlib.Path({str(cancel_log)!r}).write_text('p2_ran', encoding='utf-8')\n"
        f"print(json.dumps({{'schema_version': 2, 'total_damage': 2222}}))\n",
    )
    seq_eng = SoloRaidDamageEngine(cancel_dir, mapping(), python=sys.executable, timeout=10.0, concurrency=1)
    t1 = asyncio.create_task(seq_eng.estimate(plan.teams[:1]))
    deadline = time.monotonic() + 3.0
    while not p1_started.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert p1_started.exists()
    p1_pid = int(p1_started.read_text(encoding="utf-8").strip())
    t2 = asyncio.create_task(seq_eng.estimate(plan.teams[1:2]))
    await asyncio.sleep(0.05)
    assert not cancel_log.exists()
    # 连续两次取消 t1。
    t1.cancel()
    await asyncio.sleep(0.01)
    t1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t1
    assert await _wait_pids_dead([p1_pid]) == []
    assert (await t2).total == 2222

    # 7: aclose() 与进程创建并发竞态。
    race_pids = tmp_path / "race_pids.txt"
    race_dir = _make_sim(
        "aclose_race",
        f"import json, os, pathlib, time\n"
        f"pathlib.Path({str(race_pids)!r}).open('a', encoding='utf-8').write(f'{{os.getpid()}}\\n')\n"
        f"time.sleep(30)\n",
    )
    race_eng = SoloRaidDamageEngine(race_dir, mapping(), python=sys.executable, timeout=10.0, concurrency=2)
    t_race = asyncio.create_task(race_eng.estimate(plan.teams[:2]))
    await asyncio.sleep(0.02)
    await race_eng.aclose()
    res_race = await t_race
    assert res_race.total is None
    if race_pids.exists():
        r_pids = [int(x) for x in race_pids.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert await _wait_pids_dead(r_pids) == []
    refused = await race_eng.estimate(plan.teams[:1])
    assert refused.available is False and "已关闭" in refused.reason

    # 8: stdout / stderr 超过 MAX_OUTPUT_BYTES 立即终止进程并释放资源。
    for stream in ("stdout", "stderr"):
        flood_pid_file = tmp_path / f"flood_{stream}.pid"
        flood_dir = _make_sim(
            f"flood_{stream}",
            f"import os, pathlib, sys\n"
            f"pathlib.Path({str(flood_pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
            f"chunk = 'x' * 8192\n"
            f"while True:\n"
            f"    sys.{stream}.write(chunk)\n"
            f"    sys.{stream}.flush()\n",
        )
        res_flood = await SoloRaidDamageEngine(flood_dir, mapping(), python=sys.executable, timeout=20.0).estimate(plan.teams[:1])
        assert res_flood.total is None and "大小上限" in res_flood.teams[0].error
        f_pid = int(flood_pid_file.read_text(encoding="utf-8").strip())
        assert await _wait_pids_dead([f_pid]) == []

    # 9: 清理失败时必须有明确可观察状态（cleanup_failures + team/note 错误），禁止静默成功。
    from astrbot_plugin_nikke.integrations.nikke_calc.engine import _kill_managed_tree_sync

    def failing_killer(pid, pgid, job_handle, timeout):
        _kill_managed_tree_sync(pid, pgid, job_handle, timeout)
        return False, f"模拟进程组 {pgid} 清理拒绝访问"

    fail_eng = SoloRaidDamageEngine(
        ENGINE_PATH, mapping(), python=sys.executable, timeout=10.0, _tree_killer=failing_killer
    )
    res_fail = await fail_eng.estimate(plan.teams[:1])
    assert res_fail.cleanup_failures
    assert "模拟进程组" in res_fail.cleanup_failures[0]
    assert res_fail.total is None
    assert "进程树清理异常" in res_fail.teams[0].error
    assert fail_eng.cleanup_failures


@pytest.mark.asyncio
async def test_engine_resolves_resource_id_and_electronic_element() -> None:
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
async def test_engine_cleanup_idempotency_early_returns_collector_and_slot_hold(tmp_path: Path) -> None:
    """收尾回归：并发清理幂等、提前返回不丢 cleanup_error、collector 回收与失败不放行并发槽位。"""
    plan = build_five_teams(members())

    def _make_sim(name: str, code: str) -> Path:
        d = tmp_path / name
        shutil.copytree(ENGINE_PATH, d)
        (d / "runner" / "sim.py").write_text(code, encoding="utf-8")
        return d

    # 1: TimeoutError 提前返回必须保留 cleanup_error，且并发 aclose() 与 finally 只执行一次强杀。
    slow_dir = _make_sim(
        "timeout_and_concurrent_cleanup",
        "import time\ntime.sleep(30)\n",
    )
    killer_calls = {"count": 0, "allow_ok": False}

    def slow_killer(pid: int, pgid: int, job_handle: int | None, timeout: float) -> tuple[bool, str]:
        from astrbot_plugin_nikke.integrations.nikke_calc.engine import _kill_managed_tree_sync

        killer_calls["count"] += 1
        time.sleep(0.08)
        _kill_managed_tree_sync(pid, pgid, job_handle, timeout)
        if not killer_calls["allow_ok"]:
            return False, f"PID {pid} 暂时拒绝清理"
        return True, ""

    eng_timeout = SoloRaidDamageEngine(
        slow_dir,
        mapping(),
        python=sys.executable,
        timeout=0.2,
        batch_timeout=5.0,
        concurrency=1,
        _tree_killer=slow_killer,
    )
    res_timeout = await eng_timeout.estimate(plan.teams[:1])
    assert res_timeout.teams[0].error
    assert "引擎计算超时" in res_timeout.teams[0].error
    assert "暂时拒绝清理" in res_timeout.teams[0].cleanup_error
    assert "暂时拒绝清理" in res_timeout.teams[0].error
    assert res_timeout.cleanup_failures
    # 清理失败时不得悄悄清零追踪句柄，且并发槽位仍被占用直到重试成功。
    assert eng_timeout.active_process_count == 1
    assert eng_timeout.leaked_process_count == 1
    assert eng_timeout._semaphore().locked() is True
    # 恢复可清理条件并显式 aclose() 重试，应当回收追踪状态并释放并发槽位。
    killer_calls["allow_ok"] = True
    await eng_timeout.aclose()
    assert eng_timeout.active_process_count == 0
    assert eng_timeout.leaked_process_count == 0
    assert eng_timeout._semaphore().locked() is False

    # 2: OutputLimitExceeded 提前返回同样必须保留 cleanup_error。
    flood_dir = _make_sim(
        "flood_cleanup_err",
        "import sys\nchunk = 'y' * 8192\nwhile True:\n    sys.stdout.write(chunk)\n    sys.stdout.flush()\n",
    )
    eng_flood = SoloRaidDamageEngine(
        flood_dir,
        mapping(),
        python=sys.executable,
        timeout=10.0,
        _tree_killer=lambda pid, pgid, jh, to: (_kill_managed_tree_sync(pid, pgid, jh, to), "输出超限后清理失败")[1]
        and (False, "输出超限后清理失败"),
    )
    # Use clean helper preserving real kill before returning failure
    from astrbot_plugin_nikke.integrations.nikke_calc.engine import _kill_managed_tree_sync

    def flood_fail_killer(pid: int, pgid: int, job_handle: int | None, timeout: float) -> tuple[bool, str]:
        _kill_managed_tree_sync(pid, pgid, job_handle, timeout)
        return False, "输出超限后清理失败"

    eng_flood._tree_killer = flood_fail_killer
    res_flood = await eng_flood.estimate(plan.teams[:1])
    assert "引擎输出超过大小上限" in res_flood.teams[0].error
    assert "输出超限后清理失败" in res_flood.teams[0].cleanup_error
    assert "输出超限后清理失败" in res_flood.teams[0].error

    # 3: 同一 _ManagedProcess 被 aclose() 与任务 finally 并发调用 _cleanup_managed 时必须共享清理任务。
    conc_calls = {"count": 0}

    def slow_ok_killer(pid: int, pgid: int, job_handle: int | None, timeout: float) -> tuple[bool, str]:
        conc_calls["count"] += 1
        time.sleep(0.12)
        return _kill_managed_tree_sync(pid, pgid, job_handle, timeout)

    eng_conc = SoloRaidDamageEngine(
        slow_dir, mapping(), python=sys.executable, timeout=10.0, concurrency=1, _tree_killer=slow_ok_killer
    )
    task = asyncio.create_task(eng_conc.estimate(plan.teams[:1]))
    deadline = time.monotonic() + 3.0
    while eng_conc.active_process_count == 0 and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert eng_conc.active_process_count == 1
    handle = next(iter(eng_conc._active_handles))
    r_close, r_direct = await asyncio.gather(
        eng_conc.aclose(),
        eng_conc._cleanup_managed(handle),
    )
    await task
    assert r_direct == ""
    assert conc_calls["count"] == 1
    assert eng_conc.active_process_count == 0
    assert eng_conc.leaked_process_count == 0
