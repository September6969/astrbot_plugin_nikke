# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for Calendar Operations Feed T2I payload and template."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.features.calendar.models import CalendarActivity
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.ui.t2i_payloads import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def test_active_sorting_end_at_earlier_first(tmp_path):
    service = CalendarService(tmp_path)
    service._has_snapshot = True

    # Three active events with different end times
    ev1 = CalendarActivity("e1", "Event Later", NOW - timedelta(days=1), NOW + timedelta(days=5), category="event")
    ev2 = CalendarActivity("e2", "Event Earliest", NOW - timedelta(days=1), NOW + timedelta(hours=3), category="coop")
    ev3 = CalendarActivity("e3", "Event Middle", NOW - timedelta(days=1), NOW + timedelta(days=2), category="solo_raid")

    service._activities = {ev1.event_id: ev1, ev2.event_id: ev2, ev3.event_id: ev3}

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    assert payload["active_count"] == 3
    titles = [item["title"] for item in payload["active_items"]]
    assert titles == ["Event Earliest", "Event Middle", "Event Later"]


def test_next_ending_only_first_active_is_true(tmp_path):
    service = CalendarService(tmp_path)
    service._has_snapshot = True

    ev1 = CalendarActivity("e1", "Event 1", NOW - timedelta(days=1), NOW + timedelta(hours=4), category="coop")
    ev2 = CalendarActivity("e2", "Event 2", NOW - timedelta(days=1), NOW + timedelta(days=1), category="union_raid")
    ev3 = CalendarActivity("e3", "Event 3", NOW - timedelta(days=1), NOW + timedelta(days=3), category="event")

    service._activities = {ev1.event_id: ev1, ev2.event_id: ev2, ev3.event_id: ev3}

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    items = payload["active_items"]
    assert items[0]["is_next_ending"] is True
    assert items[1]["is_next_ending"] is False
    assert items[2]["is_next_ending"] is False


@pytest.mark.parametrize("delta,expected_urgency", [
    (timedelta(minutes=30), "CRITICAL"),
    (timedelta(hours=1), "CRITICAL"),
    (timedelta(hours=1, seconds=1), "URGENT"),
    (timedelta(hours=5), "URGENT"),
    (timedelta(hours=6), "URGENT"),
    (timedelta(hours=6, seconds=1), "CLOSING"),
    (timedelta(hours=23), "CLOSING"),
    (timedelta(hours=24), "CLOSING"),
    (timedelta(hours=24, seconds=1), "NORMAL"),
    (timedelta(days=3), "NORMAL"),
])
def test_urgency_boundaries(tmp_path, delta, expected_urgency):
    service = CalendarService(tmp_path)
    service._has_snapshot = True

    ev = CalendarActivity("e1", "Boundary Test", NOW - timedelta(days=1), NOW + delta, category="event")
    service._activities = {ev.event_id: ev}

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    assert len(payload["active_items"]) == 1
    assert payload["active_items"][0]["urgency"] == expected_urgency


def test_legacy_ui_and_progress_elements_completely_removed(tmp_path):
    service = CalendarService(tmp_path)
    service._has_snapshot = True
    service.last_updated_at = NOW.isoformat()

    ev_active = CalendarActivity("e1", "Active Op", NOW - timedelta(days=1), NOW + timedelta(hours=5), category="coop")
    ev_upcoming = CalendarActivity("e2", "Next Op", NOW + timedelta(days=2), NOW + timedelta(days=7), category="solo_raid")
    service._activities = {ev_active.event_id: ev_active, ev_upcoming.event_id: ev_upcoming}

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)

    # Verify payload does not contain legacy keys
    forbidden_payload_keys = {"groups", "ending_soon", "active", "upcoming", "progress_percent", "progress_label", "is_upcoming", "horizon_days"}
    for key in forbidden_payload_keys:
        assert key not in payload, f"Legacy key '{key}' still found in payload"

    html = Environment().from_string(T2ITemplateLoader().load("calendar_schedule")).render(**payload)

    # Verify HTML does not contain legacy UI strings or classes
    forbidden_html_tokens = [
        "ENDING SOON",
        "即将结束",
        "ACTIVE / 进行中",
        "UPCOMING",
        "即将开始",
        "14 DAYS",
        "7 DAYS",
        "30 DAYS",
        "progress-bar",
        "progress-track",
        "progress-wrap",
        "progress_percent",
        "progress_label",
    ]
    for token in forbidden_html_tokens:
        assert token not in html, f"Legacy token '{token}' still found in rendered HTML"


def test_empty_active_with_upcoming_shows_both(tmp_path):
    service = CalendarService(tmp_path)
    service._has_snapshot = True

    # No active operations, only upcoming
    ev_upcoming = CalendarActivity("e1", "Future Raid", NOW + timedelta(days=2), NOW + timedelta(days=5), category="union_raid")
    service._activities = {ev_upcoming.event_id: ev_upcoming}

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    assert payload["has_active"] is False
    assert payload["has_upcoming"] is True
    assert payload["active_count"] == 0
    assert len(payload["next_items"]) == 1

    html = Environment().from_string(T2ITemplateLoader().load("calendar_schedule")).render(**payload)
    assert "NO ACTIVE OPERATIONS" in html
    assert "当前无进行中的活动" in html
    assert "NEXT OPERATIONS" in html
    assert "Future Raid" in html


def test_unavailable_snapshot_shows_unavailable_state(tmp_path):
    service = CalendarService(tmp_path)
    service._has_snapshot = False

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    assert payload["available"] is False
    assert payload["data_quality"] == "UNAVAILABLE"
    assert payload["source_display"] == "SCHEDULE DATA UNAVAILABLE"

    html = Environment().from_string(T2ITemplateLoader().load("calendar_schedule")).render(**payload)
    assert "SCHEDULE DATA UNAVAILABLE" in html


def test_time_precision_formatting_date_only_vs_exact(tmp_path):
    # Exact event
    exact_event = CanonicalEvent(
        id="c1",
        title="Exact Operation",
        event_type="coop",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(hours=3, minutes=24),
        time_precision="EXACT",
    )
    # Date only event
    date_only_event = CanonicalEvent(
        id="c2",
        title="Date Only Operation",
        event_type="event",
        start_at=NOW - timedelta(days=2),
        end_at=NOW + timedelta(days=3),
        time_precision="DATE_ONLY",
    )

    class MockService:
        def __init__(self, events):
            self._events = events
            self.last_updated_at = NOW.isoformat()
            self.last_sync_error = ""
            self.data_quality = "FRESH"
        def has_snapshot(self):
            return True
        def list_canonical(self):
            return list(self._events.values())
        def list_activities(self):
            return [e.to_calendar_activity() for e in self._events.values()]
        def normalize_horizon(self, d):
            return d
        def format_schedule_text(self, *args, **kwargs):
            return ""

    service = MockService({"c1": exact_event, "c2": date_only_event})

    payload = CalendarT2IPayloadBuilder().build(service, days=14, now=NOW)
    items = {item["title"]: item for item in payload["active_items"]}

    assert items["Exact Operation"]["remaining"] == "03H 24M"
    assert "→" in items["Exact Operation"]["time_range_display"]
    assert ":" in items["Exact Operation"]["start"]

    assert "截止" in items["Date Only Operation"]["remaining"]
    assert ":" not in items["Date Only Operation"]["remaining"]
