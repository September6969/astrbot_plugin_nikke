from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.announcement.application import AnnouncementApplication
from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery
from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord
from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.integrations.announcement.information_feeds import InformationFeedsSource


def test_delivery_coordination_limit_is_explicitly_process_local():
    assert AnnouncementApplication.SINGLE_INSTANCE_ONLY is True
    assert "no cross-process dispatch lock" in AnnouncementApplication.EXECUTION_SCOPE


@pytest.mark.asyncio
async def test_cached_announcement_query_does_not_fetch_and_preserves_filters():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    announcements = AnnouncementService(
        clock=lambda: now,
        source_factory=lambda locale, *, max_pages, page_size: InformationFeedsSource(
            locale, max_pages=max_pages, page_size=page_size
        ),
    )
    announcements.add_or_update(
        AnnouncementRecord(
            "ja:maintenance",
            "メンテナンスのお知らせ",
            "ja body",
            now.isoformat(),
            locale="ja",
            category="maintenance",
        )
    )
    announcements.add_or_update(
        AnnouncementRecord(
            "en:event",
            "Event notice",
            "en body",
            now.isoformat(),
            locale="en",
            category="event",
        )
    )

    with tempfile.TemporaryDirectory() as directory, patch(
        "astrbot_plugin_nikke.integrations.announcement.information_feeds.InformationFeedsSource.fetch",
        new=AsyncMock(return_value=[]),
    ) as fetch:
        application = AnnouncementApplication(
            announcements=announcements,
            delivery=AnnouncementDelivery(NikkeStore(directory)),
        )

        text = await application.view_announcements(locale="ja")

    fetch.assert_not_awaited()
    assert "メンテナンスのお知らせ" in text
    assert "Event notice" not in text


@pytest.mark.asyncio
async def test_deep_rescan_returns_public_sync_result_without_dispatching():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    announcements = AnnouncementService(
        clock=lambda: now,
        source_factory=lambda locale, *, max_pages, page_size: InformationFeedsSource(
            locale, max_pages=max_pages, page_size=page_size
        ),
    )
    refreshed = AnnouncementRecord(
        "ja:new",
        "新しいお知らせ",
        "本文",
        now.isoformat(),
        locale="ja",
        category="general",
    )

    with tempfile.TemporaryDirectory() as directory, patch(
        "astrbot_plugin_nikke.integrations.announcement.information_feeds.InformationFeedsSource.fetch",
        new=AsyncMock(return_value=[refreshed]),
    ) as fetch:
        delivery = AnnouncementDelivery(NikkeStore(directory))
        application = AnnouncementApplication(
            announcements=announcements,
            delivery=delivery,
        )

        result = await application.deep_rescan("ja")

    assert result.success is True
    assert "重扫成功" in result.message
    assert announcements.last_sync_report["locale"] == "ja"
    assert announcements.last_sync_report["deep"] is True
    assert announcements.record_count() == 1
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_delivery_is_reported_and_not_replayed_by_application(caplog):
    announcements = AnnouncementService()
    with tempfile.TemporaryDirectory() as directory:
        application = AnnouncementApplication(
            announcements=announcements,
            delivery=AnnouncementDelivery(NikkeStore(directory)),
        )
        application.set_subscription("fake:group:1", enabled=True)
        now = datetime.now(timezone.utc)
        announcements.add_or_update(
            AnnouncementRecord(
                "new-item",
                "New official notice",
                "body",
                now.isoformat(),
            )
        )
        uncertain_sender = AsyncMock(side_effect=TimeoutError("response lost"))

        first = await application.dispatch_pushes(uncertain_sender, now=now)
        retry_sender = AsyncMock(return_value=True)
        second = await application.dispatch_pushes(retry_sender, now=now)

    assert first.unknown == 1
    assert first.succeeded == 0
    assert second.unknown == 0
    assert second.succeeded == 0
    uncertain_sender.assert_awaited_once()
    retry_sender.assert_not_awaited()
    assert "公告投递结果未知" in caplog.text
    assert "fake:group:1" not in caplog.text
    assert "New official notice" not in caplog.text


@pytest.mark.asyncio
async def test_single_application_serializes_overlapping_push_batches():
    announcements = AnnouncementService()
    with tempfile.TemporaryDirectory() as directory:
        application = AnnouncementApplication(
            announcements=announcements,
            delivery=AnnouncementDelivery(NikkeStore(directory)),
        )
        application.set_subscription("fake:group:1", enabled=True)
        now = datetime.now(timezone.utc)
        announcements.add_or_update(
            AnnouncementRecord(
                "concurrent-item",
                "Concurrent notice",
                "body",
                now.isoformat(),
            )
        )
        sender_entered = asyncio.Event()
        release_sender = asyncio.Event()
        sender = AsyncMock()

        async def send_once(target: str, text: str) -> bool:
            sender_entered.set()
            await release_sender.wait()
            return True

        sender.side_effect = send_once
        first = asyncio.create_task(application.dispatch_pushes(sender, now=now))
        await sender_entered.wait()
        second = asyncio.create_task(application.dispatch_pushes(sender, now=now))
        await asyncio.sleep(0)
        release_sender.set()
        results = await asyncio.gather(first, second)

    assert sender.await_count == 1
    assert sum(result.succeeded for result in results) == 1
