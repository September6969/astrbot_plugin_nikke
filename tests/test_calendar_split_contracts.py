# SPDX-License-Identifier: GPL-3.0-or-later
"""R15 Calendar 协作者边界与共享时间规则合同。"""

from datetime import datetime, timedelta, timezone

from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    EventStatus,
    TimePrecision,
    resolve_event_status,
)
from astrbot_plugin_nikke.features.calendar.merge import CalendarMergePolicy
from astrbot_plugin_nikke.features.calendar.query import CalendarScheduleQueries
from astrbot_plugin_nikke.features.calendar.refresh import CalendarRefreshCoordinator
from astrbot_plugin_nikke.features.calendar.snapshot_repository import CalendarSnapshotRepository
from astrbot_plugin_nikke.features.calendar.time_rules import CalendarEventGroups, CalendarTimeRules
from astrbot_plugin_nikke.features.calendar.models import (
    CalendarActivity,
    TimePrecision as SharedTimePrecision,
)
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _event(event_id: str, start: datetime | None, end: datetime | None, *, precision: str = "EXACT") -> CanonicalEvent:
    return CanonicalEvent(
        id=event_id,
        title=event_id,
        event_type="event",
        start_at=start,
        end_at=end,
        end_precision=precision,
    )


def test_calendar_responsibilities_have_distinct_production_owners():
    assert all((
        CalendarScheduleQueries,
        CalendarRefreshCoordinator,
        CalendarMergePolicy,
        CalendarTimeRules,
        CalendarSnapshotRepository,
    ))


def test_schedule_service_composes_real_calendar_collaborators(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)

    assert isinstance(service.query_service, CalendarScheduleQueries)
    assert isinstance(service.refresh_coordinator, CalendarRefreshCoordinator)
    assert isinstance(service.merge_policy, CalendarMergePolicy)
    assert isinstance(service.snapshot_repository, CalendarSnapshotRepository)


def test_legacy_time_precision_import_is_the_canonical_shared_type():
    assert TimePrecision is SharedTimePrecision
    assert TimePrecision.DATE_ONLY.value == "DATE_ONLY"


def test_activity_and_canonical_status_share_exact_end_boundary():
    activity = CalendarActivity(
        event_id="boundary",
        title="Boundary",
        start_at=NOW - timedelta(hours=1),
        end_at=NOW,
    )
    event = _event("boundary", NOW - timedelta(hours=1), NOW)

    assert resolve_event_status(event, NOW) == EventStatus.ENDED.value
    assert not activity.is_active(NOW)
    assert activity.is_ended(NOW)
    assert activity.remaining_display(NOW) == "已结束"


def test_shared_time_rules_preserve_precision_and_unknown_start_contract():
    exact_soon = _event("exact", NOW - timedelta(hours=1), NOW + timedelta(hours=12))
    date_only = _event(
        "coarse",
        NOW - timedelta(hours=1),
        NOW + timedelta(hours=3),
        precision="DATE_ONLY",
    )
    upcoming = _event("upcoming", NOW + timedelta(days=2), NOW + timedelta(days=3))
    unknown = _event("unknown", None, NOW + timedelta(hours=4))

    groups = CalendarTimeRules.classify_events(
        [exact_soon, date_only, upcoming, unknown], NOW, horizon_days=7
    )

    assert isinstance(groups, CalendarEventGroups)
    assert [event.id for event in groups.ending_soon] == ["exact"]
    assert [event.id for event in groups.active] == ["coarse"]
    assert [event.id for event in groups.active_including_soon] == ["exact", "coarse"]
    assert [event.id for event in groups.upcoming] == ["upcoming"]
    assert [event.id for event in CalendarTimeRules.reminder_deadlines(
        [exact_soon, date_only, upcoming, unknown], NOW
    )] == ["exact"]


def test_shared_horizon_validation_has_one_supported_contract():
    assert CalendarTimeRules.normalize_horizon(None) == 14
    assert CalendarTimeRules.normalize_horizon("7") == 7
    for invalid in (True, 0, " 7x "):
        try:
            CalendarTimeRules.normalize_horizon(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unexpected accepted horizon: {invalid!r}")
