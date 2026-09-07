# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 SQLite 持久化操作结束后不会遗留文件句柄。"""

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


if __name__ == "__main__":
    unittest.main()
