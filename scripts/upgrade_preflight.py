#!/usr/bin/env python3
"""执行 NIKKE 数据升级/回滚前的只读前置检查。

本脚本只读取现有文件和 SQLite 元数据，不执行迁移、复制、删除或覆盖。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any


REQUIRED_TABLES = frozenset({"bind_sessions", "accounts", "settings", "action_runs"})
CURRENT_ACCOUNT_COLUMNS = frozenset({"xcommon_cipher", "user_agent"})
DEFAULT_MIN_FREE_BYTES = 1_073_741_824
DEFAULT_MIN_FREE_PERCENT = 10.0


def _check(status: str, reason: str) -> dict[str, str]:
    """构造不含路径、账号标识或凭据的固定格式检查结果。"""

    return {"status": status, "reason": reason}


def _ordinary_file(path: Path) -> bool:
    """只接受普通文件，避免跟随符号链接检查未知目标。"""

    return path.is_file() and not path.is_symlink()


def inspect_pair(data_dir: str | Path, label: str = "storage") -> dict[str, str]:
    """检查 SQLite 与密钥是否作为非空普通文件成对存在。"""

    root = Path(data_dir)
    database = root / "nikke.sqlite3"
    key = root / "secret.key"
    if not _ordinary_file(database) or not _ordinary_file(key):
        return _check("BLOCKED", f"{label}_pair_missing_or_non_regular")
    try:
        if key.stat().st_size <= 0:
            return _check("BLOCKED", f"{label}_key_empty")
    except OSError:
        return _check("BLOCKED", f"{label}_key_unreadable")
    return _check("PASS", f"{label}_pair_present")


def _readonly_integrity(db_path: Path) -> tuple[str, set[str]]:
    """用 SQLite mode=ro 检查完整性和表名，不产生数据库写入。"""

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    return str(integrity[0] if integrity else ""), tables


def inspect_database(db_path: str | Path) -> dict[str, str]:
    """只读检查 SQLite 完整性及当前存储合同。"""

    path = Path(db_path)
    if not _ordinary_file(path):
        return _check("BLOCKED", "database_missing_or_non_regular")
    try:
        integrity, tables = _readonly_integrity(path)
        if integrity.lower() != "ok":
            return _check("BLOCKED", "database_integrity_failed")
        if not REQUIRED_TABLES.issubset(tables):
            return _check("BLOCKED", "database_schema_unsupported")

        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(accounts)").fetchall()
            }
        if not CURRENT_ACCOUNT_COLUMNS.issubset(columns):
            return _check("MIGRATION_REQUIRED", "database_schema_migration_required")
        return _check("PASS", "database_integrity_and_schema_ok")
    except (OSError, sqlite3.DatabaseError):
        return _check("BLOCKED", "database_unreadable")


def inspect_disk_capacity(
    data_dir: str | Path,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    min_free_percent: float = DEFAULT_MIN_FREE_PERCENT,
) -> dict[str, str]:
    """检查所在文件系统余量，不在结果中暴露路径或容量细节。"""

    if min_free_bytes < 0 or not 0 <= min_free_percent <= 100:
        return _check("BLOCKED", "disk_threshold_invalid")
    try:
        usage = shutil.disk_usage(Path(data_dir))
    except OSError:
        return _check("BLOCKED", "disk_capacity_unavailable")
    if usage.total <= 0:
        return _check("BLOCKED", "disk_capacity_unavailable")
    free_percent = usage.free * 100 / usage.total
    if usage.free < min_free_bytes or free_percent < min_free_percent:
        return _check("BLOCKED", "disk_capacity_below_threshold")
    return _check("PASS", "disk_capacity_above_threshold")


def build_preflight(
    data_dir: str | Path,
    backup_dir: str | Path | None = None,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    min_free_percent: float = DEFAULT_MIN_FREE_PERCENT,
) -> dict[str, Any]:
    """汇总升级/回滚前置检查，且明确声明没有执行写入。"""

    root = Path(data_dir)
    storage_pair = inspect_pair(root, "storage")
    database = inspect_database(root / "nikke.sqlite3")

    backup_pair: dict[str, str]
    backup_database: dict[str, str]
    if backup_dir is None:
        backup_pair = _check("NOT_CHECKED", "backup_dir_not_provided")
        backup_database = _check("NOT_CHECKED", "backup_dir_not_provided")
    else:
        backup_root = Path(backup_dir)
        backup_pair = inspect_pair(backup_root, "backup")
        backup_database = inspect_database(backup_root / "nikke.sqlite3")

    disk_capacity = inspect_disk_capacity(root, min_free_bytes, min_free_percent)
    checks = {
        "storage_pair": storage_pair,
        "database": database,
        "backup_pair": backup_pair,
        "backup_database": backup_database,
        "disk_capacity": disk_capacity,
    }
    statuses = {
        check["status"]
        for check in checks.values()
        if check["status"] != "NOT_CHECKED"
    }
    if "BLOCKED" in statuses:
        overall = "BLOCKED"
    elif "MIGRATION_REQUIRED" in statuses:
        overall = "MIGRATION_REQUIRED"
    else:
        overall = "READY"
    return {"overall": overall, "writes_performed": 0, "checks": checks}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--min-free-percent", type=float, default=DEFAULT_MIN_FREE_PERCENT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = build_preflight(
        args.data_dir,
        args.backup_dir,
        args.min_free_bytes,
        args.min_free_percent,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["overall"] == "BLOCKED":
        return 1
    if result["overall"] == "MIGRATION_REQUIRED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
