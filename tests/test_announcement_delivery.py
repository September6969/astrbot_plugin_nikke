"""仅使用模拟发送器，验证目标隔离、版本、时窗与成功持久化。"""
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from astrbot_plugin_nikke.announcement_delivery import AnnouncementDelivery
from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
from astrbot_plugin_nikke.announcement_service import GameDeadline
from astrbot_plugin_nikke.storage import NikkeStore


class DeliveryTests(IsolatedAsyncioTestCase):
    async def test_cleanup_preserves_version_watermark(self):
        self.service.subscribe("fake", [], now=self.now)
        await self.service.dispatch([self.record()], [], AsyncMock(return_value=True), now=self.now)
        state = self.store.get_setting(self.service.SETTING)
        for record in state["delivered"].values():
            record["pushed_at"] = (self.now-timedelta(days=100)).isoformat()
        state["retry_after"] = {"expired": (self.now-timedelta(minutes=1)).isoformat()}
        self.store.set_setting(self.service.SETTING, state)
        self.assertEqual(self.service.cleanup(now=self.now), 1)
        self.assertEqual(self.service.plan([self.record()], now=self.now), [])
        self.assertEqual(len(self.service.plan([self.record(version=2)], now=self.now)), 1)
        self.assertEqual(self.store.get_setting(self.service.SETTING)["retry_after"], {})

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = NikkeStore(self.directory.name)
        self.service = AnnouncementDelivery(self.store)
        self.now = datetime(2026, 9, 5, tzinfo=timezone.utc)

    def record(self, identifier="new", version=1, when=None):
        return AnnouncementRecord(identifier, "合成公告", "", (when or self.now).isoformat(), content_version=version)

    async def test_no_backfill_target_isolation_and_restart(self):
        old = self.record("old", when=self.now-timedelta(days=1))
        self.service.subscribe("fake:group:a", [old], now=self.now)
        self.service.subscribe("fake:private:b", [old], now=self.now)
        records = [old, self.record()]
        sender = AsyncMock(side_effect=[False, True])
        result = await self.service.dispatch(records, [], sender, now=self.now)
        self.assertEqual(result, {"succeeded": 1, "failed": 1})
        restarted = AnnouncementDelivery(self.store)
        pending = restarted.plan(records, now=self.now)
        self.assertEqual([p.target for p in pending], ["fake:group:a"])
        self.assertEqual(len(self.store.get_setting(self.service.SETTING)["delivered"]), 1)

    async def test_concurrent_dispatch_and_new_version(self):
        self.service.subscribe("fake", [], now=self.now)
        sender = AsyncMock(return_value=True)
        await asyncio.gather(*(self.service.dispatch([self.record()], [], sender, now=self.now) for _ in range(2)))
        self.assertEqual(sender.await_count, 1)
        self.assertEqual(len(self.service.plan([self.record(version=2)], now=self.now)), 1)
        self.service.unsubscribe("fake")
        self.assertEqual(self.service.plan([self.record(version=2)], now=self.now), [])

    async def test_deadline_window_version_and_failures(self):
        self.service.subscribe("fake", [], now=self.now-timedelta(days=2))
        deadline = GameDeadline("event", "合成活动", "event", self.now+timedelta(hours=6))
        planned = self.service.plan([], [deadline], now=self.now)
        self.assertEqual([p.reminder_hour for p in planned], [6])
        self.assertEqual(self.service.plan([], [deadline], now=self.now+timedelta(minutes=16)), [])
        failed = AsyncMock(side_effect=RuntimeError("synthetic"))
        await self.service.dispatch([], [deadline], failed, now=self.now)
        self.assertEqual(self.store.get_setting(self.service.SETTING)["delivered"], {})
        await self.service.dispatch([], [deadline], AsyncMock(return_value=True), now=self.now+timedelta(minutes=5))
        self.assertEqual(self.service.plan([], [deadline], now=self.now), [])
        deadline.deadline_version = 2
        self.assertEqual(len(self.service.plan([], [deadline], now=self.now)), 1)

    async def test_new_subscription_does_not_receive_expired_reminder(self):
        self.service.subscribe("fake", [], now=self.now)
        deadline = GameDeadline("event", "合成活动", "event", self.now+timedelta(minutes=59))
        self.assertEqual(self.service.plan([], [deadline], now=self.now), [])

    async def test_failure_backoff_survives_restart_without_blocking_other_target(self):
        for target in ("failed-target", "other-target"):
            self.service.subscribe(target, [], now=self.now)
        await self.service.dispatch([self.record()], [], AsyncMock(return_value=False), now=self.now, limit=1)
        restarted = AnnouncementDelivery(self.store)
        sender = AsyncMock(return_value=True)
        await restarted.dispatch([self.record()], [], sender, now=self.now, limit=1)
        self.assertEqual(sender.call_args.args[0], "other-target")
        sender.reset_mock()
        await restarted.dispatch([self.record()], [], sender, now=self.now)
        sender.assert_not_awaited()
        await restarted.dispatch([self.record()], [], sender, now=self.now+timedelta(minutes=5))
        sender.assert_awaited_once()
