# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import ast
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
            self.assertIs(container.web.client, container.client)
            self.assertIs(container.daily_runner.store, container.store)
            self.assertIs(container.daily_runner.client, container.client)
            self.assertIsNotNone(container.client)
            self.assertIsNotNone(container.asset_manager)
            self.assertIsNotNone(container.renderer)
            self.assertIsNotNone(container.daily_runner)
            self.assertIsNotNone(container.web)
            self.assertIsInstance(container.campaign_application, CampaignApplication)
            self.assertIs(container.campaign_application._account_reader, container.store)
            self.assertIs(container.campaign_application._gateway, container.client)
            self.assertIs(container.raid_application._gateway, container.client)
            self.assertIs(container.voice_application._store, container.store)
            self.assertIs(container.campaign_renderer.assets, container.asset_manager)
            self.assertIsInstance(container.guide_application, GuideApplication)
            self.assertIsInstance(container.tower_application, TowerApplication)

    def test_plugin_constructor_does_not_copy_container_members(self):
        source = (self.root / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        aliases = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Attribute)
                and isinstance(value.value.value, ast.Name)
                and value.value.value.id == "self"
                and value.value.attr in {"services", "handlers", "adapters"}
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    if target.value.id == "self" and target.attr != value.value.attr:
                        aliases.append(target.attr)
        self.assertEqual(aliases, [])
        self.assertNotIn("self.container", source)

    def test_main_is_a_thin_host_shell_with_registered_entry_map(self):
        source = (self.root / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertLessEqual(len(source.splitlines()), 700)

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")
        forbidden = ("features", "integrations", "ui.renderers", "httpx", "PIL", "core.storage")
        self.assertFalse(
            [module for module in imported_modules if module.startswith(forbidden)],
            imported_modules,
        )

        plugin = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
        )
        registered = []
        for method in plugin.body:
            if not isinstance(method, ast.AsyncFunctionDef):
                continue
            decorator_text = ast.unparse(method.decorator_list)
            if "filter.command" not in decorator_text and "filter.event_message_type" not in decorator_text:
                continue
            registered.append(method.name)
            self.assertLessEqual(
                sum(isinstance(node, ast.stmt) for node in ast.walk(method)),
                20,
                method.name,
            )
            self.assertTrue(
                any(
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr == (
                        "command_runtime" if method.name == "nikke" else "adapters"
                    )
                    for node in ast.walk(method)
                ),
                method.name,
            )
        self.assertEqual(registered, ["nikke", "on_nikke_poke"])
        command_methods = {
            "nikke", "tarot_command", "nikke_help", "account", "bind", "unbind",
            "status", "me", "query", "voice_settings", "union_raid_ranking",
            "union_raid_my", "union_raid", "roster", "progress", "character", "info",
            "daily", "claim", "cdk", "cdk_batch", "cdk_available", "cdk_history",
            "campaign", "event_schedule", "announcements_view",
            "announcement_deep_rescan", "announcement_subscription", "guide", "push",
            "admin", "group_set", "schedule", "summary", "run", "health",
        }
        methods = {
            method.name: method
            for method in plugin.body
            if isinstance(method, ast.AsyncFunctionDef)
        }
        self.assertTrue(command_methods.issubset(methods))
        for name in command_methods:
            method = methods[name]
            self.assertLessEqual(
                sum(isinstance(node, ast.stmt) for node in ast.walk(method)), 20,
                name,
            )
            self.assertTrue(
                any(
                    isinstance(node, ast.Attribute)
                    and node.attr in {
                        "command_runtime",
                        "adapters",
                        "_dispatch_account_command",
                        "daily",
                        "_help_text",
                    }
                    for node in ast.walk(method)
                ),
                name,
            )
        entry_map = self.root / "docs/architecture/ASTRBOT_COMMAND_ENTRY_MAP.md"
        self.assertTrue(entry_map.is_file())
        mapping = entry_map.read_text(encoding="utf-8")
        for entry in ("日程", "塔罗", "announcement", "group_set", "on_nikke_poke"):
            self.assertIn(entry, mapping)

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
