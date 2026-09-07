# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 SQLite 持久化操作结束后不会遗留文件句柄。"""

import sqlite3
import tempfile
import unittest

from astrbot_plugin_nikke.storage import NikkeStore


class StorageLifecycleTests(unittest.TestCase):
    def test_store_operations_release_sqlite_file_handles(self) -> None:
        """临时目录在 store 仍存活时也应能安全清理。"""
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            store.set_setting("lifecycle", {"ready": True})
            self.assertEqual(store.get_setting("lifecycle"), {"ready": True})

    def test_storage_context_rolls_back_and_closes_on_exception(self) -> None:
        """异常路径回滚未提交数据，并在退出时关闭连接。"""
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            connection = None
            with self.assertRaisesRegex(RuntimeError, "synthetic rollback"):
                with store._connect() as connection:
                    connection.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?)",
                        ("rollback", "should-not-persist"),
                    )
                    raise RuntimeError("synthetic rollback")

            self.assertIsNone(store.get_setting("rollback"))
            assert connection is not None
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
