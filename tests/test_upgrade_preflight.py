"""升级/回滚前置检查的离线行为测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.upgrade_preflight import build_preflight, inspect_database, main


TABLES_SQL = """
CREATE TABLE bind_sessions (token_hash TEXT PRIMARY KEY);
CREATE TABLE accounts (qq_id TEXT PRIMARY KEY, cookie_cipher BLOB NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE action_runs (run_key TEXT PRIMARY KEY);
"""


def _make_store(root: Path, *, current: bool = True) -> tuple[Path, Path]:
    root.mkdir()
    database = root / "nikke.sqlite3"
    key = root / "secret.key"
    with sqlite3.connect(database) as connection:
        connection.executescript(TABLES_SQL)
        if current:
            connection.execute(
                "ALTER TABLE accounts ADD COLUMN xcommon_cipher BLOB NOT NULL DEFAULT X''"
            )
            connection.execute(
                "ALTER TABLE accounts ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''"
            )
    key.write_bytes(b"synthetic-test-key")
    return database, key


def test_ready_checks_current_storage_and_backup_without_writes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backup"
    database, key = _make_store(data_dir)
    backup_database, backup_key = _make_store(backup_dir)
    before = {path: path.stat().st_mtime_ns for path in (database, key, backup_database, backup_key)}

    result = build_preflight(data_dir, backup_dir, min_free_bytes=0, min_free_percent=0)

    assert result["overall"] == "READY"
    assert result["writes_performed"] == 0
    assert result["checks"]["storage_pair"]["status"] == "PASS"
    assert result["checks"]["database"]["status"] == "PASS"
    assert result["checks"]["backup_pair"]["status"] == "PASS"
    assert result["checks"]["backup_database"]["status"] == "PASS"
    assert result["checks"]["disk_capacity"]["status"] == "PASS"
    assert {path: path.stat().st_mtime_ns for path in before} == before


def test_legacy_schema_requires_migration_without_altering_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database, _ = _make_store(data_dir, current=False)
    before = database.read_bytes()

    result = build_preflight(data_dir, min_free_bytes=0, min_free_percent=0)

    assert result["overall"] == "MIGRATION_REQUIRED"
    assert result["checks"]["database"]["status"] == "MIGRATION_REQUIRED"
    assert "xcommon_cipher" not in {
        row[1] for row in sqlite3.connect(database).execute("PRAGMA table_info(accounts)")
    }
    assert database.read_bytes() == before


def test_missing_key_blocks_and_does_not_create_anything(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database, key = _make_store(data_dir)
    key.unlink()

    result = build_preflight(data_dir, min_free_bytes=0, min_free_percent=0)

    assert result["overall"] == "BLOCKED"
    assert result["checks"]["storage_pair"]["status"] == "BLOCKED"
    assert result["writes_performed"] == 0
    assert not key.exists()
    assert database.exists()


def test_corrupt_database_blocks(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "nikke.sqlite3"
    database.write_bytes(b"not-a-sqlite-database")
    (data_dir / "secret.key").write_bytes(b"synthetic-test-key")

    result = build_preflight(data_dir, min_free_bytes=0, min_free_percent=0)

    assert result["overall"] == "BLOCKED"
    assert result["checks"]["database"]["reason"] == "database_unreadable"


def test_missing_backup_pair_blocks_when_backup_requested(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backup"
    _make_store(data_dir)
    backup_dir.mkdir()

    result = build_preflight(data_dir, backup_dir, min_free_bytes=0, min_free_percent=0)

    assert result["overall"] == "BLOCKED"
    assert result["checks"]["backup_pair"]["status"] == "BLOCKED"


def test_cli_prints_json_and_returns_attention_code_for_migration(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "data"
    _make_store(data_dir, current=False)

    exit_code = main(
        ["--data-dir", str(data_dir), "--min-free-bytes", "0", "--min-free-percent", "0"]
    )

    assert exit_code == 2
    output = capsys.readouterr().out
    assert '"overall": "MIGRATION_REQUIRED"' in output
    assert str(tmp_path) not in output


def test_database_inspection_does_not_open_writable_store(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database, _ = _make_store(data_dir)
    before = database.stat().st_mtime_ns

    assert inspect_database(database)["status"] == "PASS"
    assert database.stat().st_mtime_ns == before
