from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_nikke.features.calendar.application import CalendarApplication


NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


def test_hot_schedule_query_freezes_local_snapshot_without_syncing_network():
    query_context = SimpleNamespace(now=NOW, events=())
    calendar = Mock()
    calendar.normalize_horizon.return_value = 7
    calendar.freeze_query_context.return_value = query_context
    calendar.has_snapshot.return_value = True
    calendar.refresh_schedule_data = AsyncMock()
    calendar.sync_from_source = AsyncMock()
    calendar.visual_cache.sync = AsyncMock()
    calendar.cached_visual_event_ids.return_value = ()

    application = CalendarApplication(calendar, clock=lambda: NOW)

    snapshot = application.query_schedule("7")

    assert snapshot.context is query_context
    assert snapshot.horizon_days == 7
    assert snapshot.has_snapshot is True
    calendar.freeze_query_context.assert_called_once_with(NOW)
    calendar.refresh_schedule_data.assert_not_awaited()
    calendar.sync_from_source.assert_not_awaited()
    calendar.visual_cache.sync.assert_not_awaited()


def test_schedule_snapshot_uses_one_query_context_for_text_fallback():
    query_context = SimpleNamespace(now=NOW, events=())
    calendar = Mock()
    calendar.normalize_horizon.return_value = 14
    calendar.freeze_query_context.return_value = query_context
    calendar.has_snapshot.return_value = True
    calendar.last_sync_error = ""
    calendar.format_schedule_text.return_value = "同一快照文本回退"
    calendar.cached_visual_event_ids.return_value = ()

    application = CalendarApplication(calendar, clock=lambda: NOW)

    snapshot = application.query_schedule(14)

    calendar.format_schedule_text.assert_called_once_with(
        14, NOW, "", context=query_context
    )
    assert snapshot.fallback_text == "同一快照文本回退"
    calendar.freeze_query_context.assert_called_once_with(NOW)


def test_background_only_uses_current_or_upcoming_event_visuals(tmp_path):
    # PR-6B G5-calendar-e：背景只从当前与即将开始的日程事件中选择（文档规则），
    # 视觉缓存清单中已结束活动的旧图不再作为回退背景。
    from datetime import timedelta
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
    from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService

    ended_image = tmp_path / "ended.webp"
    ended_image.write_bytes(b"ended")
    upcoming_image = tmp_path / "upcoming.webp"
    upcoming_image.write_bytes(b"upcoming")

    class Visuals:
        files = {"ended": ended_image}

        def resolve_path(self, event_id):
            return self.files.get(event_id)

        def cached_event_ids(self):
            return tuple(self.files)

        async def sync(self, activities, **kwargs):
            return {}

    visuals = Visuals()
    service = ScheduleService(tmp_path / "calendar", visual_cache=visuals)

    def event(key, start, end):
        return CanonicalEvent(id=key, title=key, event_type="story_event", start_at=start, end_at=end,
                              primary_source="blabla", sources=["blabla"])

    service._events = {
        "ended": event("ended", NOW - timedelta(days=5), NOW - timedelta(days=1)),
        "active": event("active", NOW - timedelta(days=1), NOW + timedelta(days=3)),
        "upcoming": event("upcoming", NOW + timedelta(days=2), NOW + timedelta(days=6)),
    }
    service._has_snapshot = True
    application = CalendarApplication(service, clock=lambda: NOW)

    assert application.query_schedule(14).background_path is None
    visuals.files["upcoming"] = upcoming_image
    assert application.query_schedule(14).background_path == upcoming_image
