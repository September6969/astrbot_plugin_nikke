from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from astrbot_plugin_nikke.client import CookieExpired
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


class DailyRecoveryTests(IsolatedAsyncioTestCase):
    async def test_signin_intent_is_persisted_before_reads(self):
        store = FakeDailyStore()
        client = FakeDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = {"qq_id": "10001", "nickname": "测试指挥官"}

        name, detail = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(name, "测试指挥官")
        self.assertIn("签到成功", detail)
        self.assertLess(store.events.index("claim:signin"), store.events.index("signin-read"))
        self.assertLess(store.events.index("claim:signin"), store.events.index("signin-write"))

    async def test_running_daily_run_is_read_only_verified_after_restart(self):
        store = FakeDailyStore()
        run_key = "2026-09-07:10001:daily"
        store.runs[run_key] = {"status": "running"}
        client = FakeDailyClient(store.events, completed=True)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = {"qq_id": "10001", "nickname": "测试指挥官"}

        name, detail = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(name, "测试指挥官")
        self.assertIn("恢复核验", detail)
        self.assertNotIn("signin-write", store.events)
        self.assertEqual(store.finished[run_key][0], "success")

    async def test_running_signin_run_becomes_unknown_without_replay(self):
        store = FakeDailyStore()
        signin_key = "2026-09-07:10001:signin"
        store.runs[signin_key] = {"status": "running"}
        client = FakeDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = {"qq_id": "10001", "nickname": "测试指挥官"}

        name, detail = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(name, "测试指挥官")
        self.assertIn("未自动重发", detail)
        self.assertNotIn("signin-write", store.events)
        self.assertEqual(store.finished[signin_key][0], "unknown")

    async def test_cookie_expiry_closes_existing_signin_intent(self):
        store = FakeDailyStore()
        signin_key = "2026-09-07:10001:signin"
        run_key = "2026-09-07:10001:daily"
        store.runs[signin_key] = {"status": "running"}
        client = ExpiredDailyClient(store.events)
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.store = store
        plugin.client = client
        plugin.config = {"enable_daily_actions": True}
        account = {"qq_id": "10001", "nickname": "测试指挥官"}

        name, detail = await plugin._run_daily_for_account(account, "2026-09-07")

        self.assertEqual(name, "测试指挥官")
        self.assertIn("重新绑定", detail)
        self.assertEqual(store.invalid, ["10001"])
        self.assertEqual(store.finished[signin_key][0], "expired")
        self.assertEqual(store.finished[run_key][0], "expired")
