"""Announcement V2 的范围、版本、重扫与查询行为回归。"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from astrbot_plugin_nikke.announcement_delivery import AnnouncementDelivery
from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
from astrbot_plugin_nikke.announcement_sources import InformationFeedsSource
from astrbot_plugin_nikke.announcement_service import AnnouncementService
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.storage import NikkeStore


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def record(
    identifier: str,
    title: str = "合成公告",
    body: str = "正文",
    *,
    published_at: datetime = NOW,
    locale: str = "en",
    category: str = "general",
) -> AnnouncementRecord:
    return AnnouncementRecord(
        identifier,
        title,
        body,
        published_at.isoformat(),
        locale=locale,
        category=category,
    )


class AnnouncementV2ServiceTests(IsolatedAsyncioTestCase):
    def test_record_contract_rejects_non_text_core_fields(self) -> None:
        service = AnnouncementService()
        invalid_records = [
            AnnouncementRecord(None, "标题", "正文", NOW.isoformat()),
            AnnouncementRecord("   ", "标题", "正文", NOW.isoformat()),
            AnnouncementRecord("none", "标题", "正文", NOW.isoformat()),
            AnnouncementRecord("valid", None, "正文", NOW.isoformat()),
            AnnouncementRecord("valid", "标题", None, NOW.isoformat()),
            AnnouncementRecord("valid", "标题", "正文", None),
        ]
        for invalid in invalid_records:
            with self.subTest(record=invalid):
                with self.assertRaises(ValueError):
                    service.add_or_update(invalid)

    async def test_deep_fetch_primary_does_not_use_legacy_fallback(self) -> None:
        with patch(
            "astrbot_plugin_nikke.announcement_sources.InformationFeedsSource.fetch",
            new=AsyncMock(side_effect=RuntimeError("主源不可用")),
        ), patch.object(
            AnnouncementService,
            "fetch_official",
            new=AsyncMock(return_value=[]),
        ) as legacy:
            with self.assertRaises(RuntimeError):
                await AnnouncementService.fetch_primary(locale="ja", deep=True)
            legacy.assert_not_awaited()

    async def test_deep_rescan_reports_bounded_scope_and_locale(self) -> None:
        service = AnnouncementService()

        async def fetcher() -> list[AnnouncementRecord]:
            return [record("a", locale="ja"), record("b", locale="ja", category="maintenance")]

        success, message = await service.sync_from_source(fetcher, locale="ja", deep=True)

        self.assertTrue(success)
        self.assertIn("重扫成功", message)
        self.assertEqual(service.last_sync_report["locale"], "ja")
        self.assertTrue(service.last_sync_report["deep"])
        self.assertEqual(service.last_sync_report["received"], 2)
        self.assertEqual(service.last_sync_report["new"], 2)
        diagnostic = service.format_diagnostic_text()
        self.assertIn("深度重扫", diagnostic)
        self.assertIn("ja: 2", diagnostic)
        self.assertNotIn("正文", diagnostic)

    async def test_source_bounds_and_legacy_fallback_keep_all_records(self) -> None:
        source = InformationFeedsSource("ja", max_pages=5, page_size=20)
        self.assertEqual((source.max_pages, source.page_size), (5, 20))
        with self.assertRaises(ValueError):
            InformationFeedsSource("ja", max_pages=6)
        with self.assertRaises(ValueError):
            InformationFeedsSource("ja", page_size=21)

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "api.blablalink.com")
            return httpx.Response(200, json={
                "code": 0,
                "data": {"list": [
                    {"id": "a", "title": "甲", "content": "正文甲", "publish_time": "2026-09-01"},
                    {"id": "b", "title": "乙", "content": "正文乙", "publish_time": "2026-09-02"},
                ]},
            })

        real_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        with patch("astrbot_plugin_nikke.announcement_service.httpx.AsyncClient", client_factory):
            records = await AnnouncementService.fetch_official()
        self.assertEqual([item.content_id for item in records], ["a", "b"])
        self.assertEqual([item.locale for item in records], ["und", "und"])

    async def test_duplicate_fetch_and_seen_old_revision_do_not_roll_back(self) -> None:
        service = AnnouncementService()
        first = record("same", body="版本 A")
        second = record("same", body="版本 B")

        service.add_or_update(first)
        service.add_or_update(second)
        self.assertEqual(service.list_announcements()[0].content_version, 2)
        self.assertEqual(service.list_announcements()[0].body, "版本 B")

        async def replay() -> list[AnnouncementRecord]:
            return [first, first]

        success, _ = await service.sync_from_source(replay)
        self.assertTrue(success)
        current = service.list_announcements()[0]
        self.assertEqual(current.body, "版本 B")
        self.assertEqual(current.content_version, 2)
        self.assertEqual(service.last_sync_report["stale"], 2)

    async def test_cleanup_then_rescan_restores_cache_without_implying_delivery(self) -> None:
        service = AnnouncementService(clock=lambda: NOW - timedelta(days=120))
        old = record("old", body="旧公告", published_at=NOW - timedelta(days=120))
        service.add_or_update(old)
        self.assertEqual(service.prune_cache(now=NOW), 1)
        self.assertEqual(service.record_count(), 0)

        async def rescan() -> list[AnnouncementRecord]:
            return [old]

        success, _ = await service.sync_from_source(rescan)
        self.assertTrue(success)
        self.assertEqual(service.record_count(), 1)
        self.assertEqual(service.last_sync_report["new"], 1)

    def test_revision_history_survives_restart_and_cache_cleanup_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_clock = lambda: NOW - timedelta(days=120)
            service = AnnouncementService(Path(directory), clock=old_clock)
            old = record("same", body="版本 A", published_at=NOW - timedelta(days=120))
            current = record("same", body="版本 B", published_at=NOW - timedelta(days=120))
            active = record(
                "active",
                body="活动时间：2026.05.01 00:00 ~ 2026.12.01 00:00 UTC",
                published_at=NOW - timedelta(days=120),
            )
            service.add_or_update(old)
            service.add_or_update(current)
            service.add_or_update(active)
            service = AnnouncementService(Path(directory), clock=old_clock)

            self.assertEqual(service.add_or_update(old), (False, False))
            restored = next(item for item in service.list_announcements(limit=10) if item.content_id == "same")
            self.assertEqual(restored.body, "版本 B")
            self.assertEqual(service.prune_cache(now=NOW), 1)
            self.assertEqual(service.record_count(), 1)
            self.assertEqual(service.list_announcements()[0].content_id, "active")


class AnnouncementV2QueryAndDeliveryTests(IsolatedAsyncioTestCase):
    async def test_locale_category_query_and_diagnostic_do_not_fetch_or_send(self) -> None:
        service = AnnouncementService()
        service.add_or_update(record("ja", "维护告知", "维护正文", locale="ja", category="maintenance"))
        service.add_or_update(record("en", "Event Notice", "Event body", locale="en", category="event"))
        service.sync_from_source = AsyncMock(side_effect=AssertionError("本地查询不应同步"))
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.announcements = service
        plugin.announcement_delivery = SimpleNamespace(dispatch=AsyncMock())
        event = SimpleNamespace(plain_result=lambda text: text, is_admin=lambda: False)

        locale_reply = [item async for item in plugin.nikke(event, "公告", "语言", "ja")]
        category_reply = [item async for item in plugin.nikke(event, "公告", "分类", "活动")]
        query_reply = [item async for item in plugin.nikke(event, "公告", "搜索", "维护")]
        diagnostic_reply = [item async for item in plugin.nikke(event, "公告", "诊断")]

        self.assertIn("维护告知", locale_reply[0])
        self.assertNotIn("Event Notice", locale_reply[0])
        self.assertIn("Event Notice", category_reply[0])
        self.assertIn("维护告知", query_reply[0])
        self.assertIn("公开只读", diagnostic_reply[0])
        service.sync_from_source.assert_not_awaited()
        plugin.announcement_delivery.dispatch.assert_not_awaited()

    async def test_deep_rescan_requires_admin_and_resubscribe_never_replays_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AnnouncementService()
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.announcements = service
            plugin.announcement_delivery = SimpleNamespace()
            service.sync_from_source = AsyncMock(return_value=(True, "同步成功"))
            denied = SimpleNamespace(plain_result=lambda text: text, is_admin=lambda: False)
            denied_reply = [item async for item in plugin.nikke(denied, "公告", "深度刷新", "ja")]
            self.assertIn("仅机器人管理员", denied_reply[0])
            service.sync_from_source.assert_not_awaited()

            allowed = SimpleNamespace(plain_result=lambda text: text, is_admin=lambda: True)
            allowed_reply = [item async for item in plugin.nikke(allowed, "公告", "深度刷新", "ja")]
            self.assertIn("公开只读", allowed_reply[0])
            service.sync_from_source.assert_awaited_once_with(locale="ja", deep=True)

            delivery = AnnouncementDelivery(NikkeStore(directory))
            v1 = record("old", body="版本 1", published_at=NOW - timedelta(days=30))
            delivery.subscribe("target", [v1], now=NOW - timedelta(days=1))
            delivery.unsubscribe("target")
            v2 = record("old", body="版本 2", published_at=NOW - timedelta(days=30))
            v2.content_version = 2
            delivery.subscribe("target", [v2], now=NOW)
            self.assertEqual(delivery.plan([v2], now=NOW), [])
            v3 = record("old", body="版本 3", published_at=NOW - timedelta(days=30))
            v3.content_version = 3
            self.assertEqual(len(delivery.plan([v3], now=NOW)), 1)


class AnnouncementV2DeliveryRetentionTests(IsolatedAsyncioTestCase):
    async def test_old_article_upgrade_survives_delivery_cleanup_without_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            delivery = AnnouncementDelivery(NikkeStore(directory))
            old_time = NOW - timedelta(days=120)
            v1 = record("old", body="版本 1", published_at=old_time)
            delivery.subscribe("existing", [v1], now=old_time)
            v2 = record("old", body="版本 2", published_at=old_time)
            v2.content_version = 2
            self.assertEqual(len(delivery.plan([v2], now=NOW)), 1)
            await delivery.dispatch([v2], [], AsyncMock(return_value=True), now=NOW)
            state = delivery._state()
            for delivered in state["delivered"].values():
                delivered["pushed_at"] = (NOW - timedelta(days=100)).isoformat()
            delivery.store.set_setting(delivery.SETTING, state)
            self.assertEqual(delivery.cleanup(now=NOW), 1)
            self.assertEqual(delivery.plan([v2], now=NOW), [])
            delivery.subscribe("new", [v2], now=NOW)
            self.assertEqual(delivery.plan([v2], now=NOW), [])
            v3 = record("old", body="版本 3", published_at=old_time)
            v3.content_version = 3
            self.assertEqual(
                [push.target for push in delivery.plan([v3], now=NOW)],
                ["existing", "new"],
            )
