"""日程抓取完整性、精度与分页的回归测试。"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, FetchOutcome, ResponseMode
from astrbot_plugin_nikke.features.calendar.schedule_adapters import BaseScheduleAdapter, FetchResult
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def event(key, **kwargs):
    return CanonicalEvent(id=key, title=key, event_type="event", start_at=NOW - timedelta(days=1),
                          end_at=NOW + timedelta(days=2), primary_source="gamekee", sources=["gamekee"], **kwargs)


class Source(BaseScheduleAdapter):
    source_name = "gamekee"
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


@pytest.mark.asyncio
async def test_gamekee_scan_requires_metadata_and_retains_partial_pages():
    from unittest.mock import AsyncMock
    from astrbot_plugin_nikke.features.calendar.source_scan import scan_gamekee
    client = AsyncMock()
    client.get_json.side_effect = [
        {"code": 0, "data": [{"id": 1}], "meta": {"pagination": {"page_no": 1, "page_total": 2, "total": 2}}},
        TimeoutError(),
    ]
    payload, completeness = await scan_gamekee(client, "url", {}, {"limit": 1})
    assert payload["data"] == [{"id": 1}]
    assert completeness == "PARTIAL"
    client.get_json.side_effect = [{"code": 0, "data": []}]
    assert (await scan_gamekee(client, "url", {}, {}))[1] == "UNKNOWN"


@pytest.mark.asyncio
async def test_gamekee_scan_complete_and_repeated_pages():
    from unittest.mock import AsyncMock
    from astrbot_plugin_nikke.features.calendar.source_scan import scan_gamekee
    client = AsyncMock()
    first = {"data": [{"id": 1}], "meta": {"pagination": {"page_no": 1, "page_total": 2, "total": 2}}}
    client.get_json.side_effect = [first, {"data": [{"id": 2}], "meta": {"pagination": {"page_no": 2, "page_total": 2, "total": 2}}}]
    assert (await scan_gamekee(client, "url", {}, {}))[1] == "COMPLETE"
    client.get_json.side_effect = [first, first]
    assert (await scan_gamekee(client, "url", {}, {}))[1] == "PARTIAL"


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


def test_asymmetric_evidence_does_not_hide_authoritative_field():
    from astrbot_plugin_nikke.features.calendar.canonical_models import FieldEvidence
    from astrbot_plugin_nikke.features.calendar.merge import _merge_two_events
    base = event("base", field_evidence={"end": [FieldEvidence(NOW + timedelta(days=2), "gamekee", confidence=.85).to_dict()]})
    incoming = event("incoming", confidence=.99)
    incoming.primary_source = "official"
    incoming.sources = ["official"]
    incoming.end_at = NOW + timedelta(days=3)
    merged = _merge_two_events(base, incoming)
    assert merged.end_at == incoming.end_at
    repeated = _merge_two_events(merged, incoming)
    assert len(repeated.field_evidence["end"]) == len(merged.field_evidence["end"])


def test_multiple_matching_cycles_are_not_arbitrarily_collapsed(tmp_path):
    service = ScheduleService(tmp_path)
    first, second, supplement = event("a", cycle_id="one"), event("b", cycle_id="two"), event("c")
    for item in (first, second, supplement):
        item.title = "共同活动标题"
    supplement.primary_source = "official"
    supplement.sources = ["official"]
    service._source_datasets = {"gamekee": [first, second], "official": [supplement]}
    original = service._merge_datasets()
    assert len(original) == 3
    assert service.quality_diagnostics["identity_ambiguous"] == 1
    service._source_datasets = {"official": [supplement], "gamekee": [second, first]}
    reordered = service._merge_datasets()
    assert {key: e.fingerprint for key, e in reordered.items()} == {key: e.fingerprint for key, e in original.items()}


@pytest.mark.asyncio
async def test_explicit_refresh_links_announcement_and_coalesces(tmp_path):
    from unittest.mock import AsyncMock
    from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
    service = ScheduleService(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    async def sync():
        started.set()
        await release.wait()
        return False, "timeout"
    service.announcement_service = type("Announcements", (), {})()
    service.announcement_service.sync_from_source = AsyncMock(side_effect=sync)
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY))]
    app = CalendarApplication(service, task_factory=asyncio.create_task)
    first = asyncio.create_task(app.refresh_schedule())
    await started.wait()
    second = asyncio.create_task(app.refresh_schedule())
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second)
    service.announcement_service.sync_from_source.assert_awaited_once()
    assert all("官方公告更新失败" in result.message for result in results)
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


@pytest.mark.asyncio
async def test_official_failed_report_retains_lkg_and_original_confirmation(tmp_path):
    from types import SimpleNamespace
    from astrbot_plugin_nikke.features.calendar.schedule_adapters import OfficialAnnouncementScheduleAdapter
    from astrbot_plugin_nikke.features.calendar.canonical_models import SourceHealth
    service = ScheduleService(tmp_path)
    old = event("official:old")
    service._source_datasets["official"] = [old]
    service._source_health["official"] = SourceHealth("official", last_success_at=NOW)
    announcements = SimpleNamespace(list_deadlines=lambda: [], last_sync_report={"success": False}, last_updated_at="2026-10-11 08:00:00")
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY)), OfficialAnnouncementScheduleAdapter(announcements)]
    await service.refresh_schedule_data()
    assert service._source_datasets["official"] == [old]
    assert service._source_health["official"].last_success_at == NOW
    assert service._source_health["official"].consecutive_failures == 1
    restarted = ScheduleService(tmp_path)
    assert restarted._source_health["official"].consecutive_failures == 1


def test_frozen_health_and_unknown_cache_coverage(tmp_path):
    from astrbot_plugin_nikke.features.calendar.canonical_models import SourceHealth
    service = ScheduleService(tmp_path)
    service._source_datasets = {"gamekee": [event("one")]}
    service._events = {"one": event("one")}
    service._source_health["gamekee"] = SourceHealth.from_dict({"source": "gamekee"})
    context = service.freeze_query_context(NOW)
    assert context.coverage == "PARTIAL"
    service._source_health["gamekee"].consecutive_failures = 10
    assert context.source_health["gamekee"].consecutive_failures == 0


@pytest.mark.asyncio
async def test_unknown_empty_result_marks_retained_records_and_keeps_scan_counts(tmp_path):
    service = ScheduleService(tmp_path)
    service._source_datasets["gamekee"] = [event("old")]
    service.adapters = [Source(FetchResult(FetchOutcome.SUCCESS_EMPTY, completeness="UNKNOWN",
        diagnostics={"gamekee_rows": 3, "gamekee_valid": 0, "gamekee_malformed": 3}))]
    await service.refresh_schedule_data()
    assert service._source_datasets["gamekee"][0].metadata["source_stale"]
    assert service.quality_diagnostics["gamekee_malformed"] == 3


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


@pytest.mark.asyncio
async def test_official_existing_deadline_does_not_hide_other_announcement():
    from types import SimpleNamespace
    from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser
    from astrbot_plugin_nikke.features.calendar.schedule_adapters import OfficialAnnouncementScheduleAdapter
    body = "活动时间：2026-10-10 10:00 至 2026-10-20 23:59 (UTC+8)"
    known = DeadlineParser.parse_deadlines("已解析活动", body, "known")
    assert known
    records = {
        key: SimpleNamespace(content_id=key, title=title, body=body, category="event", source_url="")
        for key, title in [("known", "已解析活动"), ("missing", "此前漏掉活动")]
    }
    service = SimpleNamespace(list_deadlines=lambda: known, _records=records)
    result = await OfficialAnnouncementScheduleAdapter(service).fetch_result()
    assert {e.title for e in result.events} == {"已解析活动", "此前漏掉活动"}
    assert len(result.events) == 2
    assert len(known) == 1


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


@pytest.mark.asyncio
async def test_official_reparse_replaces_only_known_announcement_records(tmp_path):
    service = ScheduleService(tmp_path)
    service._source_datasets["official"] = [event("official:changed_0"), event("official:other_0"), event("official:changed_other_0")]
    source = Source(FetchResult(FetchOutcome.SUCCESS_DATA, [event("official:changed_range_new")],
                               diagnostics={"reparsed_content_ids": ["changed"]}))
    source.source_name = "official"
    source.response_mode = ResponseMode.INCREMENTAL
    service.adapters = [source]
    await service.refresh_schedule_data()
    assert {item.id for item in service._source_datasets["official"]} == {"official:changed_range_new", "official:other_0", "official:changed_other_0"}



def test_date_lines_are_not_numbered_section_headings():
    from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser
    body = "1. FULL BURST DAY\n2026.10.17 05:00 to 2026.10.19 04:59 (UTC+9)\n2026.10.24 05:00 to 2026.10.26 04:59 (UTC+9)"
    rows = DeadlineParser.parse_deadlines("Update", body, "numeric")
    assert len(rows) == 2
    assert {row.name for row in rows} == {"FULL BURST DAY"}
