# SPDX-License-Identifier: GPL-3.0-or-later
"""Announcement 和 Calendar 共享状态资源 provider。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...features.announcement.application import AnnouncementApplication
from ...features.announcement.delivery import AnnouncementDelivery
from ...features.announcement.ports import AnnouncementStateStore
from ...features.announcement.service import AnnouncementService
from ...features.calendar.application import CalendarApplication
from ...features.calendar.service import CalendarService
from ...integrations.announcement.information_feeds import InformationFeedsSource
from ...integrations.announcement.official_source import fetch_official_announcements
from ...integrations.blablalink.fetch_client import FetchClient
from ...integrations.calendar.visual_cache import CalendarVisualCache


@dataclass(frozen=True)
class AnnouncementResources:
    """公告服务、日程服务与应用入口的单一共享实例。"""

    service: AnnouncementService
    application: AnnouncementApplication
    calendar: CalendarService
    calendar_application: CalendarApplication


def create_announcement_resources(
    data_dir: Path, *, store: AnnouncementStateStore
) -> AnnouncementResources:
    """组装公告投递和 Calendar 提醒所共享的唯一服务。"""
    service = AnnouncementService(
        data_dir / "announcements",
        source_factory=lambda locale, *, max_pages, page_size: InformationFeedsSource(
            locale, max_pages=max_pages, page_size=page_size
        ),
        official_fetcher=fetch_official_announcements,
    )
    delivery = AnnouncementDelivery(store)
    calendar = CalendarService(
        data_dir / "calendar",
        announcement_service=service,
        fetch_client=FetchClient(),
        visual_cache=CalendarVisualCache(data_dir / "calendar"),
    )
    calendar_application = calendar.application
    application = AnnouncementApplication(
        announcements=service,
        delivery=delivery,
        deadline_selector=calendar_application.reminder_deadlines,
    )
    return AnnouncementResources(
        service, application, calendar, calendar_application
    )
