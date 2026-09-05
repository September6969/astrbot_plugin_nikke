# SPDX-License-Identifier: GPL-3.0-or-later

import unittest
from datetime import datetime, timedelta, timezone

from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
from astrbot_plugin_nikke.announcement_service import AnnouncementService, DeadlineParser, GameDeadline


class AnnouncementModelsTests(unittest.TestCase):
    def test_record_hash_and_keys(self):
        rec = AnnouncementRecord(
            content_id="cms_12345",
            title="版本维护更新",
            body="服务器将于 2026.09.10 11:00 ~ 18:00 进行停服维护。",
            published_at="2026-09-08 12:00",
            source_url="https://nikke.example.com/news/12345",
            category="maintenance",
        )
        self.assertTrue(len(rec.body_hash) > 20)
        push_key = rec.compute_push_key("group_1001", "announcement")
        self.assertEqual(push_key, "group_1001:cms_12345:1:announcement")

        dl_key = rec.compute_deadline_key("group_1001", 24, "deadline")
        self.assertEqual(dl_key, "group_1001:cms_12345:1:24:deadline")


class DeadlineParserTests(unittest.TestCase):
    def test_parse_range_dates(self):
        title = "GREAT VILLAIN UNION 活动开启"
        body = "活动时间：2026.09.10 18:00 ~ 2026.09.24 04:59"
        deadlines = DeadlineParser.parse_deadlines(title, body, content_id="evt_01")
        self.assertEqual(len(deadlines), 1)
        dl = deadlines[0]
        self.assertEqual(dl.name, title)
        self.assertIsNotNone(dl.start_at)
        self.assertIsNotNone(dl.end_at)
        self.assertTrue(dl.end_at > dl.start_at)


class AnnouncementServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_add_and_update_change_detection(self):
        service = AnnouncementService()
        rec1 = AnnouncementRecord(
            content_id="cms_001",
            title="版本维护公告",
            body="停服时间：2026.09.10 11:00 ~ 2026.09.10 18:00",
            published_at="2026-09-08 12:00",
            category="maintenance",
        )
        is_new, is_updated = service.add_or_update(rec1)
        self.assertTrue(is_new)
        self.assertFalse(is_updated)
        self.assertEqual(service.record_count(), 1)

        # 相同内容再次添加，无变化
        is_new, is_updated = service.add_or_update(rec1)
        self.assertFalse(is_new)
        self.assertFalse(is_updated)

        # 维护延期：body 发生变化
        rec2 = AnnouncementRecord(
            content_id="cms_001",
            title="版本维护公告",
            body="停服时间：2026.09.10 11:00 ~ 2026.09.10 19:00（延期1小时）",
            published_at="2026-09-08 12:00",
            category="maintenance",
        )
        is_new, is_updated = service.add_or_update(rec2)
        self.assertFalse(is_new)
        self.assertTrue(is_updated)
        self.assertEqual(rec2.content_version, 2)

    def test_delivery_deduplication(self):
        service = AnnouncementService()
        key = "group_1001:cms_001:1:announcement"
        self.assertTrue(service.should_deliver(key))
        service.mark_delivered(key)
        self.assertFalse(service.should_deliver(key))

    def test_format_texts(self):
        service = AnnouncementService()
        rec = AnnouncementRecord(
            content_id="cms_001",
            title="版本维护公告",
            body="停服时间：2026.09.10 11:00 ~ 2026.09.10 18:00",
            published_at="2026-09-08 12:00",
            category="maintenance",
        )
        service.add_or_update(rec)
        text = service.format_announcements_text()
        self.assertIn("版本维护公告", text)
        self.assertIn("NIKKE 官方最新公告", text)

        sched_text = service.format_schedule_text()
        self.assertIsInstance(sched_text, str)

    def test_empty_cache_returns_not_ready_message(self):
        service = AnnouncementService()
        not_ready = "功能尚未就绪，正在同步官方数据，请稍候。"
        self.assertEqual(service.format_announcements_text(), not_ready)
        self.assertEqual(service.format_schedule_text(), not_ready)

    def test_disk_cache_load_and_save_with_update_time(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            service = AnnouncementService(Path(td))
            rec = AnnouncementRecord(
                content_id="cms_persistence",
                title="持久化测试公告",
                body="测试内容 2026.09.01 10:00 ~ 2026.09.20 12:00",
                published_at="2026-09-05 12:00",
                category="update",
            )
            service.add_or_update(rec)
            cache_file = Path(td) / "announcements_cache.json"
            self.assertTrue(cache_file.is_file())
            self.assertIsNotNone(service.last_updated_at)

            # 新建服务实例恢复缓存
            service2 = AnnouncementService(Path(td))
            self.assertEqual(service2.record_count(), 1)
            self.assertEqual(service2.last_updated_at, service.last_updated_at)

            # 验证输出包含最近更新时间
            text = service2.format_announcements_text()
            self.assertIn("最近更新时间", text)
            self.assertIn("持久化测试公告", text)

            sched = service2.format_schedule_text()
            self.assertIn("最近更新时间", sched)
            self.assertIn("持久化测试公告", sched)

    async def test_sync_failure_falls_back_to_cache_with_update_time(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            service = AnnouncementService(Path(td))
            rec = AnnouncementRecord(
                content_id="cms_fallback",
                title="本地降级公告",
                body="测试内容",
                published_at="2026-09-05 12:00",
            )
            service.add_or_update(rec)
            initial_time = service.last_updated_at

            # 模拟官方数据源同步失败
            async def failing_fetcher():
                raise ConnectionError("官方网络超时")

            success, err_msg = await service.sync_from_source(failing_fetcher)
            self.assertFalse(success)
            self.assertIn("官方数据同步失败", err_msg)

            # 降级输出本地缓存，并附带更新时间与降级提示
            text = service.format_announcements_text(fallback_error=err_msg)
            self.assertIn("本地降级公告", text)
            self.assertIn("官方数据同步失败", text)
            self.assertIn(initial_time, text)

    def test_parse_dates_with_various_timezones(self):
        # 1. UTC+9 / JST
        body_utc9 = "活动时间：2026.09.10 18:00 ~ 2026.09.24 04:59 (UTC+9)"
        deadlines_utc9 = DeadlineParser.parse_deadlines("活动1", body_utc9, "evt_utc9")
        self.assertEqual(len(deadlines_utc9), 1)
        dl9 = deadlines_utc9[0]
        # 2026-09-24 04:59 UTC+9 等价于 2026-09-23 19:59 UTC
        self.assertEqual(dl9.end_at, datetime(2026, 9, 23, 19, 59, tzinfo=timezone.utc))

        # 2. UTC
        body_utc = "维护时间：2026.09.15 11:00 ~ 2026.09.15 18:00 UTC"
        deadlines_utc = DeadlineParser.parse_deadlines("维护1", body_utc, "evt_utc")
        self.assertEqual(len(deadlines_utc), 1)
        self.assertEqual(deadlines_utc[0].end_at, datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc))

        # 3. PST (UTC-8)
        body_pst = "截止时间：2026.09.15 18:00 PST"
        deadlines_pst = DeadlineParser.parse_deadlines("截止1", body_pst, "evt_pst")
        self.assertEqual(len(deadlines_pst), 1)
        # 2026-09-15 18:00 PST (-8) 等价于 2026-09-16 02:00 UTC
        self.assertEqual(deadlines_pst[0].end_at, datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc))

    def test_update_announcement_prunes_old_deadlines_when_dates_removed(self):
        service = AnnouncementService()
        rec_initial = AnnouncementRecord(
            content_id="cms_evt_01",
            title="限时活动开启",
            body="活动时间：2026.09.10 18:00 ~ 2026.09.24 04:59",
            published_at="2026-09-08 12:00",
        )
        service.add_or_update(rec_initial)
        now_dt = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(len(service.list_active_deadlines(now_dt)), 1)

        # 官方修改公告正文，活动延期/取消且删除了所有时间
        rec_updated = AnnouncementRecord(
            content_id="cms_evt_01",
            title="限时活动开启",
            body="因系统故障，本次活动已暂时取消，时间待定。",
            published_at="2026-09-08 12:00",
        )
        is_new, is_updated = service.add_or_update(rec_updated)
        self.assertTrue(is_updated)
        # 验证旧日程已被完全清除，不再残留在列表中
        self.assertEqual(len(service.list_active_deadlines(now_dt)), 0)

    def test_mark_delivered_immediately_persists_to_disk(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            service = AnnouncementService(Path(td))
            key = "group_1001:cms_001:1:announcement"
            self.assertTrue(service.should_deliver(key))

            # 标记已投递
            service.mark_delivered(key)
            self.assertFalse(service.should_deliver(key))

            # 模拟进程重启，从磁盘恢复服务实例
            service_recovered = AnnouncementService(Path(td))
            self.assertFalse(service_recovered.should_deliver(key))
            self.assertIn(key, service_recovered._delivery_log)

    def test_single_start_time_does_not_create_deadline(self):
        # 1. 开启/上线/开始时间不应误建为截止日程
        body_start1 = "特殊招募预计将于 2026.09.20 18:00 开启"
        deadlines1 = DeadlineParser.parse_deadlines("新角色招募", body_start1, "rec_start1")
        self.assertEqual(len(deadlines1), 0)

        body_start2 = "全新主线剧情将于 2026.09.24 11:00 上线，敬请期待"
        deadlines2 = DeadlineParser.parse_deadlines("主线剧情更新", body_start2, "rec_start2")
        self.assertEqual(len(deadlines2), 0)

        # 2. 明确的截止时间应该正确建立 deadline
        body_deadline = "该兑换码将于 2026.09.25 23:59 截止兑换"
        deadlines3 = DeadlineParser.parse_deadlines("兑换截止", body_deadline, "rec_dl")
        self.assertEqual(len(deadlines3), 1)
        self.assertIsNotNone(deadlines3[0].end_at)

    async def test_official_fetch_error_is_not_recorded_as_sync_success(self):
        from unittest.mock import patch, MagicMock

        service = AnnouncementService()
        self.assertIsNone(service.last_updated_at)

        # 模拟官方接口返回权限错误 (code: 220000)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 220000,
            "code_type": 1,
            "msg": "not permission",
            "data": None,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            success, msg = await service.sync_from_source(service.fetch_official)
            self.assertFalse(success)
            self.assertIn("官方数据同步失败", msg)
            self.assertIn("not permission", msg)
            # 确认未将失败记录为同步成功，且未篡改 last_updated_at
            self.assertIsNone(service.last_updated_at)


class AnnouncementReviewRegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_english_deadline_forms_preserve_word_boundaries(self):
        for word in ("End", "Ends", "Ending"):
            with self.subTest(word=word):
                result = DeadlineParser.parse_deadlines(
                    "Weekend event", f"{word} 2026-09-15 04:59 UTC+9"
                )
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].end_at, datetime(2026, 9, 14, 19, 59, tzinfo=timezone.utc))
        for word in ("Start", "Starts", "Starting", "Open", "Opens", "Opening", "Launch", "Launches", "Launching", "Begin", "Begins", "Beginning", "send", "vendor", "Weekend"):
            with self.subTest(word=word):
                self.assertEqual(DeadlineParser.parse_deadlines(
                    "Weekend event", f"{word} 2026-09-15 04:59 UTC+9"
                ), [])

    async def test_empty_cache_commands_display_sync_errors(self):
        import asyncio
        from unittest.mock import AsyncMock
        from astrbot_plugin_nikke.main import NikkePlugin

        class Event:
            def plain_result(self, text):
                return text

        # 使用真实格式化服务，验证错误能穿过完整命令链到达用户。
        for command in ("announcements_view", "event_schedule"):
            for error in (None, asyncio.TimeoutError(), RuntimeError("测试同步异常")):
                with self.subTest(command=command, error=type(error).__name__):
                    plugin = NikkePlugin.__new__(NikkePlugin)
                    plugin.announcements = AnnouncementService()
                    plugin.announcements.sync_from_source = AsyncMock(
                        return_value=(False, "官方源不可用"), side_effect=error
                    )
                    replies = [reply async for reply in getattr(plugin, command)(Event())]
                    self.assertEqual(len(replies), 1)
                    expected = "官方源不可用" if error is None else "超时" if isinstance(error, asyncio.TimeoutError) else "测试同步异常"
                    self.assertIn(expected, replies[0])
                    self.assertIn("没有可用缓存", replies[0])
                    self.assertNotIn("正在同步", replies[0])
                    plugin.announcements.sync_from_source.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
