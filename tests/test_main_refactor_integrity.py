# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from astrbot_plugin_nikke.core.container import ServiceContainer, create_container
from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.campaign.application import CampaignApplication
from astrbot_plugin_nikke.features.guide.application import GuideApplication
from astrbot_plugin_nikke.features.tower.application import TowerApplication


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
            self.assertIs(container.account_application._store, container.store)
            self.assertIs(container.web.store, container.store)
            self.assertIsNotNone(container.client)
            self.assertIsNotNone(container.asset_manager)
            self.assertIsNotNone(container.renderer)
            self.assertIsNotNone(container.daily_runner)
            self.assertIsNotNone(container.web)
            self.assertIsInstance(container.campaign_application, CampaignApplication)
            self.assertIs(container.campaign_application._account_reader, container.store)
            self.assertIs(container.campaign_application._gateway, container.client)
            self.assertIsInstance(container.guide_application, GuideApplication)
            self.assertIsInstance(container.tower_application, TowerApplication)

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

    def test_root_entrypoints_and_isolation(self):
        import warnings

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            import astrbot_plugin_nikke.container as root_container
            self.assertTrue(hasattr(root_container, "create_container"))

        with self.assertRaises(ModuleNotFoundError):
            import astrbot_plugin_nikke.daily_runner


if __name__ == "__main__":
    unittest.main()
