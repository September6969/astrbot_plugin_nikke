# SPDX-License-Identifier: GPL-3.0-or-later
"""验证本地数据备份与恢复所需文件的完整性。"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.scripts.backup_nikke_data import BackupError, create_backup


class DataBackupTests(unittest.TestCase):
    def test_backup_contains_verified_database_key_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data" / "nikke"
            backup_dir = root / "backups"
            data_dir.mkdir(parents=True)
            connection = sqlite3.connect(data_dir / "nikke.sqlite3")
            try:
                connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO settings VALUES ('ready', '1')")
                connection.commit()
            finally:
                connection.close()
            secret = b"synthetic-secret-key"
            (data_dir / "secret.key").write_bytes(secret)

            backup = create_backup(data_dir, backup_dir, label="test")

            self.assertEqual(
                sorted(path.name for path in backup.iterdir()),
                ["manifest.json", "nikke.sqlite3", "secret.key"],
            )
            self.assertEqual((backup / "secret.key").read_bytes(), secret)
            connection = sqlite3.connect(backup / "nikke.sqlite3")
            try:
                row = connection.execute("SELECT value FROM settings WHERE key='ready'").fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], "1")
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["files"], ["nikke.sqlite3", "secret.key"])

    def test_backup_refuses_source_subdirectory_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            sqlite3.connect(data_dir / "nikke.sqlite3").close()
            (data_dir / "secret.key").write_bytes(b"key")

            with self.assertRaises(BackupError):
                create_backup(data_dir, data_dir / "backups", label="nested")

            destination = root / "backups"
            create_backup(data_dir, destination, label="stable")
            with self.assertRaises(BackupError):
                create_backup(data_dir, destination, label="stable")


if __name__ == "__main__":
    unittest.main()
