# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from astrbot_plugin_nikke.core.container import ServiceContainer, create_container
from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.features.daily.runner import DailyRunner


class MainRefactorIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

    def test_container_creation_and_fields(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            config = {"request_timeout": 5, "spine_budget_seconds": 1.0}
            container = create_container(self.root, data_dir, config)

            self.assertIsInstance(container, ServiceContainer)
            self.assertIsNotNone(container.store)
            self.assertIsNotNone(container.client)
            self.assertIsNotNone(container.asset_manager)
            self.assertIsNotNone(container.renderer)
            self.assertIsNotNone(container.daily_runner)
            self.assertIsNotNone(container.web)

    def test_daily_runner_identity_and_keys(self):
        account = {
            "game_uid": "98765432",
            "area_id": "1",
            "platform": "Global",
            "qq_id": "123456",
        }
        identity = DailyRunner.daily_identity(account)
        self.assertEqual(identity, "global:1:98765432")

        key = DailyRunner.daily_run_key("2026-09-16", account, "daily")
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        self.assertEqual(key, f"2026-09-16:game:{digest}:daily")

    def test_daily_runner_error_mapping(self):
        class RateLimitExc(Exception):
            code = "429"

        res = DailyRunner.daily_error_result("TestUser", "签到", RateLimitExc("Too Many Requests"))
        self.assertEqual(res.status, DailyTaskStatus.RATE_LIMITED)
        self.assertIn("受到频控", res.detail)

        res_generic = DailyRunner.daily_error_result("TestUser", "签到", ValueError("something bad"))
        self.assertEqual(res_generic.status, DailyTaskStatus.FAILED)
        self.assertIn("失败：ValueError", res_generic.detail)

    def test_legacy_shims(self):
        import warnings

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            import astrbot_plugin_nikke.container as root_container
            import astrbot_plugin_nikke.daily_runner as root_daily_runner

            self.assertTrue(hasattr(root_container, "create_container"))
            self.assertTrue(hasattr(root_daily_runner, "DailyRunner"))
            deprecation_warnings = [w for w in recorded if issubclass(w.category, DeprecationWarning)]
            self.assertGreaterEqual(len(deprecation_warnings), 2)


if __name__ == "__main__":
    unittest.main()
