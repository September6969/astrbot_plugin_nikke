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
    service = AnnouncementService(data_dir / "announcements")
    delivery = AnnouncementDelivery(store)
    calendar = CalendarService(
        data_dir / "calendar", announcement_service=service
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
