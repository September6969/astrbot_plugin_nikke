# SPDX-License-Identifier: GPL-3.0-or-later
"""验证绑定服务 healthz 的本地存储 readiness 合同。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_nikke.web_service import BindingWebService


class HealthzReadinessTests(IsolatedAsyncioTestCase):
    async def _request_health(self, store) -> tuple[int, dict]:
        service = BindingWebService(store, object(), Path("unused-extension.zip"))
        client = TestClient(TestServer(service.app()))
        await client.start_server()
        try:
            response = await client.get("/healthz")
            return response.status, await response.json()
        finally:
            await client.close()

    async def test_healthz_ready_when_database_and_key_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "nikke.sqlite3"
            secret_key = root / "secret.key"
            database.write_bytes(b"synthetic-db")
            secret_key.write_bytes(b"synthetic-key")

            status, body = await self._request_health(SimpleNamespace(db_path=database, key_path=secret_key))

            self.assertEqual(status, 200)
            self.assertEqual(body["ok"], True)
            self.assertEqual(body["storage"], "ready")
            self.assertNotIn(str(root), str(body))
            self.assertNotIn("synthetic-key", str(body))

    async def test_healthz_returns_service_unavailable_when_key_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "nikke.sqlite3"
            database.write_bytes(b"synthetic-db")

            status, body = await self._request_health(SimpleNamespace(db_path=database, key_path=root / "secret.key"))

            self.assertEqual(status, 503)
            self.assertEqual(body, {
                "ok": False,
                "service": "nikke-binding",
                "version": body["version"],
                "storage": "unavailable",
            })

    async def test_healthz_does_not_treat_directories_as_storage_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "nikke.sqlite3"
            secret_key = root / "secret.key"
            database.mkdir()
            secret_key.mkdir()

            status, body = await self._request_health(SimpleNamespace(db_path=database, key_path=secret_key))

            self.assertEqual(status, 503)
            self.assertFalse(body["ok"])


if __name__ == "__main__":
    unittest.main()
