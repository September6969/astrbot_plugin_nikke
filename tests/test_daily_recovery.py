from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase

from astrbot_plugin_nikke.client import CookieExpired
from astrbot_plugin_nikke.daily_models import DailyTaskStatus
from astrbot_plugin_nikke.main import NikkePlugin


class FakeDailyStore:
    def __init__(self):
        self.runs = {}
        self.events = []
        self.finished = {}
        self.invalid = []

    def claim_run(self, run_key, qq_id, action):
        self.events.append(f"claim:{action}")
        if run_key in self.runs:
            return False
        self.runs[run_key] = {"status": "running"}
        return True

    def get_run(self, run_key):
        return self.runs.get(run_key)

    def finish_run(self, run_key, status, detail=""):
        self.events.append(f"finish:{status}")
        self.runs[run_key] = {"status": status, "detail": detail}
        self.finished[run_key] = (status, detail)

    def mark_cookie_invalid(self, qq_id):
        self.invalid.append(str(qq_id))


class FakeDailyClient:
    def __init__(self, events, *, completed=False):
        self.events = events
        self.completed = completed

    async def get_profile(self, account):
        self.events.append("profile-read")

    async def get_daily_signin(self, account):
        self.events.append("signin-read")
        return {"found": True, "completed": self.completed, "task_id": "task-1"}

    async def perform_daily_signin(self, account):
        self.events.append("signin-read")
        self.events.append("signin-write")
        return "签到成功"


class ExpiredDailyClient(FakeDailyClient):
    async def get_profile(self, account):
        raise CookieExpired("登录状态已失效", "401", "GetUserProfileBasicInfo")


class CancelledDailyClient(FakeDailyClient):
    async def get_profile(self, account):
        raise asyncio.CancelledError()


class DailyRecoveryTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _account():
        return {
            "qq_id": "10001",
            "game_uid": "game-10001",
            "area_id": "3",
            "platform": "global",
            "nickname": "测试指挥官",
        }

    async def test_signin_intent_is_persisted_before_reads(self):
        store = FakeDailyStore()
        client = FakeDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = self._account()

        result = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(result.account_name, "测试指挥官")
        self.assertIn("签到成功", result.detail)
        self.assertLess(store.events.index("claim:signin"), store.events.index("signin-read"))
        self.assertLess(store.events.index("claim:signin"), store.events.index("signin-write"))

    async def test_running_daily_run_is_read_only_verified_after_restart(self):
        store = FakeDailyStore()
        run_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "daily")
        store.runs[run_key] = {"status": "running"}
        client = FakeDailyClient(store.events, completed=True)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = self._account()

        result = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(result.account_name, "测试指挥官")
        self.assertEqual(result.status, DailyTaskStatus.ALREADY_DONE)
        self.assertIn("恢复核验", result.detail)
        self.assertNotIn("signin-write", store.events)
        self.assertEqual(store.finished[run_key][0], "success")

    async def test_running_signin_run_becomes_unknown_without_replay(self):
        store = FakeDailyStore()
        signin_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "signin")
        store.runs[signin_key] = {"status": "running"}
        client = FakeDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = self._account()

        result = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(result.account_name, "测试指挥官")
        self.assertIn("未自动重发", result.detail)
        self.assertNotIn("signin-write", store.events)
        self.assertEqual(store.finished[signin_key][0], "unknown")

    async def test_terminal_success_signin_is_preserved_without_recovery_read(self):
        store = FakeDailyStore()
        signin_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "signin")
        store.runs[signin_key] = {"status": "success", "detail": "登录有效；签到成功"}
        client = FakeDailyClient(store.events, completed=False)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = self._account()

        result = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(result.account_name, "测试指挥官")
        self.assertEqual(result.detail, "登录有效；签到成功")
        self.assertEqual(store.runs[signin_key]["status"], "success")
        self.assertEqual(store.runs[signin_key]["detail"], "登录有效；签到成功")
        daily_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "daily")
        self.assertEqual(store.finished[daily_key][0], "success")
        self.assertEqual(store.events, ["claim:daily", "claim:signin", "finish:success"])
        self.assertNotIn("signin-read", store.events)

    async def test_cookie_expiry_closes_existing_signin_intent(self):
        store = FakeDailyStore()
        signin_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "signin")
        run_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "daily")
        store.runs[signin_key] = {"status": "running"}
        client = ExpiredDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = self._account()

        result = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(result.account_name, "测试指挥官")
        self.assertIn("重新绑定", result.detail)
        self.assertEqual(store.invalid, ["10001"])
        self.assertEqual(store.finished[signin_key][0], "expired")
        self.assertEqual(store.finished[run_key][0], "expired")

    async def test_cancellation_marks_owned_intents_unknown_and_is_rethrown(self):
        store = FakeDailyStore()
        client = CancelledDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = {"qq_id": "10001", "nickname": "测试指挥官"}
        run_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "daily")
        signin_key = NikkePlugin._daily_run_key("2026-09-07", self._account(), "signin")

        with self.assertRaises(asyncio.CancelledError):
            await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(store.finished[signin_key][0], "unknown")
        self.assertEqual(store.finished[run_key][0], "unknown")
        self.assertIn("未自动重发", store.finished[signin_key][1])
        self.assertIn("未自动重发", store.finished[run_key][1])
