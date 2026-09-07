# SPDX-License-Identifier: GPL-3.0-or-later
"""验证只读运行健康诊断和管理员命令接线。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.runtime_health import collect_runtime_health, format_runtime_health


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
