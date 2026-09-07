"""每账号自动签到偏好只影响定时任务，不触发真实写操作。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.storage import NikkeStore


class DailyAutoStoreTests(unittest.TestCase):
    def _bound_store(self, directory: str) -> NikkeStore:
        store = NikkeStore(directory)
        store.create_bind_session("a" * 40, "10001")
        store.consume_bind_session(
            "a" * 40,
            "session=synthetic",
            "game-uid",
            "game-openid",
            "合成指挥官",
            "合成角色",
            "3",
        )
        return store

    def test_auto_daily_defaults_off_and_filters_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._bound_store(directory)
            account = store.get_account("10001", with_cookie=False)
            self.assertEqual(account["auto_daily_enabled"], 0)
            self.assertEqual(store.list_accounts(auto_daily_only=True, with_cookie=False), [])

            self.assertTrue(store.set_auto_daily("10001", True))
            self.assertEqual(
                [row["qq_id"] for row in store.list_accounts(auto_daily_only=True, with_cookie=False)],
                ["10001"],
            )
            self.assertTrue(store.set_push("10001", False))
            self.assertEqual(
                store.list_accounts(push_only=True, auto_daily_only=True, with_cookie=False),
                [],
            )

    def test_existing_database_gets_safe_default_without_losing_account(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._bound_store(directory)
            self.assertTrue(store.set_auto_daily("10001", True))
            conn = sqlite3.connect(Path(directory) / "nikke.sqlite3")
            try:
                conn.execute("ALTER TABLE accounts DROP COLUMN auto_daily_enabled")
                conn.commit()
            finally:
                conn.close()
            reopened = NikkeStore(Path(directory))
            self.assertEqual(reopened.get_account("10001", with_cookie=False)["auto_daily_enabled"], 0)


class DailyAutoCommandTests(unittest.IsolatedAsyncioTestCase):
    class Event:
        @staticmethod
        def get_sender_id():
            return "10001"

        @staticmethod
        def plain_result(text):
            return text

    def _plugin(self, *, global_enabled=False):
        class Store:
            def __init__(self):
                self.enabled = None

            @staticmethod
            def get_account(qq_id):
                return {"qq_id": qq_id, "nickname": "合成指挥官"}

            def set_auto_daily(self, qq_id, enabled):
                self.enabled = (qq_id, enabled)
                return True

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin.config = {"enable_daily_actions": global_enabled}
        return plugin

    async def test_preference_command_only_changes_local_setting(self):
        plugin = self._plugin(global_enabled=False)
        results = [item async for item in plugin.daily(self.Event(), "自动", "开")]
        self.assertEqual(plugin.store.enabled, ("10001", True))
        self.assertIn("自动签到已开启", results[0])
        self.assertIn("暂不会提交", results[0])

    async def test_router_passes_auto_value_to_daily_handler(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        calls = []

        async def daily(event, action, value):
            calls.append((action, value))
            yield "ok"

        plugin.daily = daily
        results = [item async for item in plugin.nikke(self.Event(), "日常", "自动", "关")]
        self.assertEqual(results, ["ok"])
        self.assertEqual(calls, [("自动", "关")])


class DailyAutoSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def _plugin(self):
        class Store:
            def __init__(self):
                self.calls = []
                self.saved = []

            def list_accounts(self, **kwargs):
                self.calls.append(kwargs)
                return []

            def set_setting(self, key, value):
                self.saved.append((key, value))

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin.config = {"max_concurrency": 2}
        return plugin

    async def test_scheduled_batch_requires_both_account_preferences(self):
        plugin = self._plugin()
        self.assertEqual(await plugin._run_all_daily("2026-09-07", automatic=True), [])
        self.assertEqual(
            plugin.store.calls,
            [{"push_only": True, "with_cookie": True, "auto_daily_only": True}],
        )

    async def test_explicit_admin_batch_keeps_existing_selection_semantics(self):
        plugin = self._plugin()
        self.assertEqual(await plugin._run_all_daily("2026-09-07"), [])
        self.assertEqual(
            plugin.store.calls,
            [{"push_only": True, "with_cookie": True, "auto_daily_only": False}],
        )
        self.assertEqual(
            plugin.store.saved,
            [("daily_results:2026-09-07:manual", [])],
        )

    async def test_manual_results_are_not_reused_by_automatic_summary(self):
        class Store:
            @staticmethod
            def get_setting(key, default=None):
                if key == "summary_group_umo":
                    return "synthetic-group"
                if key == "daily_results:2026-09-07:manual":
                    return [("manual-account", "已执行")]
                return default

        class Renderer:
            @staticmethod
            def render_summary(results):
                return "synthetic-summary.png"

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin.renderer = Renderer()
        plugin.context = type("Context", (), {"send_message": AsyncMock()})()
        plugin._run_all_daily = AsyncMock(return_value=[("automatic-account", "已执行")])

        await plugin._send_summary("2026-09-07")

        plugin._run_all_daily.assert_awaited_once_with("2026-09-07", automatic=True)

    async def test_summary_fallback_stays_in_automatic_scope(self):
        class Store:
            @staticmethod
            def get_setting(key, default=None):
                return "synthetic-group" if key == "summary_group_umo" else []

        class Renderer:
            @staticmethod
            def render_summary(results):
                return "synthetic-summary.png"

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = Store()
        plugin.renderer = Renderer()
        plugin.context = type("Context", (), {"send_message": AsyncMock()})()
        plugin._run_all_daily = AsyncMock(return_value=[])

        await plugin._send_summary("2026-09-07")
        plugin._run_all_daily.assert_awaited_once_with("2026-09-07", automatic=True)
