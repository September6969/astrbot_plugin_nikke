# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar v0.4 结构化活动日程系统测试套件。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

import httpx

from astrbot_plugin_nikke.announcement_delivery import AnnouncementDelivery
from astrbot_plugin_nikke.calendar_models import CalendarActivity, _aware_utc
from astrbot_plugin_nikke.calendar_service import CalendarService
from astrbot_plugin_nikke.calendar_sources import GameKeeNikkeScheduleSource, _canonical_int
from astrbot_plugin_nikke.storage import NikkeStore


class TestCalendarModels(IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    def test_rejects_naive_datetime(self):
        naive_start = datetime(2026, 9, 13, 10, 0)
        aware_end = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            CalendarActivity(
                event_id="test:1",
                title="Test Event",
                start_at=naive_start,
                end_at=aware_end,
            )

    def test_rejects_inverted_or_equal_window(self):
        t1 = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 9, 13, 11, 0, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            CalendarActivity(
                event_id="test:1",
                title="Test Event",
                start_at=t1,
                end_at=t2,
            )
        with self.assertRaises(ValueError):
            CalendarActivity(
                event_id="test:1",
                title="Test Event",
                start_at=t1,
                end_at=t1,
            )

    def test_strict_type_validations(self):
        start = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)
        # Empty event_id or title
        with self.assertRaises(ValueError):
            CalendarActivity(event_id="", title="Title", start_at=start, end_at=end)
        with self.assertRaises(ValueError):
            CalendarActivity(event_id="e1", title="", start_at=start, end_at=end)
        # Rejects bool as int
        with self.assertRaises(ValueError):
            CalendarActivity(event_id="e1", title="T", start_at=start, end_at=end, importance=True)
        with self.assertRaises(ValueError):
            CalendarActivity(event_id="e1", title="T", start_at=start, end_at=end, version=True)
        # Rejects version < 1
        with self.assertRaises(ValueError):
            CalendarActivity(event_id="e1", title="T", start_at=start, end_at=end, version=0)

    def test_cache_roundtrip(self):
        act = CalendarActivity(
            event_id="gamekee:101",
            title="Coop Operation",
            start_at=datetime(2026, 9, 13, 4, 0, tzinfo=timezone(timedelta(hours=8))),
            end_at=datetime(2026, 9, 15, 4, 0, tzinfo=timezone(timedelta(hours=8))),
            category="coop",
            source="gamekee",
            source_id="101",
            source_url="https://gamekee.com/101",
            banner_url="https://gamekee.com/banner.png",
            description="Details",
            importance=1,
            tag="coop",
            version=2,
        )
        d = act.to_dict()
        restored = CalendarActivity.from_dict(d)

        self.assertEqual(restored.event_id, act.event_id)
        self.assertEqual(restored.title, act.title)
        self.assertEqual(restored.start_at, act.start_at)
        self.assertEqual(restored.end_at, act.end_at)
        self.assertEqual(restored.start_at.tzinfo, timezone.utc)
        self.assertEqual(restored.version, 2)
        self.assertEqual(restored.fingerprint, act.fingerprint)
        self.assertEqual(restored.name, act.title)
        self.assertEqual(restored.deadline_version, 2)

    def test_status_and_remaining_display(self):
        start = self.now
        end = self.now + timedelta(days=2, hours=3)
        act = CalendarActivity(event_id="e1", title="Active Event", start_at=start, end_at=end)

        # Before start
        before_now = start - timedelta(days=1, hours=2)
        self.assertFalse(act.is_active(before_now))
        self.assertTrue(act.is_upcoming(before_now))
        self.assertFalse(act.is_ended(before_now))
        self.assertEqual(act.remaining_display(before_now), "距开始 1天 2小时")

        # Active
        mid_now = start + timedelta(hours=5)
        self.assertTrue(act.is_active(mid_now))
        self.assertFalse(act.is_upcoming(mid_now))
        self.assertFalse(act.is_ended(mid_now))
        self.assertIn("剩余 1天", act.remaining_display(mid_now))

        # Under 1 day remaining
        soon_now = end - timedelta(hours=4, minutes=15)
        self.assertTrue(act.is_active(soon_now))
        self.assertEqual(act.remaining_display(soon_now), "剩余 4小时 15分钟")

        # Ended
        after_now = end + timedelta(minutes=1)
        self.assertFalse(act.is_active(after_now))
        self.assertFalse(act.is_upcoming(after_now))
        self.assertTrue(act.is_ended(after_now))
        self.assertEqual(act.remaining_display(after_now), "已结束")


class TestCalendarSources(IsolatedAsyncioTestCase):
    def test_canonical_int(self):
        self.assertEqual(_canonical_int(123), 123)
        self.assertEqual(_canonical_int("123"), 123)
        self.assertEqual(_canonical_int(" 123 "), 123)
        self.assertIsNone(_canonical_int(True))
        self.assertIsNone(_canonical_int(False))
        self.assertIsNone(_canonical_int(1.0))
        self.assertIsNone(_canonical_int("1.0"))
        self.assertIsNone(_canonical_int("abc"))
        self.assertIsNone(_canonical_int(None))

    async def test_gamekee_fetch_contract_and_mapping(self):
        captured_request = {}

        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_request["url"] = str(request.url)
            captured_request["headers"] = dict(request.headers)
            captured_request["params"] = dict(request.url.params)

            payload = {
                "code": 0,
                "data": [
                    {
                        "id": 991,
                        "title": "协同作战：神罚",
                        "begin_at": 1789200000,
                        "end_at": 1789300000,
                        "importance": 1,
                        "tag": "协同作战",
                        "big_picture": "https://img.gamekee.com/big.png",
                        "picture": "https://img.gamekee.com/small.png",
                        "link_url": "https://gamekee.com/nikke/991",
                        "description": "协同作战说明",
                    },
                    {
                        # Malformed row (missing end_at > begin_at)
                        "id": 992,
                        "title": "坏数据",
                        "begin_at": 1789300000,
                        "end_at": 1789200000,
                    },
                ],
            }
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(mock_handler)
        source = GameKeeNikkeScheduleSource(transport=transport)
        activities = await source.fetch()

        self.assertEqual(captured_request["headers"].get("game-alias"), "nikke")
        self.assertEqual(captured_request["params"].get("serverId"), "19")
        self.assertEqual(captured_request["params"].get("status"), "0")
        self.assertEqual(captured_request["params"].get("limit"), "999")

        self.assertEqual(len(activities), 1)
        act = activities[0]
        self.assertEqual(act.event_id, "gamekee:991")
        self.assertEqual(act.title, "协同作战：神罚")
        self.assertEqual(act.category, "coop")
        self.assertEqual(act.banner_url, "https://img.gamekee.com/big.png")
        self.assertEqual(act.source_url, "https://gamekee.com/nikke/991")
        self.assertEqual(act.importance, 1)

        self.assertEqual(source.last_scan["rows"], 2)
        self.assertEqual(source.last_scan["valid"], 1)
        self.assertEqual(source.last_scan["malformed"], 1)
        self.assertEqual(source.last_scan["duplicates"], 0)

    async def test_schema_drift_protection_on_all_malformed(self):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            payload = {
                "code": 200,
                "data": [
                    {"id": 1, "title": "broken", "begin_at": True, "end_at": 2},
                    {"id": "bad", "title": "also broken", "begin_at": 1, "end_at": 0},
                ],
            }
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(mock_handler)
        source = GameKeeNikkeScheduleSource(transport=transport)
        with self.assertRaises(ValueError) as ctx:
            await source.fetch()
        self.assertIn("漂移", str(ctx.exception))

    async def test_valid_empty_upstream_data(self):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 0, "data": []})

        transport = httpx.MockTransport(mock_handler)
        source = GameKeeNikkeScheduleSource(transport=transport)
        activities = await source.fetch()
        self.assertEqual(activities, [])
        self.assertEqual(source.last_scan["rows"], 0)


class TestCalendarService(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.service = CalendarService(self.tmp_dir.name)
        self.now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    def test_horizon_normalization(self):
        self.assertEqual(CalendarService.normalize_horizon(None), 14)
        self.assertEqual(CalendarService.normalize_horizon(""), 14)
        self.assertEqual(CalendarService.normalize_horizon(7), 7)
        self.assertEqual(CalendarService.normalize_horizon("7"), 7)
        self.assertEqual(CalendarService.normalize_horizon(14), 14)
        self.assertEqual(CalendarService.normalize_horizon("14"), 14)
        self.assertEqual(CalendarService.normalize_horizon(30), 30)
        self.assertEqual(CalendarService.normalize_horizon("30"), 30)

        for invalid in (0, 1, 15, 31, "abc", True, False, 14.0):
            with self.assertRaises(ValueError):
                CalendarService.normalize_horizon(invalid)

    async def test_versioning_and_atomic_cache_reload(self):
        t1 = self.now
        t2 = self.now + timedelta(days=2)
        act1 = CalendarActivity(event_id="gamekee:1", title="Event v1", start_at=t1, end_at=t2)

        success, msg = await self.service.sync_from_source(fetcher=lambda: [act1])
        self.assertTrue(success)
        self.assertTrue(self.service.has_snapshot())
        self.assertEqual(self.service.activity_count(), 1)
        self.assertEqual(self.service.list_activities()[0].version, 1)

        # Reload from disk into new instance
        service2 = CalendarService(self.tmp_dir.name)
        self.assertTrue(service2.has_snapshot())
        self.assertEqual(service2.activity_count(), 1)
        self.assertEqual(service2.list_activities()[0].version, 1)

        # Sync same activity with identical content -> version unchanged
        act1_same = CalendarActivity(event_id="gamekee:1", title="Event v1", start_at=t1, end_at=t2)
        await service2.sync_from_source(fetcher=lambda: [act1_same])
        self.assertEqual(service2.list_activities()[0].version, 1)

        # Sync same activity with modified title -> version incremented
        act1_modified = CalendarActivity(event_id="gamekee:1", title="Event v2 Updated", start_at=t1, end_at=t2)
        await service2.sync_from_source(fetcher=lambda: [act1_modified])
        self.assertEqual(service2.list_activities()[0].version, 2)
        self.assertEqual(service2.list_activities()[0].title, "Event v2 Updated")

    async def test_source_failure_preserves_existing_cache(self):
        act = CalendarActivity(
            event_id="gamekee:1",
            title="Initial Event",
            start_at=self.now,
            end_at=self.now + timedelta(days=1),
        )
        ok, _ = await self.service.sync_from_source(fetcher=lambda: [act])
        self.assertTrue(ok)
        self.assertEqual(self.service.activity_count(), 1)
        self.assertTrue(self.service.has_snapshot())

        # Failed sync
        async def failing_fetcher():
            raise httpx.ConnectError("Connection refused")

        ok, err = await self.service.sync_from_source(fetcher=failing_fetcher)
        self.assertFalse(ok)
        self.assertIn("ConnectError", err)
        # Snapshot and cache must remain intact
        self.assertTrue(self.service.has_snapshot())
        self.assertEqual(self.service.activity_count(), 1)
        self.assertEqual(self.service.list_activities()[0].title, "Initial Event")

        # format_schedule_text should still succeed with warning banner
        text = self.service.format_schedule_text(days=14, now=self.now)
        self.assertIn("⚠️ 日程数据同步失败", text)
        self.assertIn("Initial Event", text)

    def test_grouping_mutual_exclusivity(self):
        # 5 items
        soon = CalendarActivity(
            event_id="soon",
            title="Soon Ending Event",
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(hours=4),
            category="coop",
        )
        active = CalendarActivity(
            event_id="active",
            title="Active Long Event",
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(days=3),
            category="union_raid",
        )
        upcoming = CalendarActivity(
            event_id="upcoming",
            title="Upcoming In Window",
            start_at=self.now + timedelta(days=2),
            end_at=self.now + timedelta(days=5),
            category="solo_raid",
        )
        late = CalendarActivity(
            event_id="late",
            title="Too Far Ahead",
            start_at=self.now + timedelta(days=20),
            end_at=self.now + timedelta(days=25),
            category="recruit",
        )
        ended = CalendarActivity(
            event_id="ended",
            title="Already Finished",
            start_at=self.now - timedelta(days=3),
            end_at=self.now - timedelta(days=1),
            category="event",
        )

        for a in (soon, active, upcoming, late, ended):
            self.service._activities[a.event_id] = a
        self.service._has_snapshot = True

        text = self.service.format_schedule_text(days=14, now=self.now)
        self.assertIn("【即将结束】", text)
        self.assertIn("Soon Ending Event", text)
        self.assertIn("【进行中】", text)
        self.assertIn("Active Long Event", text)
        self.assertIn("【即将开始】", text)
        self.assertIn("Upcoming In Window", text)
        self.assertNotIn("Too Far Ahead", text)
        self.assertNotIn("Already Finished", text)

        # Ensure items appear exactly once in their specific section
        parts = text.split("【")
        soon_part = [p for p in parts if p.startswith("即将结束")][0]
        active_part = [p for p in parts if p.startswith("进行中")][0]
        upcoming_part = [p for p in parts if p.startswith("即将开始")][0]

        self.assertIn("Soon Ending Event", soon_part)
        self.assertNotIn("Soon Ending Event", active_part)
        self.assertNotIn("Soon Ending Event", upcoming_part)

        self.assertIn("Active Long Event", active_part)
        self.assertNotIn("Active Long Event", soon_part)

        self.assertIn("Upcoming In Window", upcoming_part)
        self.assertNotIn("Upcoming In Window", soon_part)

    def test_reminder_deadlines_returns_only_active(self):
        soon = CalendarActivity(
            event_id="soon",
            title="Soon",
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(hours=2),
        )
        active = CalendarActivity(
            event_id="active",
            title="Active",
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(days=2),
        )
        upcoming = CalendarActivity(
            event_id="upcoming",
            title="Upcoming",
            start_at=self.now + timedelta(days=2),
            end_at=self.now + timedelta(days=5),
        )
        ended = CalendarActivity(
            event_id="ended",
            title="Ended",
            start_at=self.now - timedelta(days=3),
            end_at=self.now - timedelta(days=1),
        )
        for a in (soon, active, upcoming, ended):
            self.service._activities[a.event_id] = a
        self.service._has_snapshot = True

        deadlines = self.service.list_reminder_deadlines(now=self.now)
        deadline_ids = [d.event_id for d in deadlines]
        self.assertEqual(deadline_ids, ["soon", "active"])


class TestAnnouncementDeliveryCalendarDefense(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.store = NikkeStore(self.tmp_dir.name)
        self.delivery = AnnouncementDelivery(self.store)
        self.now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        self.delivery.subscribe("fake:target", [], now=self.now - timedelta(days=5), reminder_hours=(24,))

    def test_future_start_activity_suppressed_from_reminder_plan(self):
        # Even if someone accidentally passes an upcoming activity to delivery.plan
        # with end_at - 24h <= now, the start_at > now guard MUST prevent it from being planned.
        future_act = CalendarActivity(
            event_id="gamekee:future_1",
            title="Future Raid",
            start_at=self.now + timedelta(hours=2),
            end_at=self.now + timedelta(hours=24),  # due = end_at - 24h = now
        )
        planned = self.delivery.plan(records=[], deadlines=[future_act], now=self.now)
        self.assertEqual(planned, [], "未来尚未开始的活动绝不能提前触发结束提醒")


class TestMainIntegration(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    async def test_event_schedule_command_horizon_and_fallback(self):
        from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
        from astrbot_plugin_nikke.announcement_service import AnnouncementService
        from astrbot_plugin_nikke.main import NikkePlugin

        class DummyEvent:
            def plain_result(self, text):
                return text

        # 1. Invalid horizon
        main_inst = NikkePlugin.__new__(NikkePlugin)
        results = [r async for r in main_inst.event_schedule(DummyEvent(), "99")]
        self.assertEqual(len(results), 1)
        self.assertIn("日程范围错误", results[0])
        self.assertIn("用法", results[0])

        # 2. Calendar snapshot available
        cal = CalendarService(Path(self.tmp_dir.name) / "cal")
        act = CalendarActivity(
            event_id="e1",
            title="Active Test Event",
            start_at=datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
        )
        await cal.sync_from_source(fetcher=lambda: [act])
        main_inst.calendar = cal
        main_inst.announcements = AnnouncementService()

        # Query 7 days
        results = [r async for r in main_inst.event_schedule(DummyEvent(), "7")]
        self.assertIn("未来 7 天", results[0])
        self.assertIn("Active Test Event", results[0])

        # Query 30 days
        results = [r async for r in main_inst.event_schedule(DummyEvent(), "30")]
        self.assertIn("未来 30 天", results[0])
        self.assertIn("Active Test Event", results[0])

        # 3. Calendar fails and has no snapshot -> falls back to announcements with warning banner
        cal_empty = CalendarService(Path(self.tmp_dir.name) / "cal_empty")
        main_inst.calendar = cal_empty

        async def fail_sync():
            return False, "网络连接拒绝"

        cal_empty.sync_from_source = fail_sync

        rec = AnnouncementRecord(
            content_id="a1",
            title="Official Maintenance Notice",
            body="活动时间：2026.09.01 18:00 ~ 2026.09.20 18:00",
            published_at="2026-09-01 10:00",
        )
        main_inst.announcements.add_or_update(rec)

        results = [r async for r in main_inst.event_schedule(DummyEvent(), "14")]
        self.assertIn("⚠️ 结构化日程不可用，已降级使用官方公告时间解析。", results[0])
        self.assertIn("网络连接拒绝", results[0])
        self.assertIn("Official Maintenance Notice", results[0])

    def test_deadline_reminders_for_delivery_selector(self):
        from astrbot_plugin_nikke.announcement_service import AnnouncementService, GameDeadline
        from astrbot_plugin_nikke.main import NikkePlugin

        main_inst = NikkePlugin.__new__(NikkePlugin)
        ann_service = AnnouncementService()
        main_inst.announcements = ann_service

        real_now = datetime.now(timezone.utc)
        dl = GameDeadline("d1", "Ann Deadline", "event", end_at=real_now + timedelta(days=1), start_at=real_now - timedelta(days=1))
        ann_service._deadlines = {dl.event_id: dl}

        # Without calendar -> returns announcements deadlines
        main_inst.calendar = None
        deadlines = main_inst._deadline_reminders_for_delivery()
        self.assertEqual(len(deadlines), 1)
        self.assertEqual(deadlines[0].event_id, "d1")

        # With calendar without snapshot -> returns announcements deadlines
        cal = CalendarService(Path(self.tmp_dir.name) / "cal2")
        main_inst.calendar = cal
        deadlines = main_inst._deadline_reminders_for_delivery()
        self.assertEqual(len(deadlines), 1)
        self.assertEqual(deadlines[0].event_id, "d1")

        # With calendar having snapshot and activities -> returns calendar deadlines
        act = CalendarActivity(
            event_id="cal_1",
            title="Cal Event",
            start_at=real_now - timedelta(hours=1),
            end_at=real_now + timedelta(days=1),
        )
        cal._activities["cal_1"] = act
        cal._has_snapshot = True

        deadlines = main_inst._deadline_reminders_for_delivery()
        self.assertEqual(len(deadlines), 1)
        self.assertEqual(deadlines[0].event_id, "cal_1")
