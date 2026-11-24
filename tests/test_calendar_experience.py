"""日程抓取完整性、精度与分页的回归测试。"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, FetchOutcome, ResponseMode, SourceRole
from astrbot_plugin_nikke.features.calendar.schedule_adapters import BaseScheduleAdapter, FetchResult
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def event(key, **kwargs):
    return CanonicalEvent(id=key, title=key, event_type="event", start_at=NOW - timedelta(days=1),
                          end_at=NOW + timedelta(days=2), primary_source="gamekee", sources=["gamekee"], **kwargs)


class Source(BaseScheduleAdapter):
    source_name = "gamekee"
    # 显式声明主源角色，不依赖基类按源名推断（GameKee 源已在 PR-6B 删除）。
    source_role = SourceRole.PRIMARY
    response_mode = ResponseMode.COMPLETE_SNAPSHOT

    def __init__(self, result):
        self.result = result

    async def fetch_result(self):
        return self.result


@pytest.mark.asyncio
async def test_partial_snapshot_keeps_missing_records_and_reports_partial(tmp_path):
    service = ScheduleService(tmp_path)
    service._source_datasets["gamekee"] = [event("old")]
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_DATA, [event("new")], completeness="PARTIAL"))]
    await service.refresh_schedule_data()
    assert {e.id for e in service._source_datasets["gamekee"]} == {"old", "new"}
    assert service.coverage == "PARTIAL"
    assert service._source_datasets["gamekee"][0].metadata.get("source_stale")


@pytest.mark.asyncio
async def test_incremental_success_does_not_delete_previous_records(tmp_path):
    service = ScheduleService(tmp_path)
    service._source_datasets["gamekee"] = [event("old")]
    source = Source(FetchResult(FetchOutcome.SUCCESS_DATA, [event("new")]))
    source.response_mode = ResponseMode.INCREMENTAL
    service.adapters = [source]
    await service.refresh_schedule_data()
    assert {e.id for e in service._source_datasets["gamekee"]} == {"old", "new"}


@pytest.mark.asyncio
async def test_complete_empty_snapshot_remains_available_after_restart(tmp_path):
    service = ScheduleService(tmp_path)
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY, completeness="COMPLETE"))]
    await service.refresh_schedule_data()
    assert service.has_snapshot()
    assert ScheduleService(tmp_path).has_snapshot()


@pytest.mark.asyncio
async def test_refresh_coalesces_and_cancelled_waiter_does_not_cancel_shared_work(tmp_path):
    service = ScheduleService(tmp_path, task_factory=asyncio.create_task)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def refresh():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True, "ok"
    service._refresh_schedule_data = refresh
    first = asyncio.create_task(service.refresh_schedule_data())
    await started.wait()
    second = asyncio.create_task(service.refresh_schedule_data())
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == (True, "ok")
    assert calls == 1



def test_precision_and_pagination_share_canonical_dates(tmp_path):
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    from astrbot_plugin_nikke.features.calendar.presentation import schedule_pages
    service = ScheduleService(tmp_path)
    events = [event(str(index)) for index in range(17)]
    events[0].start_at = None
    events[0].start_precision = "UNKNOWN"
    events[0].has_started_evidence = True
    events[0].end_precision = "DATE_ONLY"
    service._events = {e.id: e for e in events}
    service._has_snapshot = True
    snapshot = CalendarApplication(service).query_schedule(now=NOW)
    pages = schedule_pages(snapshot)
    assert [len(p["items"]) for p in pages] == [8, 8, 1]
    assert len({item["id"] for p in pages for item in p["items"]}) == 17
    item = next(item for p in pages for item in p["items"] if item["id"] == "0")
    assert item["start"] == "待公布"
    assert item["end"] == "10/13（时间待确认）"
    assert "待公布 → 10/13（时间待确认）" in snapshot.fallback_text


@pytest.mark.asyncio
async def test_command_sends_selected_page_and_build_failure_keeps_page_text(tmp_path):
    from unittest.mock import AsyncMock, Mock
    from astrbot_plugin_nikke.application.commands.calendar import CalendarCommandHandler
    from astrbot_plugin_nikke.application.commands.contracts import CommandContext
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
    service = ScheduleService(tmp_path)
    service._events = {str(i): event(str(i)) for i in range(17)}
    service._has_snapshot = True
    render = AsyncMock(return_value=None)
    builder = CalendarT2IPayloadBuilder()
    handler = CalendarCommandHandler(application=CalendarApplication(service, clock=lambda: NOW),
        payload_builder=builder, render=render, start_background_refresh=Mock())
    context = CommandContext(parameters={"page": str(len(builder.build(CalendarApplication(service).query_schedule(now=NOW))["pages"]))})
    result = await handler.handle(context)
    assert len(render.call_args.args[0]["pages"]) == 1
    assert render.call_args.args[0]["page_number"] == int(context.parameters["page"])
    expected = result.messages[0].text
    builder.build = Mock(side_effect=RuntimeError("render failed"))
    assert (await handler.handle(context)).messages[0].text == CalendarApplication(service).query_schedule(now=NOW).fallback_text
    assert "页】" in expected
    handler._payload_builder = CalendarT2IPayloadBuilder()
    assert "超出范围" in (await handler.handle(CommandContext(parameters={"page": "999"}))).messages[0].text



def test_multiple_matching_cycles_are_not_arbitrarily_collapsed(tmp_path):
    service = ScheduleService(tmp_path)
    first, second, supplement = event("a", cycle_id="one"), event("b", cycle_id="two"), event("c")
    for item in (first, second, supplement):
        item.title = "共同活动标题"
    supplement.primary_source = "official"
    supplement.sources = ["official"]
    service._source_datasets = {"gamekee": [first, second], "official": [supplement]}
    original = service._merge_datasets()
    # PR-6B G5-calendar-a3：按 ID 聚合不折叠同名不同 ID 的记录，且结果与来源顺序无关。
    assert len(original) == 3
    service._source_datasets = {"official": [supplement], "gamekee": [second, first]}
    reordered = service._merge_datasets()
    assert {key: e.fingerprint for key, e in reordered.items()} == {key: e.fingerprint for key, e in original.items()}


@pytest.mark.asyncio
async def test_explicit_refresh_coalesces_without_announcement_linkage(tmp_path):
    # PR-6B G5-calendar-a2：官方公告日程源已删除，显式刷新只读日程源、不联动公告同步；
    # 原 test_explicit_refresh_links_announcement_and_coalesces 改为校验合并与不联动。
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    service = ScheduleService(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0

    class SlowSource(Source):
        async def fetch_result(self):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return self.result

    service.adapters = [SlowSource(FetchResult(FetchOutcome.SUCCESS_EMPTY))]
    app = CalendarApplication(service, task_factory=asyncio.create_task)
    first = asyncio.create_task(app.refresh_schedule())
    await started.wait()
    second = asyncio.create_task(app.refresh_schedule())
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)
    assert calls == 1
    assert not hasattr(service, "announcement_service")
    assert all(result.success and result.message == "ok" for result in results)
    assert all(result.has_snapshot for result in results)


@pytest.mark.asyncio
async def test_runtime_shutdown_cancels_shared_refresh(tmp_path):
    from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
    runtime = RuntimeCoordinator()
    service = ScheduleService(tmp_path, task_factory=runtime.create_task)
    started = asyncio.Event()
    async def refresh():
        started.set()
        await asyncio.Event().wait()
    service._refresh_schedule_data = refresh
    waiter = asyncio.create_task(service.refresh_schedule_data())
    await started.wait()
    await runtime.close()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert service._refresh_task.cancelled()



def test_frozen_health_and_unknown_cache_coverage(tmp_path):
    from astrbot_plugin_nikke.features.calendar.canonical_models import SourceHealth
    service = ScheduleService(tmp_path)
    # PR-6B G5-calendar-a1/b：默认适配器链不再含必需的 GameKee 源，显式注入必需主源。
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY))]
    service._source_datasets = {"gamekee": [event("one")]}
    service._events = {"one": event("one")}
    service._source_health["gamekee"] = SourceHealth.from_dict({"source": "gamekee"})
    context = service.freeze_query_context(NOW)
    assert context.coverage == "PARTIAL"
    service._source_health["gamekee"].consecutive_failures = 10
    assert context.source_health["gamekee"].consecutive_failures == 0


@pytest.mark.asyncio
async def test_unknown_empty_result_marks_retained_records(tmp_path):
    # PR-6B G5-calendar-a1：GameKee 扫描计数诊断已随源删除，只保留“未知空结果标记旧记录”合同。
    service = ScheduleService(tmp_path)
    service._source_datasets["gamekee"] = [event("old")]
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY, completeness="UNKNOWN",
        diagnostics={"gamekee_rows": 3, "gamekee_valid": 0, "gamekee_malformed": 3}))]
    await service.refresh_schedule_data()
    assert service._source_datasets["gamekee"][0].metadata["source_stale"]
    assert "gamekee_malformed" not in service.quality_diagnostics


def test_unknown_start_is_not_silently_reported_as_no_activity(tmp_path):
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    from astrbot_plugin_nikke.features.calendar.presentation import schedule_pages
    service = ScheduleService(tmp_path)
    unknown = event("unknown")
    unknown.start_at = None
    unknown.start_precision = "UNKNOWN"
    service._events = {unknown.id: unknown}
    service._has_snapshot = True
    page = schedule_pages(CalendarApplication(service).query_schedule(now=NOW))[0]
    assert page["summary"]["active"] == 0
    assert page["unconfirmed_count"] == 1
    assert "另有 1 项时间待确认" in page["fallback_text"]



def test_snapshot_uses_original_calendar_layout(tmp_path):
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
    service = ScheduleService(tmp_path)
    service._events = {"one": event("one")}
    service._has_snapshot = True
    bundle = CalendarT2IPayloadBuilder().build(CalendarApplication(service).query_schedule(now=NOW))
    assert not bundle.get("experience")
    assert bundle["canvas"]["width"] == 1600
    assert bundle["pages"][0]["active_items"][0]["title"] == "one"



def test_official_parser_recovers_repeated_ranges_without_cross_pairing():
    from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser
    body = """1. Union Raid
Union Raid starts October 9, 2026, 5:00:00 (UTC+9).
Duration: From October 9, 2026, 5:00:00 to October 15, 2026, 4:59:59 (UTC+9)
2. FULL BURST DAY
From October 17, 2026, 5:00:00 to October 19, 2026, 4:59:59 (UTC+9)
From October 24, 2026, 5:00:00 to October 26, 2026, 4:59:59 (UTC+9)
"""
    rows = DeadlineParser.parse_deadlines("Update", body, "ranges")
    assert len(rows) == 3
    assert len({item.event_id for item in rows}) == 3
    assert sum(item.name == "FULL BURST DAY" for item in rows) == 2
    assert next(item for item in rows if item.name == "Union Raid").end_at == datetime(2026, 10, 14, 19, 59, tzinfo=timezone.utc)
    assert DeadlineParser.parse_deadlines("Unrelated dates", "2026-10-09 05:00 publication\n2026-10-11 05:00 revision\n2026-10-15 05:00 report", "unrelated") == []


def test_official_numeric_heading_and_time_first_date_keep_correct_title():
    from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser, CST
    body = """4.3 Storyline
Available after the maintenance on October 8, 2026
4.4 14-Day Login Event
Event duration: From the end of the October 8, 2026 maintenance to October 28, 2026, 23:59:59 (UTC+9)
4.6 Story Event
Event duration: From the end of the October 8, 2026 maintenance to 23:59:59, October 28, 2026 (UTC+9)
"""
    rows = DeadlineParser.parse_deadlines("Update", body, "dates")
    assert {item.name for item in rows} == {"14-Day Login Event", "Story Event"}
    assert all(item.start_precision == "DATE_ONLY" for item in rows)
    assert all(item.start_at.astimezone(CST).hour == 0 for item in rows)
    assert all(item.end_at == datetime(2026, 10, 28, 14, 59, tzinfo=timezone.utc) for item in rows)



def test_date_lines_are_not_numbered_section_headings():
    from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser
    body = "1. FULL BURST DAY\n2026.10.17 05:00 to 2026.10.19 04:59 (UTC+9)\n2026.10.24 05:00 to 2026.10.26 04:59 (UTC+9)"
    rows = DeadlineParser.parse_deadlines("Update", body, "numeric")
    assert len(rows) == 2
    assert {row.name for row in rows} == {"FULL BURST DAY"}
