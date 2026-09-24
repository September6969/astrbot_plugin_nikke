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
