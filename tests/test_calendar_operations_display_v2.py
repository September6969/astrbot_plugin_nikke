# SPDX-License-Identifier: GPL-3.0-or-later
"""Operations Feed v2 分类组与展示顺序行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from astrbot_plugin_nikke.features.calendar.content_quality import (
    operations_display_group,
    sort_operations_display_events,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _event(
    event_id: str,
    category: str,
    *,
    start_offset: int = 0,
    end_offset: int = 1,
    end_precision: str = "EXACT",
):
    return SimpleNamespace(
        id=event_id,
        identity_key=f"GLOBAL:gamekee:{event_id}",
        event_type=category,
        start_at=NOW + timedelta(hours=start_offset),
        end_at=NOW + timedelta(hours=end_offset),
        start_precision="EXACT",
        end_precision=end_precision,
        title=f"{category} {event_id}",
        metadata={},
        primary_source="gamekee",
        sources=["gamekee"],
    )


def test_operations_display_groups_keep_meta_last_and_preserve_unknown_content():
    assert operations_display_group("event") == 0
    assert operations_display_group("recruit") == 1
    assert operations_display_group("costume_gacha") == 2
    assert operations_display_group("limited_costume") == 3
    assert operations_display_group("maintenance") == 4
    assert operations_display_group("future_category") == 0


def test_active_sort_groups_then_exact_end_date_only_unknown_and_relevance():
    events = [
        _event("meta", "announcement", end_offset=1),
        _event("costume", "costume_gacha", end_offset=2),
        _event("activity-late", "event", end_offset=4),
        _event("recruit", "recruit", end_offset=3),
        _event("activity-date-only", "event", end_offset=1, end_precision="DATE_ONLY"),
        _event("limited", "limited_costume", end_offset=5),
        _event("activity-unknown", "pass", end_offset=0, end_precision="UNKNOWN"),
        _event("activity-early", "event", end_offset=2),
    ]

    ordered = sort_operations_display_events(events, "ACTIVE")

    assert [event.id for event in ordered] == [
        "activity-early",
        "activity-late",
        "activity-date-only",
        "activity-unknown",
        "recruit",
        "costume",
        "limited",
        "meta",
    ]


def test_upcoming_sort_groups_then_start_time_and_stable_identity():
    events = [
        _event("recruit-late", "recruit", start_offset=4),
        _event("event-late", "event", start_offset=4),
        _event("event-early", "event", start_offset=1),
        _event("meta-early", "update", start_offset=0),
        _event("costume-early", "costume_gacha", start_offset=0),
        _event("limited-early", "limited_costume", start_offset=0),
    ]

    ordered = sort_operations_display_events(events, "UPCOMING")

    assert [event.id for event in ordered] == [
        "event-early",
        "event-late",
        "recruit-late",
        "costume-early",
        "limited-early",
        "meta-early",
    ]
