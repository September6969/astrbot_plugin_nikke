"""Profile application 的依赖边界与固定时钟合同。"""

from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot_plugin_nikke.features.profile.application import ProfileApplication


class _Gateway:
    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None):
        self.payload = payload or {
            "basic": {"nickname": "固定账号"},
            "outpost": {},
            "roster": [],
            "outpost_available": True,
            "roster_available": True,
        }
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def get_profile_dashboard(self, account):
        self.calls.append(account)
        if self.error is not None:
            raise self.error
        return self.payload


class _Builder:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class ProfileApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_injected_gateway_builder_and_clock_preserve_display_timezone(self):
        gateway = _Gateway()
        builder = _Builder()
        app = ProfileApplication(
            gateway=gateway,
            builder=builder,
            clock=lambda: datetime(2026, 9, 6, 4, 0, tzinfo=timezone.utc),
            plugin_version="test-version",
        )
        account = {"qq_id": "synthetic-qq", "area_id": "3"}

        result = await app.build_dashboard(account)

        self.assertIs(result, builder.calls[0])
        self.assertEqual(gateway.calls, [account])
        self.assertEqual(builder.calls[0]["fetched_at"], "2026-09-06 12:00")
        self.assertEqual(builder.calls[0]["plugin_version"], "test-version")
        self.assertIs(builder.calls[0]["account"], account)
        self.assertEqual(builder.calls[0]["basic"], {"nickname": "固定账号"})

    async def test_gateway_failure_is_not_converted_or_retried(self):
        error = RuntimeError("synthetic gateway failure")
        gateway = _Gateway(error=error)
        builder = _Builder()
        app = ProfileApplication(
            gateway=gateway,
            builder=builder,
            clock=lambda: datetime(2026, 9, 6, 12, 0),
            plugin_version="test-version",
        )

        with self.assertRaises(RuntimeError) as raised:
            await app.build_dashboard({"qq_id": "synthetic-qq"})

        self.assertIs(raised.exception, error)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(builder.calls, [])

    def test_application_source_has_no_framework_or_infrastructure_import(self):
        path = Path(__file__).resolve().parents[1] / "features" / "profile" / "application.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )
        self.assertTrue(imported.isdisjoint({"astrbot", "aiohttp", "httpx", "sqlite3", "PIL"}))
        self.assertNotIn("ui", " ".join(imported))


if __name__ == "__main__":
    unittest.main()
