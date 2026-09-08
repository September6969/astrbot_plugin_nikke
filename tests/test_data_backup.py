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

    def test_backup_reports_unusable_destination_and_corrupt_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            sqlite3.connect(data_dir / "nikke.sqlite3").close()
            (data_dir / "secret.key").write_bytes(b"key")

            destination_file = root / "destination-file"
            destination_file.write_bytes(b"not a directory")
            with self.assertRaisesRegex(BackupError, "备份输出目录不可用"):
                create_backup(data_dir, destination_file, label="file")

            (data_dir / "nikke.sqlite3").write_bytes(b"not sqlite")
            with self.assertRaisesRegex(BackupError, "SQLite 备份失败"):
                create_backup(data_dir, root / "backups", label="corrupt")

    def test_backup_refuses_symlinked_roots_and_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_target = root / "source-target"
            source_target.mkdir()
            connection = sqlite3.connect(source_target / "nikke.sqlite3")
            connection.close()
            (source_target / "secret.key").write_bytes(b"key")
            destination = root / "backups"

            source_link = root / "source-link"
            try:
                source_link.symlink_to(source_target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("当前 Windows 环境不允许创建目录符号链接")

            with self.assertRaisesRegex(BackupError, "源数据目录不能是符号链接"):
                create_backup(source_link, destination, label="source-link")

            destination_target = root / "destination-target"
            destination_target.mkdir()
            destination_link = root / "destination-link"
            destination_link.symlink_to(destination_target, target_is_directory=True)
            with self.assertRaisesRegex(BackupError, "备份输出目录不能是符号链接"):
                create_backup(source_target, destination_link, label="destination-link")

            external_database = root / "external.sqlite3"
            external_database.write_bytes((source_target / "nikke.sqlite3").read_bytes())
            (source_target / "nikke.sqlite3").unlink()
            (source_target / "nikke.sqlite3").symlink_to(external_database)
            with self.assertRaisesRegex(BackupError, "源目录文件不能是符号链接"):
                create_backup(source_target, destination, label="database-link")

            (source_target / "nikke.sqlite3").unlink()
            connection = sqlite3.connect(source_target / "nikke.sqlite3")
            connection.close()
            external_key = root / "external.key"
            external_key.write_bytes(b"external-key")
            (source_target / "secret.key").unlink()
            (source_target / "secret.key").symlink_to(external_key)
            with self.assertRaisesRegex(BackupError, "源目录文件不能是符号链接"):
                create_backup(source_target, destination, label="key-link")


if __name__ == "__main__":
    unittest.main()
