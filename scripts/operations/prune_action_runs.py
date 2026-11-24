# SPDX-License-Identifier: GPL-3.0-or-later
"""离线保留清理已完结的 action_runs 历史；默认只生成计划，不修改数据库。

安全边界（REFACTOR_PLAN_V2 §2 红线 4/5，PR-6B G7-f2）：
- 只处理白名单 action 与其终态状态，且 run_key 必须完整匹配当前格式；
- 绝不删除未决（DISPATCH_INTENT/DISPATCHED/UNKNOWN_AFTER_ACTION 及旧版小写
  running/unknown）、ACKNOWLEDGED_UNKNOWN、执行租约、永久幂等守卫
  （cdk/session_renewal/session_renewal_window/community_reward）、precheck_* 与
  pending 记录，也不删除任何旧格式或无法解析的运行键；
- 同一账号作用域与周期内只要存在受保护记录，该周期的终态记录也全部保留，
  便于人工核实时保留上下文；
- 运行键中嵌入的 UTC 周期日期是主要年龄门槛，created_at 只是辅助门槛
  （transition_run(refresh_created_at=True) 会刷新它）；
- 计划阶段以 SQLite ``mode=ro`` 只读打开；``--apply`` 须在插件停止、完成
  upgrade_preflight 与 backup_nikke_data 成对备份后执行，并在单个
  BEGIN IMMEDIATE 事务中按 (run_key, status, created_at) 条件删除，状态在计划与
  应用之间变化的记录会被跳过；
- 输出只包含按 action/status 汇总的计数，不输出 run_key、qq_id 或 detail。

本工具不修改 core/storage.py，也不引入 NikkeStore 删除接口。
"""

from __future__ import annotations

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))


import argparse
import json
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 7
DATABASE_NAME = "nikke.sqlite3"

# 任何 action 下都不删除的状态：未决、人工核实、预检可重试与旧版小写未决。
PROTECTED_STATUSES = frozenset({
    "DISPATCH_INTENT",
    "DISPATCHED",
    "UNKNOWN_AFTER_ACTION",
    "ACKNOWLEDGED_UNKNOWN",
    "running",
    "unknown",
    "pending",
    "precheck_expired",
    "precheck_failed",
})
# 整个 action 都不参与保留清理：执行租约与永久幂等守卫。
PROTECTED_ACTIONS = frozenset({
    "community_account_lease",
    "cdk",
    "session_renewal",
    "session_renewal_window",
    "community_reward",
})

_DAY = r"(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})"
_D24 = r"(?P<scope>[0-9a-f]{24})"
_D64 = r"(?P<scope>[0-9a-f]{64})"


@dataclass(frozen=True)
class RetentionRule:
    """一个可清理 action 的当前格式运行键与终态白名单。"""

    action: str
    pattern: re.Pattern[str]
    terminal_statuses: frozenset[str]


RULES: dict[str, RetentionRule] = {
    rule.action: rule
    for rule in (
        # features/daily/runner.py DailyRunner.daily_run_key（UTC 社区日）
        RetentionRule(
            "daily",
            re.compile(rf"community-utc:{_DAY}:game:{_D24}:daily"),
            frozenset({"success", "failed", "expired", "unavailable"}),
        ),
        RetentionRule(
            "signin",
            re.compile(rf"community-utc:{_DAY}:game:{_D24}:signin"),
            frozenset({"success", "failed", "expired", "unavailable"}),
        ),
        # application/commands/daily.py 私聊异常通知
        RetentionRule(
            "daily_notice",
            re.compile(rf"{_DAY}:game:{_D24}:notice:[a-z_]+"),
            frozenset({"success", "failed"}),
        ),
        # features/daily/actions.py 社区周期动作
        RetentionRule(
            "community_action",
            re.compile(
                rf"community-actions:v1:{_D64}:community-utc:{_DAY}:[a-z_]+:[0-9a-f]{{64}}"
            ),
            frozenset({"VERIFIED", "NOT_SENT"}),
        ),
        # application/commands/community_automation.py 私聊异常通知
        RetentionRule(
            "community_automation_notice",
            re.compile(rf"community-automation-notice:v1:{_D64}:{_DAY}:[a-z_]+"),
            frozenset({"SENT", "FAILED"}),
        ),
    )
}


@dataclass(frozen=True)
class PruneCandidate:
    run_key: str
    action: str
    status: str
    created_at: int


@dataclass(frozen=True)
class PrunePlan:
    database: Path
    retention_days: int
    cutoff_day: str
    candidates: tuple[PruneCandidate, ...]
    kept: dict[str, int]

    def as_dict(self) -> dict:
        counts = Counter(f"{item.action}:{item.status}" for item in self.candidates)
        return {
            "mode": "PLAN",
            "retention_days": self.retention_days,
            "cutoff_day": self.cutoff_day,
            "candidate_count": len(self.candidates),
            "candidates_by_action_status": dict(sorted(counts.items())),
            "kept_by_reason": dict(sorted(self.kept.items())),
        }


def _contains_symlink_component(path: Path) -> bool:
    candidate = path if path.is_absolute() else Path.cwd() / path
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current /= component
        if current.is_symlink():
            return True
    return False


def _database_path(data_dir: str | Path) -> Path:
    root = Path(data_dir).expanduser()
    database = root / DATABASE_NAME
    if _contains_symlink_component(database) or not root.is_dir() or not database.is_file():
        raise ValueError("数据目录或数据库不是普通路径")
    return database


def _retention_days(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("保留天数必须是整数")
    if value < MIN_RETENTION_DAYS:
        raise ValueError(f"保留天数不得少于 {MIN_RETENTION_DAYS} 天")
    return value


def _classify(row: sqlite3.Row, cutoff: date, created_cutoff: int) -> tuple[str, PruneCandidate | None, str | None]:
    """返回 (保留原因或空, 候选, 作用域周期键)。"""
    action = str(row["action"])
    status = str(row["status"])
    run_key = str(row["run_key"])
    if action in PROTECTED_ACTIONS:
        return "protected_action", None, None
    rule = RULES.get(action)
    match = rule.pattern.fullmatch(run_key) if rule is not None else None
    group = None
    if match is not None:
        scope = match.groupdict().get("scope") or ""
        # 同一账号作用域同一周期（跨 daily/signin 等动作）共享人工核实上下文。
        group = f"{scope}:{match.group('day')}"
    if status in PROTECTED_STATUSES:
        return "protected_status", None, group
    if rule is None:
        return "unlisted_action", None, None
    if match is None:
        return "unrecognized_key", None, None
    if status not in rule.terminal_statuses:
        return "non_terminal_status", None, group
    try:
        period = date.fromisoformat(match.group("day"))
    except ValueError:
        return "unrecognized_key", None, None
    created_at = row["created_at"]
    if isinstance(created_at, bool) or not isinstance(created_at, int):
        return "unrecognized_key", None, None
    if period >= cutoff or created_at >= created_cutoff:
        return "within_retention", None, group
    return "", PruneCandidate(run_key, action, status, created_at), group


def build_prune_plan(
    data_dir: str | Path,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: float | None = None,
) -> PrunePlan:
    """以只读连接扫描 action_runs，返回保守的保留清理计划。"""
    days = _retention_days(retention_days)
    database = _database_path(data_dir)
    current = time.time() if now is None else float(now)
    today = datetime.fromtimestamp(current, timezone.utc).date()
    cutoff = today - timedelta(days=days)
    created_cutoff = int(current) - days * 86400
    uri = f"{database.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT run_key, action, status, created_at FROM action_runs"
        ).fetchall()
    kept: Counter[str] = Counter()
    eligible: list[tuple[PruneCandidate, str | None]] = []
    blocked_groups: set[str] = set()
    for row in rows:
        reason, candidate, group = _classify(row, cutoff, created_cutoff)
        if candidate is not None:
            eligible.append((candidate, group))
            continue
        kept[reason] += 1
        if reason in {"protected_status", "non_terminal_status"} and group is not None:
            blocked_groups.add(group)
    candidates: list[PruneCandidate] = []
    for candidate, group in eligible:
        if group is not None and group in blocked_groups:
            kept["protected_period_context"] += 1
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: (item.action, item.created_at, item.run_key))
    return PrunePlan(database, days, cutoff.isoformat(), tuple(candidates), dict(kept))


def apply_prune(plan: PrunePlan) -> dict:
    """在单个 IMMEDIATE 事务中按计划条件删除；状态或时间已变化的记录跳过。"""
    database = plan.database
    if _contains_symlink_component(database) or not database.is_file():
        raise ValueError("数据库不是普通路径")
    removed: Counter[str] = Counter()
    skipped = 0
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for item in plan.candidates:
                rule = RULES.get(item.action)
                if (
                    item.action in PROTECTED_ACTIONS
                    or item.status in PROTECTED_STATUSES
                    or rule is None
                    or item.status not in rule.terminal_statuses
                    or rule.pattern.fullmatch(item.run_key) is None
                ):
                    skipped += 1
                    continue
                cursor = connection.execute(
                    "DELETE FROM action_runs WHERE run_key=? AND action=? AND status=? AND created_at=?",
                    (item.run_key, item.action, item.status, item.created_at),
                )
                if cursor.rowcount == 1:
                    removed[f"{item.action}:{item.status}"] += 1
                else:
                    skipped += 1
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    finally:
        connection.close()
    return {
        "mode": "APPLY",
        "retention_days": plan.retention_days,
        "cutoff_day": plan.cutoff_day,
        "planned_count": len(plan.candidates),
        "removed_count": sum(removed.values()),
        "removed_by_action_status": dict(sorted(removed.items())),
        "skipped_changed_or_protected": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True, help="AstrBot 的 data/nikke 目录")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"保留最近 N 天（默认 {DEFAULT_RETENTION_DAYS}，最少 {MIN_RETENTION_DAYS}）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="插件停止并完成成对备份后才删除计划内记录；默认只预览",
    )
    args = parser.parse_args()
    try:
        plan = build_prune_plan(args.data_dir, retention_days=args.older_than_days)
        result = apply_prune(plan) if args.apply else plan.as_dict()
    except (ValueError, sqlite3.Error) as exc:
        parser.error(f"{type(exc).__name__}: {exc}" if isinstance(exc, sqlite3.Error) else str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
