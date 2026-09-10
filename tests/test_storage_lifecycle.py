# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 SQLite 持久化操作结束后不会遗留文件句柄。"""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from cryptography.fernet import Fernet

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

    def test_fernet_key_semantic_validation_matrix(self) -> None:
        """完整测试 Fernet 密钥语义校验：合法密钥通过，长度、字符集或解码字节数错误均精准拦截。"""
        import os
        from unittest.mock import patch

        # 1. 合法 Fernet key 通过
        valid_key = Fernet.generate_key().decode("ascii")
        self.assertEqual(len(valid_key), 44)
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": valid_key}):
                store = NikkeStore(directory)
                self.assertEqual(store._cipher._signing_key, Fernet(valid_key.encode("ascii"))._signing_key)

        # 2. 43-char 拒绝
        short_key = "A" * 43
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": short_key}):
                with self.assertRaises(ValueError) as ctx:
                    NikkeStore(directory)
                self.assertIn("NIKKE_ENCRYPTION_KEY", str(ctx.exception))

        # 3. 45-char 拒绝
        long_key = "A" * 45
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": long_key}):
                with self.assertRaises(ValueError) as ctx:
                    NikkeStore(directory)
                self.assertIn("NIKKE_ENCRYPTION_KEY", str(ctx.exception))

        # 4. 44-char 含有非法 Base64 字符（如 !@#$）拒绝
        invalid_b64 = "!@#$" * 10 + "===="
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": invalid_b64}):
                with self.assertRaises(ValueError) as ctx:
                    NikkeStore(directory)
                self.assertIn("NIKKE_ENCRYPTION_KEY", str(ctx.exception))

        # 5. 44-char Base64 但解码后字节数不是 32（例如 44 个 'A' 解码出 33 字节）拒绝
        wrong_bytes_key = "A" * 44
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": wrong_bytes_key}):
                with self.assertRaises(ValueError) as ctx:
                    NikkeStore(directory)
                self.assertIn("NIKKE_ENCRYPTION_KEY", str(ctx.exception))

    def test_database_replacement_automatically_reinitializes_wal_mode(self) -> None:
        """验证即使底层 SQLite 文件在运行时被替换为 DELETE 模式的新库，下一次连接也能自动恢复 WAL 模式。"""
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)

            # 初始状态应为 WAL 模式
            raw_conn = sqlite3.connect(store.db_path)
            try:
                mode = raw_conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")
            finally:
                raw_conn.close()

            # 模拟外部数据库恢复/替换：生成一个 DELETE 模式的新 SQLite 库并覆盖 db_path
            new_db_path = Path(directory) / "restored.sqlite3"
            new_conn = sqlite3.connect(new_db_path)
            try:
                new_conn.execute("PRAGMA journal_mode=DELETE")
                new_conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                new_conn.execute("INSERT INTO settings (key, value) VALUES ('replaced', 'true')")
                new_conn.commit()
            finally:
                new_conn.close()

            # 原子替换数据库文件
            import time
            time.sleep(0.02)
            new_db_path.replace(store.db_path)

            # 通过 store 读取数据，验证底层连接感知文件身份变更，并自动执行 WAL 初始化
            val = store.get_setting("replaced")
            self.assertEqual(val, True)

            raw_conn2 = sqlite3.connect(store.db_path)
            try:
                mode2 = raw_conn2.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode2.lower(), "wal", "被替换的数据库文件在首次访问后必须被自动初始化为 WAL 模式")
            finally:
                raw_conn2.close()


if __name__ == "__main__":
    unittest.main()
