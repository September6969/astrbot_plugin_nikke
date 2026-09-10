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

    def test_list_accounts_returns_all_accounts_and_filters(self) -> None:
        """验证 list_accounts 单次查询能正确解密多账号并支持 push/auto_daily 过滤。"""
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            for i in range(1, 4):
                token = f"token_test_{i}_" + "x" * 20
                store.create_bind_session(token, f"1000{i}")
                store.consume_bind_session(
                    token,
                    f"game_token=tok_{i}; game_uid={i}",
                    str(i),
                    f"openid_{i}",
                    f"Player_{i}",
                    f"Commander_{i}",
                    "global",
                )
            # push_enabled 默认为 1；关闭 10001 和 10003，仅保留 10002
            store.set_push("10001", False)
            store.set_push("10003", False)
            # 开启第 3 个账号的 auto_daily（默认为 0）
            store.set_auto_daily("10003", True)

            all_accounts = store.list_accounts(with_cookie=True)
            self.assertEqual(len(all_accounts), 3)
            self.assertEqual({a["qq_id"] for a in all_accounts}, {"10001", "10002", "10003"})
            self.assertTrue(all("cookie" in a for a in all_accounts))

            push_only = store.list_accounts(push_only=True, with_cookie=False)
            self.assertEqual(len(push_only), 1)
            self.assertEqual(push_only[0]["qq_id"], "10002")
            self.assertNotIn("cookie", push_only[0])

            auto_daily = store.list_accounts(auto_daily_only=True, with_cookie=False)
            self.assertEqual(len(auto_daily), 1)
            self.assertEqual(auto_daily[0]["qq_id"], "10003")

    def test_invalid_encryption_key_env_var_is_rejected(self) -> None:
        """非 44 字符合法 Fernet 密钥环境变量会被直接拒绝。"""
        import os
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": "too-short"}):
                with self.assertRaises(ValueError) as ctx:
                    NikkeStore(directory)
                self.assertIn("NIKKE_ENCRYPTION_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
