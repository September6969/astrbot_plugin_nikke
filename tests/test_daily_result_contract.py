"""DailyTaskResult 状态合同与签到主链行为测试。"""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.client import BlaBlaError, CookieExpired, UnknownAfterAction
from astrbot_plugin_nikke.daily_models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.main import NikkePlugin


class FakeStore:
    def __init__(self, *, signin_claim=True):
        self.signin_claim = signin_claim
        self.claimed = []
        self.finished = []
        self.invalidated = []
        self.runs = {}

    def claim_run(self, run_key, qq_id, action):
        self.claimed.append((run_key, qq_id, action))
        if run_key in self.runs:
            return False
        if action == "signin":
            return self.signin_claim
        return True

    def finish_run(self, run_key, status, detail=""):
        self.finished.append((run_key, status, detail))
        self.runs[run_key] = {"status": status, "detail": detail}

    def get_run(self, run_key):
        return self.runs.get(run_key)

    def retry_run(self, run_key, statuses):
        current = self.runs.get(run_key)
        if current and current["status"] in statuses:
            self.runs[run_key] = {"status": "running", "detail": ""}
            return True
        return False

    def mark_cookie_invalid(self, qq_id):
        self.invalidated.append(qq_id)


class DailyResultModelTests(IsolatedAsyncioTestCase):
    def test_storage_round_trip_is_strict(self):
        result = DailyTaskResult("测试账号", DailyTaskStatus.UNKNOWN_AFTER_ACTION, "结果未确认")
        self.assertEqual(DailyTaskResult.from_storage(result.to_storage()), result)
        self.assertIsNone(DailyTaskResult.from_storage(["测试账号", "结果未确认"]))
        self.assertIsNone(DailyTaskResult.from_storage({"account_name": "测试账号", "status": "success"}))


class DailyResultWiringTests(IsolatedAsyncioTestCase):
    def _plugin(self, *, enabled=True, signin_claim=True):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_daily_actions": enabled}
        plugin.store = FakeStore(signin_claim=signin_claim)
        plugin.client = SimpleNamespace(
            get_profile=AsyncMock(),
            get_daily_signin=AsyncMock(return_value={"found": True, "completed": False, "task_id": "task"}),
            perform_daily_signin=AsyncMock(return_value="签到成功"),
        )
        return plugin

    async def test_missing_task_is_unavailable_not_success(self):
        plugin = self._plugin(enabled=False)
        plugin.client.get_daily_signin.return_value = {"found": False, "completed": False, "task_id": ""}

        result = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(result.status, DailyTaskStatus.UNAVAILABLE)
        self.assertEqual(plugin.store.finished[-1][1], "unavailable")

    async def test_existing_unknown_daily_run_is_not_reported_as_done(self):
        plugin = self._plugin()
        run_key = "2026-09-07:u1:daily"
        plugin.store.runs[run_key] = {"status": "unknown", "detail": "未确认"}

        result = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(result.status, DailyTaskStatus.UNKNOWN_AFTER_ACTION)
        plugin.client.get_profile.assert_awaited_once()
        plugin.client.perform_daily_signin.assert_not_awaited()

    async def test_disabled_pending_task_is_explicit(self):
        plugin = self._plugin(enabled=False)

        result = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(result.status, DailyTaskStatus.PENDING)
        plugin.client.perform_daily_signin.assert_not_awaited()

    async def test_pending_result_is_rechecked_when_actions_become_enabled(self):
        plugin = self._plugin(enabled=False)

        first = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")
        self.assertEqual(first.status, DailyTaskStatus.PENDING)
        self.assertEqual(plugin.store.finished[-1][1], "pending")

        plugin.config["enable_daily_actions"] = True
        second = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(second.status, DailyTaskStatus.SUCCESS)
        plugin.client.perform_daily_signin.assert_awaited_once()

    async def test_unavailable_result_is_rechecked_when_task_appears(self):
        plugin = self._plugin(enabled=False)
        plugin.client.get_daily_signin.return_value = {"found": False, "completed": False, "task_id": ""}

        first = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")
        self.assertEqual(first.status, DailyTaskStatus.UNAVAILABLE)
        self.assertEqual(plugin.store.finished[-1][1], "unavailable")

        plugin.client.get_daily_signin.return_value = {"found": True, "completed": True, "task_id": "task"}
        second = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(second.status, DailyTaskStatus.ALREADY_DONE)
        self.assertEqual(plugin.client.get_daily_signin.await_count, 2)

    async def test_unknown_after_action_is_not_failed_or_replayed(self):
        plugin = self._plugin()
        plugin.client.perform_daily_signin.side_effect = UnknownAfterAction("未确认", "UNKNOWN_AFTER_ACTION", "DailyCheckIn")

        result = await plugin._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")

        self.assertEqual(result.status, DailyTaskStatus.UNKNOWN_AFTER_ACTION)
        self.assertEqual(result.run_status, "unknown")
        self.assertEqual(plugin.client.perform_daily_signin.await_count, 1)
        self.assertEqual(plugin.store.finished[-1][1], "unknown")

    async def test_rate_limit_and_cookie_expired_are_distinct(self):
        rate_limited = self._plugin()
        rate_limited.client.perform_daily_signin.side_effect = BlaBlaError("请求过频", "212000", "DailyCheckIn")
        result = await rate_limited._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")
        self.assertEqual(result.status, DailyTaskStatus.RATE_LIMITED)

        expired = self._plugin()
        expired.client.get_daily_signin.side_effect = CookieExpired("失效", "401", "GetTaskListWithStatusV2")
        result = await expired._run_daily_for_account({"qq_id": "u1", "nickname": "测试"}, "2026-09-07")
        self.assertEqual(result.status, DailyTaskStatus.COOKIE_EXPIRED)
        self.assertEqual(expired.store.invalidated, ["u1"])
