# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-6B G7-misc-dead-f2：action_runs 离线保留清理只删除过期的已完结白名单记录。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.scripts.operations.prune_action_runs import (
    MIN_RETENTION_DAYS,
    apply_prune,
    build_prune_plan,
)

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
OLD_DAY = (NOW - timedelta(days=60)).date().isoformat()
RECENT_DAY = (NOW - timedelta(days=3)).date().isoformat()
D24 = hashlib.sha256(b"global:81:1001").hexdigest()[:24]
OTHER24 = hashlib.sha256(b"global:81:2002").hexdigest()[:24]
SCOPE64 = hashlib.sha256(b"blablalink-community:openid-1").hexdigest()
POST64 = hashlib.sha256(b"post-1").hexdigest()


def _seed(data_dir: Path, rows: list[tuple[str, str, str, int]]) -> None:
    store = NikkeStore(data_dir)
    for run_key, action, status, _ in rows:
        assert store.claim_run(run_key, "10001", action, initial_status="DISPATCH_INTENT")
        store.finish_run(run_key, status, "detail")
    with sqlite3.connect(data_dir / "nikke.sqlite3") as conn:
        for run_key, _, _, created_at in rows:
            conn.execute("UPDATE action_runs SET created_at=? WHERE run_key=?", (created_at, run_key))


def _keys(data_dir: Path) -> set[str]:
    with sqlite3.connect(data_dir / "nikke.sqlite3") as conn:
        return {row[0] for row in conn.execute("SELECT run_key FROM action_runs")}


OLD_TS = int((NOW - timedelta(days=60)).timestamp())
RECENT_TS = int((NOW - timedelta(days=3)).timestamp())

ELIGIBLE = [
    (f"community-utc:{OLD_DAY}:game:{D24}:daily", "daily", "success", OLD_TS),
    (f"community-utc:{OLD_DAY}:game:{D24}:signin", "signin", "failed", OLD_TS),
    (f"{OLD_DAY}:game:{D24}:notice:failed", "daily_notice", "success", OLD_TS),
    (f"community-actions:v1:{SCOPE64}:community-utc:{OLD_DAY}:like:{POST64}", "community_action", "VERIFIED", OLD_TS),
    (f"community-automation-notice:v1:{SCOPE64}:{OLD_DAY}:community_actions", "community_automation_notice", "SENT", OLD_TS),
]

PROTECTED = [
    # 未决、人工核实、预检与旧版小写状态。
    (f"community-utc:{OLD_DAY}:game:{OTHER24}:daily", "daily", "UNKNOWN_AFTER_ACTION", OLD_TS),
    (f"community-utc:{OLD_DAY}:game:{OTHER24}:signin", "signin", "precheck_failed", OLD_TS),
    (f"community-actions:v1:{SCOPE64[::-1]}:community-utc:{OLD_DAY}:share:{POST64}", "community_action", "DISPATCHED", OLD_TS),
    (f"community-actions:v1:{SCOPE64[::-1]}:community-utc:{OLD_DAY}:like:{POST64}", "community_action", "ACKNOWLEDGED_UNKNOWN", OLD_TS),
    (f"{OLD_DAY}:game:{OTHER24}:notice:pending", "daily_notice", "pending", OLD_TS),
    # 租约与永久幂等守卫。
    (f"community-account-lease:v1:{SCOPE64}", "community_account_lease", "RELEASED", OLD_TS),
    (f"cdk:game:{D24}:{POST64}", "cdk", "success", OLD_TS),
    (f"cdk:10001:1001:{POST64}", "cdk", "success", OLD_TS),
    (f"session-renewal:v1:{SCOPE64}:rev", "session_renewal", "success", OLD_TS),
    (f"session-renewal-window:v1:{SCOPE64}:{OLD_DAY}", "session_renewal_window", "DISPATCH_INTENT", OLD_TS),
    (f"community-utc:2026-01-01:game:{D24}:reward:r1", "community_reward", "success", OLD_TS),
    # 旧格式（北京时间/QQ 作用域）运行键与近期记录。
    (f"{OLD_DAY}:game:{D24}:daily", "daily", "success", OLD_TS),
    (f"{OLD_DAY}:10001:signin", "signin", "success", OLD_TS),
    (f"community-utc:{RECENT_DAY}:game:{D24}:daily", "daily", "success", RECENT_TS),
    # 周期日期已过期但 created_at 近期刷新（transition_run refresh_created_at）。
    (f"community-utc:{OLD_DAY}:game:{hashlib.sha256(b'x').hexdigest()[:24]}:signin", "signin", "success", RECENT_TS),
]


def test_plan_is_read_only_and_selects_only_expired_terminal_rows(tmp_path):
    _seed(tmp_path, ELIGIBLE + PROTECTED)
    before = (tmp_path / "nikke.sqlite3").read_bytes()
    plan = build_prune_plan(tmp_path, now=NOW.timestamp())
    assert (tmp_path / "nikke.sqlite3").read_bytes() == before
    assert {item.run_key for item in plan.candidates} == {row[0] for row in ELIGIBLE}
    report = plan.as_dict()
    assert report["mode"] == "PLAN"
    assert report["candidate_count"] == len(ELIGIBLE)
    # 输出只含聚合计数，不含运行键或账号标识。
    text = json.dumps(report, ensure_ascii=False)
    assert D24 not in text and SCOPE64 not in text and "10001" not in text


def test_apply_deletes_plan_and_keeps_every_protected_row(tmp_path):
    _seed(tmp_path, ELIGIBLE + PROTECTED)
    result = apply_prune(build_prune_plan(tmp_path, now=NOW.timestamp()))
    assert result["removed_count"] == len(ELIGIBLE)
    assert _keys(tmp_path) == {row[0] for row in PROTECTED}


def test_protected_row_keeps_same_scope_period_context(tmp_path):
    rows = [
        (f"community-utc:{OLD_DAY}:game:{D24}:daily", "daily", "success", OLD_TS),
        (f"community-utc:{OLD_DAY}:game:{D24}:signin", "signin", "UNKNOWN_AFTER_ACTION", OLD_TS),
        (f"{OLD_DAY}:game:{D24}:notice:unknown_after_action", "daily_notice", "success", OLD_TS),
    ]
    _seed(tmp_path, rows)
    plan = build_prune_plan(tmp_path, now=NOW.timestamp())
    assert plan.candidates == ()
    assert plan.kept["protected_period_context"] == 2


def test_status_change_between_plan_and_apply_is_skipped(tmp_path):
    _seed(tmp_path, ELIGIBLE)
    plan = build_prune_plan(tmp_path, now=NOW.timestamp())
    changed = ELIGIBLE[0][0]
    with sqlite3.connect(tmp_path / "nikke.sqlite3") as conn:
        conn.execute("UPDATE action_runs SET status='UNKNOWN_AFTER_ACTION' WHERE run_key=?", (changed,))
    result = apply_prune(plan)
    assert result["removed_count"] == len(ELIGIBLE) - 1
    assert result["skipped_changed_or_protected"] == 1
    assert _keys(tmp_path) == {changed}


def test_reserve_run_budget_for_current_period_is_unchanged(tmp_path):
    today = NOW.date().isoformat()
    scope = f"community-actions:v1:{SCOPE64}:community-utc:{today}:like"
    _seed(tmp_path, ELIGIBLE + [(f"{scope}:{POST64}", "community_action", "VERIFIED", int(NOW.timestamp()))])
    apply_prune(build_prune_plan(tmp_path, now=NOW.timestamp()))
    store = NikkeStore(tmp_path)
    assert not store.reserve_run(scope, f"{scope}:{'0' * 64}", "10001", "community_action", limit=1,
                                 blocking_statuses=set(), initial_status="DISPATCH_INTENT")


@pytest.mark.parametrize("days", [0, MIN_RETENTION_DAYS - 1, True, 7.5])
def test_retention_below_minimum_or_invalid_is_rejected(tmp_path, days):
    _seed(tmp_path, ELIGIBLE)
    with pytest.raises(ValueError):
        build_prune_plan(tmp_path, retention_days=days, now=NOW.timestamp())


def test_symlinked_data_dir_is_rejected(tmp_path):
    real = tmp_path / "real"
    _seed(real, ELIGIBLE)
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建目录符号链接")
    with pytest.raises(ValueError):
        build_prune_plan(link, now=NOW.timestamp())


def test_cli_defaults_to_plan_and_outputs_counts_only(tmp_path):
    _seed(tmp_path, ELIGIBLE)
    script = Path(__file__).resolve().parents[1] / "scripts" / "operations" / "prune_action_runs.py"
    result = subprocess.run([sys.executable, str(script), "--data-dir", str(tmp_path)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "PLAN"
    assert report["retention_days"] == 30
    assert len(_keys(tmp_path)) == len(ELIGIBLE)
    refused = subprocess.run([sys.executable, str(script), "--data-dir", str(tmp_path), "--older-than-days", "3"],
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert refused.returncode == 2
