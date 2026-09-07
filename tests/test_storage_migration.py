# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 SQLite schema migration 的兼容、幂等和回滚合同。"""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from astrbot_plugin_nikke.storage import NikkeStore, SCHEMA_NAME, SCHEMA_VERSION


class StorageMigrationTests(unittest.TestCase):
    @staticmethod
    def _write_key(root: Path) -> None:
        (root / "secret.key").write_bytes(Fernet.generate_key())

    def test_legacy_accounts_are_migrated_without_losing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_key(root)
            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                connection.execute(
                    """
                    CREATE TABLE accounts (
                        qq_id TEXT PRIMARY KEY,
                        cookie_cipher BLOB NOT NULL,
                        game_uid TEXT NOT NULL,
                        game_openid TEXT NOT NULL DEFAULT '',
                        nickname TEXT NOT NULL DEFAULT '',
                        role_name TEXT NOT NULL DEFAULT '',
                        area_id TEXT NOT NULL DEFAULT '',
                        push_enabled INTEGER NOT NULL DEFAULT 1,
                        cookie_valid INTEGER NOT NULL DEFAULT 1,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO accounts(qq_id,cookie_cipher,game_uid,updated_at) VALUES(?,?,?,?)",
                    ("synthetic-qq", b"cipher", "synthetic-game", 1),
                )
                connection.commit()
            finally:
                connection.close()

            store = NikkeStore(root)
            migrated = store.get_account("synthetic-qq", with_cookie=False)
            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
                version = connection.execute(
                    "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                    (SCHEMA_NAME,),
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(migrated["game_uid"], "synthetic-game")
            self.assertIn("xcommon_cipher", columns)
            self.assertIn("user_agent", columns)
            self.assertEqual(version, SCHEMA_VERSION)

    def test_migration_is_idempotent_and_preserves_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = NikkeStore(root)
            first.set_setting("synthetic", {"ready": True})
            NikkeStore(root)

            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                version = connection.execute(
                    "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                    (SCHEMA_NAME,),
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(first.get_setting("synthetic"), {"ready": True})
            self.assertEqual(version, SCHEMA_VERSION)

    def test_failed_migration_rolls_back_added_columns_and_meta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_key(root)
            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                connection.execute(
                    "CREATE TABLE accounts (qq_id TEXT PRIMARY KEY, cookie_cipher BLOB NOT NULL, game_uid TEXT NOT NULL, updated_at INTEGER NOT NULL)"
                )
                connection.commit()
            finally:
                connection.close()

            store = NikkeStore.__new__(NikkeStore)
            store.data_dir = root
            store.db_path = root / "nikke.sqlite3"
            store.key_path = root / "secret.key"
            store._lock = threading.RLock()
            original = store._apply_account_migrations

            def fail_after_schema_change(conn):
                original(conn)
                raise RuntimeError("synthetic migration failure")

            store._apply_account_migrations = fail_after_schema_change
            with self.assertRaisesRegex(RuntimeError, "synthetic migration failure"):
                store._init_db()

            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
                meta = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                ).fetchone()
            finally:
                connection.close()

            self.assertNotIn("xcommon_cipher", columns)
            self.assertNotIn("user_agent", columns)
            self.assertIsNone(meta)

    def test_newer_schema_is_rejected_without_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            NikkeStore(root)
            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                connection.execute(
                    "UPDATE schema_meta SET schema_version=? WHERE schema_name=?",
                    (SCHEMA_VERSION + 1, SCHEMA_NAME),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(RuntimeError, "高于当前插件"):
                NikkeStore(root)

            connection = sqlite3.connect(root / "nikke.sqlite3")
            try:
                version = connection.execute(
                    "SELECT schema_version FROM schema_meta WHERE schema_name=?",
                    (SCHEMA_NAME,),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION + 1)


if __name__ == "__main__":
    unittest.main()
