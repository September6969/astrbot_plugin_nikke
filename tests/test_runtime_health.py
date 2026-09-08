# SPDX-License-Identifier: GPL-3.0-or-later
"""验证只读运行健康诊断和管理员命令接线。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.runtime_health import RuntimeHealth, collect_runtime_health, format_runtime_health


class RuntimeHealthTests(IsolatedAsyncioTestCase):
    def test_collects_cache_size_temp_files_and_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache" / "portraits").mkdir(parents=True)
            (root / "voice_cache").mkdir()
            (root / "announcements").mkdir()
            (root / "nikke.sqlite3").write_bytes(b"synthetic-db")
            (root / "secret.key").write_bytes(b"synthetic-key")
            (root / "cache" / "portraits" / "hero.png").write_bytes(b"1234")
            (root / "cache" / "portraits" / "hero.temporary.tmp").write_bytes(b"12")
            (root / "voice_cache" / "voice.mp3").write_bytes(b"123456")

            snapshot = collect_runtime_health(root, min_free_bytes=0)

            self.assertTrue(snapshot.data_dir_exists)
            self.assertTrue(snapshot.database_present)
            self.assertTrue(snapshot.secret_key_present)
            self.assertEqual(snapshot.cache_file_count, 3)
            self.assertEqual(snapshot.cache_bytes, 12)
            self.assertEqual(snapshot.temporary_file_count, 1)
            self.assertEqual(snapshot.status, "需关注")
            text = format_runtime_health(snapshot)
            self.assertIn("缓存：3 个文件 / 12.0 B", text)
            self.assertIn("存在未清理临时缓存", text)
            self.assertNotIn(str(root), text)
            self.assertNotIn("synthetic-key", text)

    def test_missing_data_is_reported_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            snapshot = collect_runtime_health(root, min_free_bytes=0)

            self.assertFalse(snapshot.data_dir_exists)
            self.assertFalse(snapshot.database_present)
            self.assertFalse(snapshot.secret_key_present)
            self.assertIn("数据目录缺失", format_runtime_health(snapshot))
            self.assertFalse(root.exists())

    def test_root_symlink_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "target"
            target.mkdir()
            (target / "cache").mkdir()
            (target / "cache" / "outside.txt").write_bytes(b"must not count")
            link = base / "data-link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"当前平台不支持目录符号链接：{error}")

            snapshot = collect_runtime_health(link, min_free_bytes=0)

            self.assertFalse(snapshot.data_dir_exists)
            self.assertFalse(snapshot.database_present)
            self.assertEqual(snapshot.cache_file_count, 0)
            self.assertEqual(snapshot.cache_bytes, 0)

            parent_target = base / "parent-target"
            (parent_target / "nested" / "cache").mkdir(parents=True)
            (parent_target / "nested" / "cache" / "outside.txt").write_bytes(b"must not count")
            parent_link = base / "parent-link"
            parent_link.symlink_to(parent_target, target_is_directory=True)
            snapshot = collect_runtime_health(parent_link / "nested", min_free_bytes=0)

            self.assertFalse(snapshot.data_dir_exists)
            self.assertEqual(snapshot.cache_file_count, 0)
            self.assertEqual(snapshot.cache_bytes, 0)

    def test_invalid_disk_usage_is_unknown_and_attention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nikke.sqlite3").write_bytes(b"synthetic-db")
            (root / "secret.key").write_bytes(b"synthetic-key")
            with patch("astrbot_plugin_nikke.runtime_health.shutil.disk_usage") as disk_usage:
                disk_usage.return_value = SimpleNamespace(free=-1, total=1024)

                snapshot = collect_runtime_health(root, min_free_bytes=0)

            self.assertIsNone(snapshot.disk_free_bytes)
            self.assertIsNone(snapshot.disk_total_bytes)
            self.assertIn("磁盘容量不可用", format_runtime_health(snapshot))
            self.assertEqual(snapshot.status, "需关注")

    def test_unrepresentable_disk_usage_is_unknown_and_attention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("astrbot_plugin_nikke.runtime_health.shutil.disk_usage") as disk_usage:
                disk_usage.return_value = SimpleNamespace(free=10**1000, total=10**1001)

                snapshot = collect_runtime_health(root, min_free_bytes=0)

            self.assertIsNone(snapshot.disk_free_bytes)
            self.assertIsNone(snapshot.disk_total_bytes)
            self.assertIn("磁盘容量不可用", format_runtime_health(snapshot))
            self.assertEqual(snapshot.status, "需关注")

    def test_format_bytes_handles_unrepresentable_snapshot_values(self) -> None:
        snapshot = RuntimeHealth(
            data_dir_exists=True,
            database_present=True,
            secret_key_present=True,
            cache_file_count=0,
            cache_bytes=0,
            temporary_file_count=0,
            disk_free_bytes=10**1000,
            disk_total_bytes=10**1001,
            issues=(),
        )

        self.assertIn("磁盘：未知 可用 / 未知 总计", format_runtime_health(snapshot))

    async def test_admin_health_command_includes_readonly_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache").mkdir()
            (root / "nikke.sqlite3").write_bytes(b"synthetic-db")
            (root / "secret.key").write_bytes(b"synthetic-key")
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.data_dir = root
            plugin.store = SimpleNamespace(list_accounts=lambda with_cookie=False: [{"qq_id": "synthetic"}])
            plugin._directory = []
            plugin.web_host = "0.0.0.0"
            plugin.web_port = 6210
            plugin.config = {"enable_daily_actions": False, "enable_cdk_redemption": False}
            event = SimpleNamespace(is_admin=lambda: True, plain_result=lambda text: text)

            with patch("astrbot_plugin_nikke.runtime_health.shutil.disk_usage") as disk_usage:
                disk_usage.return_value = SimpleNamespace(free=2 * 1024**3, total=4 * 1024**3)
                result = [item async for item in plugin.health(event)]

            self.assertEqual(len(result), 1)
            self.assertIn("状态：正常", result[0])
            self.assertIn("磁盘：2.0 GiB 可用 / 4.0 GiB 总计", result[0])
            self.assertNotIn("synthetic-key", result[0])


if __name__ == "__main__":
    unittest.main()
