from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_nikke.application.commands.calendar import CalendarCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    ImageReply,
    TextReply,
)
from astrbot_plugin_nikke.features.calendar.application import CalendarScheduleSnapshot
from astrbot_plugin_nikke.features.calendar.application import CalendarRefreshResult
from astrbot_plugin_nikke.main import NikkePlugin


@pytest.mark.asyncio
async def test_hot_query_uses_cached_payload_and_text_fallback_without_refresh():
    snapshot = CalendarScheduleSnapshot(
        context=object(),
        horizon_days=7,
        has_snapshot=True,
        activity_count=1,
        data_quality="DATA OK",
        last_updated_at=None,
        sync_warning="",
        fallback_text="缓存日程回退",
    )
    application = Mock()
    application.query_schedule.return_value = snapshot
    application.refresh_schedule = AsyncMock()
    builder = Mock()
    builder.build.return_value = {"fallback_text": snapshot.fallback_text}
    render = AsyncMock(return_value=None)
    start_background_refresh = Mock()
    handler = CalendarCommandHandler(
        application=application,
        payload_builder=builder,
        render=render,
        start_background_refresh=start_background_refresh,
    )

    result = await handler.handle(
        CommandContext(parameters={"horizon": "7"})
    )

    application.query_schedule.assert_called_once_with("7")
    application.refresh_schedule.assert_not_awaited()
    builder.build.assert_called_once_with(snapshot)
    render.assert_awaited_once_with(builder.build.return_value)
    start_background_refresh.assert_not_called()
    assert result.messages == (TextReply("缓存日程回退"),)


@pytest.mark.asyncio
async def test_explicit_refresh_reports_application_result_without_building_payload():
    application = Mock()
    application.refresh_schedule = AsyncMock(
        return_value=CalendarRefreshResult(
            success=False,
            message="源站超时，旧快照保留",
            activity_count=4,
            data_quality="STALE",
        )
    )
    builder = Mock()
    render = AsyncMock()
    start_background_refresh = Mock()
    handler = CalendarCommandHandler(
        application=application,
        payload_builder=builder,
        render=render,
        start_background_refresh=start_background_refresh,
    )

    result = await handler.handle(
        CommandContext(parameters={"horizon": "刷新"})
    )

    application.refresh_schedule.assert_awaited_once_with()
    application.query_schedule.assert_not_called()
    builder.build.assert_not_called()
    render.assert_not_awaited()
    start_background_refresh.assert_not_called()
    assert "失败（已保留旧快照）" in result.messages[0].text
    assert "当前活动条目数：4" in result.messages[0].text
    assert "源站超时，旧快照保留" in result.messages[0].text


@pytest.mark.asyncio
async def test_missing_snapshot_schedules_background_refresh_without_rendering():
    snapshot = CalendarScheduleSnapshot(
        context=object(),
        horizon_days=14,
        has_snapshot=False,
        activity_count=0,
        data_quality="SCHEDULE DATA UNAVAILABLE",
        last_updated_at=None,
        sync_warning="",
    )
    application = Mock()
    application.query_schedule.return_value = snapshot
    builder = Mock()
    render = AsyncMock()
    start_background_refresh = Mock()
    handler = CalendarCommandHandler(
        application=application,
        payload_builder=builder,
        render=render,
        start_background_refresh=start_background_refresh,
    )

    result = await handler.handle(CommandContext())

    assert "正在后台同步" in result.messages[0].text
    start_background_refresh.assert_called_once_with()
    builder.build.assert_not_called()
    render.assert_not_awaited()


@pytest.mark.asyncio
async def test_page_command_renders_the_requested_calendar_page_without_refresh():
    snapshot = CalendarScheduleSnapshot(
        context=object(),
        horizon_days=14,
        has_snapshot=True,
        activity_count=2,
        data_quality="DATA OK",
        last_updated_at=None,
        sync_warning="",
        fallback_text="全局文本回退",
    )
    page_one = {
        "page_number": 1,
        "page_total": 2,
        "active_items": [{"event_id": "event-1", "full_title": "第一项", "time_range": "10.20"}],
        "next_items": [],
    }
    page_two = {
        "page_number": 2,
        "page_total": 2,
        "active_items": [],
        "next_items": [{"event_id": "event-2", "full_title": "第二项", "time_range": "10.21"}],
    }
    application = Mock()
    application.query_schedule.return_value = snapshot
    application.refresh_schedule = AsyncMock()
    builder = Mock()
    builder.build.return_value = {
        "pages": [page_one, page_two],
        "horizon_days": 14,
        "page_total": 2,
        "fallback_text": snapshot.fallback_text,
    }
    render = AsyncMock(return_value="calendar-page-2.png")
    start_background_refresh = Mock()
    handler = CalendarCommandHandler(
        application=application,
        payload_builder=builder,
        render=render,
        start_background_refresh=start_background_refresh,
    )

    result = await handler.handle(CommandContext(parameters={"horizon": "14", "page": "2"}))

    application.query_schedule.assert_called_once_with("14")
    application.refresh_schedule.assert_not_awaited()
    builder.build.assert_called_once_with(snapshot)
    start_background_refresh.assert_not_called()
    render.assert_awaited_once()
    rendered_payload = render.await_args.args[0]
    assert rendered_payload["page_number"] == 2
    assert rendered_payload["pages"] == [page_two]
    assert rendered_payload["active_items"] == []
    assert rendered_payload["next_items"] == page_two["next_items"]
    assert "第二项" in rendered_payload["fallback_text"]
    assert result.messages == (ImageReply("calendar-page-2.png"),)


@pytest.mark.asyncio
async def test_calendar_page_out_of_range_returns_text_without_rendering():
    snapshot = CalendarScheduleSnapshot(
        context=object(),
        horizon_days=14,
        has_snapshot=True,
        activity_count=1,
        data_quality="DATA OK",
        last_updated_at=None,
        sync_warning="",
        fallback_text="回退文本",
    )
    application = Mock()
    application.query_schedule.return_value = snapshot
    application.refresh_schedule = AsyncMock()
    builder = Mock()
    builder.build.return_value = {"pages": [{"page_number": 1}], "fallback_text": "回退文本"}
    render = AsyncMock()
    handler = CalendarCommandHandler(
        application=application,
        payload_builder=builder,
        render=render,
        start_background_refresh=Mock(),
    )

    result = await handler.handle(CommandContext(parameters={"horizon": "14", "page": "2"}))

    assert "页码超出范围" in result.messages[0].text
    application.refresh_schedule.assert_not_awaited()
    render.assert_not_awaited()


def test_main_calendar_route_does_not_read_schedule_service_or_model_fields():
    from astrbot_plugin_nikke.main import NikkePlugin

    method = getattr(NikkePlugin, "event_schedule")
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    forbidden_names = {
        "has_snapshot",
        "activity_count",
        "data_quality",
        "refresh_schedule_data",
        "sync_from_source",
        "list_reminder_deadlines",
        "CalendarT2IPayloadBuilder",
    }
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found.update(node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute))
    assert not (found & forbidden_names)


def test_calendar_pagination_payload_is_owned_by_page_module():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "ui" / "t2i_payloads.py").exists()
    from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder

    assert CalendarT2IPayloadBuilder.__module__ == "astrbot_plugin_nikke.ui.payloads.calendar"
