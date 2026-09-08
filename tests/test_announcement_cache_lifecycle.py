"""公告缓存 last_changed_at 生命周期的行为合同。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from astrbot_plugin_nikke.announcement_models import AnnouncementRecord
from astrbot_plugin_nikke.announcement_service import AnnouncementService


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


class MutableClock:
    """为缓存生命周期测试提供可控的 UTC 时钟。"""

    def __init__(self, current: datetime):
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def record(
    content_id: str,
    *,
    body: str = "正文",
    published_at: str | None = None,
) -> AnnouncementRecord:
    return AnnouncementRecord(
        content_id=content_id,
        title="合成公告",
        body=body,
        published_at=published_at or NOW.isoformat(),
    )


class AnnouncementCacheLifecycleTests(IsolatedAsyncioTestCase):
    def test_version_contract_rejects_silent_numeric_coercion(self) -> None:
        service = AnnouncementService(clock=lambda: NOW)
        for field in ("content_version", "deadline_version"):
            for value in (True, False, 1.5, "2.5", 0, -1):
                with self.subTest(field=field, value=value):
                    item = record(f"{field}-{value!s}")
                    setattr(item, field, value)
                    with self.assertRaises(ValueError):
                        service.add_or_update(item)

    def test_corrupt_cached_versions_are_skipped_without_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "announcements_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "content_id": "float-version",
                                "title": "损坏内容版本",
                                "body": "正文",
                                "published_at": NOW.isoformat(),
                                "content_version": 1.5,
                            },
                            {
                                "content_id": "bool-version",
                                "title": "损坏日程版本",
                                "body": "正文",
                                "published_at": NOW.isoformat(),
                                "deadline_version": True,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            service = AnnouncementService(Path(directory), clock=lambda: NOW)

            self.assertEqual(service.record_count(), 0)

    def test_long_unchanged_record_is_pruned_without_active_deadline(self) -> None:
        clock = MutableClock(NOW - timedelta(days=120))
        service = AnnouncementService(clock=clock)
        service.add_or_update(record("old", published_at=(NOW - timedelta(days=120)).isoformat()))

        clock.current = NOW
        self.assertEqual(service.prune_cache(now=NOW), 1)
        self.assertEqual(service.record_count(), 0)

    async def test_sync_runs_bounded_cache_cleanup(self) -> None:
        clock = MutableClock(NOW - timedelta(days=120))
        service = AnnouncementService(clock=clock)
        service.add_or_update(record("old", published_at=(NOW - timedelta(days=120)).isoformat()))
        clock.current = NOW

        async def empty_source() -> list[AnnouncementRecord]:
            return []

        success, _ = await service.sync_from_source(empty_source)
        self.assertTrue(success)
        self.assertEqual(service.record_count(), 0)

    def test_recently_changed_old_article_survives_prune(self) -> None:
        old_published = (NOW - timedelta(days=120)).isoformat()
        clock = MutableClock(NOW)
        service = AnnouncementService(clock=clock)
        service.add_or_update(record("old", body="版本 A", published_at=old_published))

        clock.current = NOW + timedelta(days=1)
        service.add_or_update(record("old", body="版本 B", published_at=old_published))
        self.assertEqual(service.prune_cache(now=clock.current), 0)
        self.assertEqual(service.record_count(), 1)

    def test_active_deadline_blocks_prune(self) -> None:
        clock = MutableClock(NOW - timedelta(days=120))
        service = AnnouncementService(clock=clock)
        service.add_or_update(
            AnnouncementRecord(
                "active",
                "活动公告",
                "活动时间：2026.09.05 00:00 ~ 2026.09.08 00:00 UTC",
                (NOW - timedelta(days=120)).isoformat(),
            )
        )

        clock.current = NOW
        self.assertEqual(service.prune_cache(now=NOW), 0)
        self.assertEqual(service.record_count(), 1)

    def test_malformed_published_or_changed_time_is_kept(self) -> None:
        service = AnnouncementService(clock=lambda: NOW)
        service.add_or_update(record("bad-published", published_at="not-a-time"))
        service.add_or_update(record("bad-changed", published_at=(NOW - timedelta(days=120)).isoformat()))
        service._last_changed_at["bad-changed"] = "not-a-time"

        self.assertEqual(service.prune_cache(now=NOW + timedelta(days=365)), 0)
        self.assertEqual(service.record_count(), 2)

    def test_legacy_cache_without_last_changed_at_is_migrated_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_file = Path(directory) / "announcements_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "content_id": "legacy",
                                "title": "旧缓存",
                                "body": "正文",
                                "published_at": (NOW - timedelta(days=120)).isoformat(),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = AnnouncementService(Path(directory), clock=lambda: NOW)

            self.assertEqual(service.prune_cache(now=NOW), 0)
            migrated = json.loads(cache_file.read_text(encoding="utf-8"))
            self.assertIsInstance(migrated["records"][0].get("last_changed_at"), str)
            self.assertEqual(AnnouncementService(Path(directory), clock=lambda: NOW).record_count(), 1)

    def test_last_changed_at_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = AnnouncementService(Path(directory), clock=lambda: NOW)
            service.add_or_update(record("same"))
            original = service._last_changed_at["same"]

            restarted = AnnouncementService(
                Path(directory),
                clock=lambda: NOW + timedelta(days=1),
            )
            self.assertEqual(restarted._last_changed_at["same"], original)

    def test_duplicate_fetch_does_not_refresh_last_changed_at(self) -> None:
        clock = MutableClock(NOW)
        service = AnnouncementService(clock=clock)
        first = record("same", body="版本 A")
        service.add_or_update(first)
        original = service._last_changed_at["same"]

        clock.current = NOW + timedelta(days=1)
        self.assertEqual(service.add_or_update(first), (False, False))
        self.assertEqual(service._last_changed_at["same"], original)

    def test_stale_old_revision_does_not_refresh_last_changed_at(self) -> None:
        clock = MutableClock(NOW)
        service = AnnouncementService(clock=clock)
        first = record("same", body="版本 A")
        second = record("same", body="版本 B")
        service.add_or_update(first)

        clock.current = NOW + timedelta(days=1)
        service.add_or_update(second)
        updated = service._last_changed_at["same"]

        clock.current = NOW + timedelta(days=2)
        self.assertEqual(service.add_or_update(first), (False, False))
        self.assertEqual(service._last_changed_at["same"], updated)

    def test_brand_new_fingerprint_refreshes_last_changed_at(self) -> None:
        clock = MutableClock(NOW)
        service = AnnouncementService(clock=clock)
        service.add_or_update(record("same", body="版本 A"))
        original = service._last_changed_at["same"]

        clock.current = NOW + timedelta(days=1)
        service.add_or_update(record("same", body="版本 B"))
        self.assertNotEqual(service._last_changed_at["same"], original)
        self.assertEqual(
            datetime.fromisoformat(service._last_changed_at["same"]),
            clock.current,
        )
