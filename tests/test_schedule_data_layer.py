# SPDX-License-Identifier: GPL-3.0-or-later
"""数据抓取与标准化数据层测试套件。"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    quality_badge,
    CST,
)
from astrbot_plugin_nikke.integrations.blablalink.fetch_client import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    FetchClient,
    FetchHTTPStatusError,
    FetchNetworkError,
    FetchTimeoutError,
    _sanitize_url,
)
from astrbot_plugin_nikke.features.calendar.schedule_adapters import (
    GameKeeScheduleAdapter,
    ManualOverrideScheduleAdapter,
    OfficialAnnouncementScheduleAdapter,
)
from astrbot_plugin_nikke.features.calendar.schedule_service import (
    ScheduleService,
    _is_same_event,
    _merge_two_events,
    _title_similarity,
)


class TestFetchClient(IsolatedAsyncioTestCase):
    def test_sanitize_url(self):
        url = "https://example.com/api/v1/data?token=secret123&key=abc"
        sanitized = _sanitize_url(url)
        self.assertEqual(sanitized, "https://example.com/api/v1/data?...")

        clean_url = "https://example.com/api/v1/data"
        self.assertEqual(_sanitize_url(clean_url), clean_url)

    def test_circuit_breaker_state_machine(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_seconds=10.0)
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.can_request())

        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, "CLOSED")
        self.assertTrue(cb.can_request())

        # 第 3 次连续失败，触发熔断
        cb.record_failure()
        self.assertEqual(cb.state, "OPEN")
        self.assertFalse(cb.can_request())

        # 成功后恢复
        cb.record_success()
        self.assertEqual(cb.state, "CLOSED")
        self.assertEqual(cb.consecutive_failures, 0)
        self.assertTrue(cb.can_request())

    async def test_fetch_timeout_and_retry(self):
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        # 模拟 2 次超时（初次 + 1次重试），随后抛出 FetchTimeoutError
        mock_transport.handle_async_request.side_effect = httpx.ReadTimeout("Read timed out")

        client = FetchClient(
            connect_timeout=0.1,
            read_timeout=0.1,
            max_retries=1,
            circuit_failure_threshold=5,
            transport=mock_transport,
        )

        with self.assertRaises(FetchTimeoutError):
            await client.get_json("https://api.example.com/data")

        # 验证确实只重试了 1 次（总共 2 次请求）
        self.assertEqual(mock_transport.handle_async_request.call_count, 2)

    async def test_circuit_breaker_blocks_requests_when_open(self):
        mock_transport = AsyncMock(spec=httpx.AsyncBaseTransport)
        mock_transport.handle_async_request.side_effect = httpx.ConnectError("Connection refused")

        client = FetchClient(
            max_retries=0,
            circuit_failure_threshold=3,
            circuit_recovery_seconds=60.0,
            transport=mock_transport,
        )

        # 触发 3 次失败
        for _ in range(3):
            with self.assertRaises(FetchNetworkError):
                await client.get_json("https://fail.example.com/data")

        # 第 4 次请求应被熔断器直接阻断，不再调用 transport
        call_count_before = mock_transport.handle_async_request.call_count
        with self.assertRaises(CircuitBreakerOpenError):
            await client.get_json("https://fail.example.com/data")
        self.assertEqual(mock_transport.handle_async_request.call_count, call_count_before)


class TestCanonicalModels(IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    def test_status_self_computed(self):
        # 1. UPCOMING: start_at > now
        event_up = CanonicalEvent(
            id="ev:1",
            title="Upcoming Event",
            event_type="event",
            start_at=self.now + timedelta(days=1),
            end_at=self.now + timedelta(days=3),
        )
        self.assertEqual(event_up.compute_status(self.now), "UPCOMING")
        self.assertTrue(event_up.is_upcoming(self.now))
        self.assertFalse(event_up.is_active(self.now))

        # 2. ACTIVE: start_at <= now < end_at
        event_act = CanonicalEvent(
            id="ev:2",
            title="Active Event",
            event_type="event",
            start_at=self.now - timedelta(days=1),
            end_at=self.now + timedelta(days=1),
        )
        self.assertEqual(event_act.compute_status(self.now), "ACTIVE")
        self.assertTrue(event_act.is_active(self.now))

        # 3. ENDED: end_at <= now
        event_end = CanonicalEvent(
            id="ev:3",
            title="Ended Event",
            event_type="event",
            start_at=self.now - timedelta(days=3),
            end_at=self.now - timedelta(days=1),
        )
        self.assertEqual(event_end.compute_status(self.now), "ENDED")
        self.assertTrue(event_end.is_ended(self.now))

    def test_no_pseudo_precision_countdown(self):
        # EXACT 精度展示精确倒计时
        exact_event = CanonicalEvent(
            id="ev:exact",
            title="Exact Raid",
            event_type="solo_raid",
            start_at=self.now - timedelta(hours=5),
            end_at=self.now + timedelta(hours=7, minutes=30),
            time_precision="EXACT",
        )
        rem_exact = exact_event.remaining_display(self.now)
        self.assertIn("剩余 7小时30分", rem_exact)

        # DATE_ONLY 精度绝不显示时分秒倒计时，仅显示日期截止
        end_time = datetime(2026, 9, 20, 23, 59, 59, tzinfo=timezone.utc)
        date_only_event = CanonicalEvent(
            id="ev:date_only",
            title="Coop Date Only",
            event_type="coop",
            start_at=self.now,
            end_at=end_time,
            time_precision="DATE_ONLY",
        )
        rem_date = date_only_event.remaining_display(self.now)
        self.assertNotIn("小时", rem_date)
        self.assertNotIn("分", rem_date)
        self.assertIn("截止", rem_date)
        end_cst_str = end_time.astimezone(CST).strftime("%m.%d")
        self.assertIn(end_cst_str, rem_date)

    def test_fingerprint_and_serialization(self):
        ev = CanonicalEvent(
            id="ev:fingerprint",
            title="Test Title",
            event_type="event",
            start_at=self.now,
            end_at=self.now + timedelta(days=2),
            banner_url="https://img.example.com/a.png",
        )
        fp1 = ev.fingerprint
        self.assertTrue(len(fp1) == 64)

        data = ev.to_dict()
        restored = CanonicalEvent.from_dict(data)
        self.assertEqual(restored.id, ev.id)
        self.assertEqual(restored.fingerprint, fp1)


class TestScheduleServiceDataLayer(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.service = ScheduleService(self.tmp_dir.name)
        self.now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_multi_source_field_level_merge(self):
        # 两个来自不同源的同一活动条目
        gk_event = CanonicalEvent(
            id="gamekee:100",
            title="EVA 联动大型活动",
            event_type="event",
            start_at=self.now,
            end_at=self.now + timedelta(days=7),
            cycle_id="eva_2026",
            banner_url="https://gamekee.com/eva_banner.png",
            detail_url="https://gamekee.com/eva",
            sources=["gamekee"],
            primary_source="gamekee",
            confidence=0.85,
        )

        official_event = CanonicalEvent(
            id="official:notice_999",
            title="【联动通知】新世纪福音战士合作活动正式开启",
            event_type="event",
            start_at=self.now + timedelta(minutes=5),  # 稍微校准
            end_at=self.now + timedelta(days=7),
            cycle_id="eva_2026",
            banner_url="https://official.com/eva.png",
            detail_url="https://official.com/notice_999",
            sources=["official"],
            primary_source="official",
            confidence=0.95,
        )

        self.assertTrue(_is_same_event(gk_event, official_event))
        merged = _merge_two_events(gk_event, official_event)

        # 验证合并字段：
        # 来源列表合并包含两者
        self.assertIn("gamekee", merged.sources)
        self.assertIn("official", merged.sources)
        # 偏好 GameKee 易读中文标题
        self.assertEqual(merged.title, "EVA 联动大型活动")
        # 时间偏好官方
        self.assertEqual(merged.start_at, official_event.start_at)

    async def test_l1_l2_cache_and_last_known_good(self):
        event = CanonicalEvent(
            id="e:init",
            title="Baseline Event",
            event_type="event",
            start_at=self.now,
            end_at=self.now + timedelta(days=5),
        )

        # 1. 成功同步并保存 L2 快照
        ok, _ = await self.service.sync_from_source(fetcher=lambda: [event])
        self.assertTrue(ok)
        self.assertEqual(self.service.activity_count(), 1)
        self.assertEqual(self.service.data_quality, "FRESH")
        self.assertTrue(self.service.cache_path.is_file())

        # 2. 从磁盘重建新实例，验证从 L2 快照冷启动
        reloaded = ScheduleService(self.tmp_dir.name)
        self.assertTrue(reloaded.has_snapshot())
        self.assertEqual(reloaded.activity_count(), 1)
        self.assertEqual(reloaded.list_canonical()[0].title, "Baseline Event")

        # 3. 模拟数据源全部失败，验证降级使用旧快照并标记 STALE，绝不清空数据
        async def failing_adapter():
            raise httpx.ConnectError("Network unreachable")

        mock_adapter = AsyncMock()
        mock_adapter.source_name = "mock_remote"
        mock_adapter.fetch.side_effect = failing_adapter
        reloaded.adapters = [mock_adapter]

        ok, err = await reloaded.refresh_schedule_data()
        self.assertFalse(ok)
        self.assertEqual(reloaded.data_quality, "STALE")
        # 快照依然保留
        self.assertEqual(reloaded.activity_count(), 1)
        self.assertEqual(reloaded.list_canonical()[0].title, "Baseline Event")

        # 文本展示包含 STALE 提示
        text = reloaded.format_schedule_text(days=14, now=self.now)
        self.assertIn("STALE", text)
        self.assertIn("Baseline Event", text)
