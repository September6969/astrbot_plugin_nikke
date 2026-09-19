# SPDX-License-Identifier: GPL-3.0-or-later
"""Gate A P0 数据语义与边界测试全集。

覆盖：
1. start=None + future end -> UNKNOWN (严禁仅由 end_at 在未来反推已开始)
2. explicit started evidence -> ACTIVE
3. snapshot old ACTIVE + now after end -> ENDED (状态非持久化真值)
4. start >= end -> INVALID / UNKNOWN (不进入 ACTIVE、不触发提醒、不崩溃)
5. EXACT start + DATE_ONLY end (独立起止精度、向后兼容)
6. UNKNOWN end 安全排序 (无 TypeError，未知截止置底)
7. all unknown end -> no NEXT ENDING (允许缺省)
8. DATE_ONLY -> no hourly urgency
9. DATE_ONLY -> no hourly reminder (不进入 list_reminder_deadlines)
10. 304 -> last_success_at 更新，content_updated_at 不变
11. content unchanged 连续成功 -> 重启后依据 health 持久化仍然为 FRESH
12. GameKee 成功 + Official 失败 -> per-source LKG 保留，Coverage=PARTIAL
13. COMPLETE_SNAPSHOT 来源 SUCCESS_EMPTY 清空该源 dataset
14. PARSE_FAILED 保留该源历史 LKG
15. Official 取消证据优先于存在证据 -> CANCELLED
16. Manual Override 覆盖层：删除 override 自动恢复 Base 原值
17. same title, different cycle -> 独立 identity，不误合并
18. same title, different scope -> 独立 identity，不误合并
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock
from pathlib import Path

import pytest

from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    FieldEvidence,
    FetchOutcome,
    ResponseMode,
    TimePrecision,
    EventStatus,
    Freshness,
    Coverage,
    resolve_event_status,
    active_sort_key,
    sort_active_events,
    resolve_next_ending,
    compute_health_badge,
    QueryContext,
)
from astrbot_plugin_nikke.features.calendar.schedule_adapters import (
    BaseScheduleAdapter,
    FetchResult,
)
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def test_unknown_start_with_future_end_is_unknown():
    """P0-1: start=None, end=future -> UNKNOWN (严禁仅由 end_at 在未来反推已开始)。"""
    event = CanonicalEvent(
        id="test:1",
        title="Unknown Start Event",
        event_type="event",
        start_at=None,
        end_at=NOW + timedelta(days=3),
    )
    status = resolve_event_status(event, NOW)
    assert status == EventStatus.UNKNOWN.value
    assert not event.is_active(NOW)


def test_explicit_started_evidence_is_active():
    """P0-1: start=None, end=future 但存在独立可靠 started evidence -> ACTIVE。"""
    event = CanonicalEvent(
        id="test:2",
        title="Started Evidence Event",
        event_type="event",
        start_at=None,
        end_at=NOW + timedelta(days=3),
        has_started_evidence=True,
    )
    assert resolve_event_status(event, NOW) == EventStatus.ACTIVE.value
    assert event.is_active(NOW)

    # 当查询时间推进到 end_at 之后，应转为 ENDED
    assert resolve_event_status(event, NOW + timedelta(days=4)) == EventStatus.ENDED.value


def test_snapshot_old_active_now_after_end_is_ended():
    """P0-1: 快照保存时为 ACTIVE，但查询时间已过 end_at -> 必须动态计算为 ENDED。"""
    event = CanonicalEvent(
        id="test:3",
        title="Past Event",
        event_type="event",
        start_at=NOW - timedelta(days=5),
        end_at=NOW - timedelta(days=1),
        status="ACTIVE",  # 快照中残留旧状态
    )
    # 动态查询必须重新计算为 ENDED，不能相信静态 status
    assert resolve_event_status(event, NOW) == EventStatus.ENDED.value


def test_invalid_interval_start_ge_end_is_invalid():
    """P0-4: start_at >= end_at 标记为 INVALID，不抛异常崩溃，不进入 ACTIVE，不进入提醒。"""
    event = CanonicalEvent(
        id="test:4",
        title="Invalid Interval Event",
        event_type="event",
        start_at=NOW + timedelta(days=2),
        end_at=NOW - timedelta(days=1),  # start > end
    )
    assert not event.is_valid_interval
    assert resolve_event_status(event, NOW) == EventStatus.INVALID.value
    assert not event.is_active(NOW)
    assert "时间区间无效" in event.remaining_display(NOW)


def test_exact_start_and_date_only_end():
    """P0-3: start_precision 与 end_precision 分别表达，向后兼容。"""
    event = CanonicalEvent(
        id="test:5",
        title="Hybrid Precision Event",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=2),
        start_precision="EXACT",
        end_precision="DATE_ONLY",
    )
    assert event.start_precision == "EXACT"
    assert event.end_precision == "DATE_ONLY"
    assert event.time_precision == "DATE_ONLY"  # 兼容属性

    rem = event.remaining_display(NOW)
    # DATE_ONLY 绝不制造小时/分钟倒计时
    assert "截止" in rem
    assert "小时" not in rem
    assert "分钟" not in rem

    # 字典序列化与反序列化平滑兼容
    d = event.to_dict()
    assert d["start_precision"] == "EXACT"
    assert d["end_precision"] == "DATE_ONLY"
    restored = CanonicalEvent.from_dict(d)
    assert restored.start_precision == "EXACT"
    assert restored.end_precision == "DATE_ONLY"


def test_unknown_end_sorting_no_type_error():
    """P0-5: 排序安全，可靠 end ASC，未知 end 置底，无 TypeError。"""
    e_exact_soon = CanonicalEvent(
        id="soon",
        title="Soon Exact",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(hours=2),
        end_precision="EXACT",
    )
    e_exact_later = CanonicalEvent(
        id="later",
        title="Later Exact",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=5),
        end_precision="EXACT",
    )
    e_date_only = CanonicalEvent(
        id="date_only",
        title="Date Only",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=3),
        end_precision="DATE_ONLY",
    )
    e_unknown = CanonicalEvent(
        id="unknown",
        title="Unknown End",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=None,
        end_precision="UNKNOWN",
    )

    events = [e_unknown, e_date_only, e_exact_later, e_exact_soon]
    sorted_evs = sort_active_events(events, NOW)
    # 期望顺序：e_exact_soon (0) -> e_exact_later (0) -> e_date_only (1) -> e_unknown (2)
    assert [ev.id for ev in sorted_evs] == ["soon", "later", "date_only", "unknown"]


def test_all_unknown_end_no_next_ending():
    """P0-6: 若所有 Active 均为未知或 DATE_ONLY，NEXT ENDING 允许缺省 (返回 None)。"""
    e1 = CanonicalEvent(
        id="1",
        title="No End 1",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=None,
    )
    e2 = CanonicalEvent(
        id="2",
        title="Date Only 2",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=2),
        end_precision="DATE_ONLY",
    )
    assert resolve_next_ending([e1, e2], NOW) is None


def test_date_only_no_hourly_reminder(tmp_path):
    """P0-7: DATE_ONLY 绝不触发小时级截止提醒 (list_reminder_deadlines 排除)。"""
    service = ScheduleService(tmp_path)
    e_exact = CanonicalEvent(
        id="exact",
        title="Exact Urgent",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(hours=2),
        end_precision="EXACT",
    )
    e_date = CanonicalEvent(
        id="date",
        title="Date Only Today",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(hours=2),
        end_precision="DATE_ONLY",
    )
    service._events = {e_exact.id: e_exact, e_date.id: e_date}
    service._sync_internal_stores(service._events)
    service._has_snapshot = True

    deadlines = service.list_reminder_deadlines(NOW)
    assert len(deadlines) == 1
    assert deadlines[0].event_id == "exact"


@pytest.mark.asyncio
async def test_304_updates_last_success_not_content_time(tmp_path):
    """P0-9 & P0-18: 304 Not Modified 更新 last_success_at，但 content_updated_at 不变。"""
    service = ScheduleService(tmp_path)
    t0 = NOW - timedelta(days=2)
    service.content_updated_at = t0
    service.last_success_at = t0
    service.last_attempt_at = t0

    class Mock304Adapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "mock"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.NOT_MODIFIED, source="mock")

    service.adapters = [Mock304Adapter()]
    ok, msg = await service.refresh_schedule_data()
    assert ok
    # 成功确认，last_success_at 更新为最新
    assert service.last_success_at > t0
    # 内容无变更，content_updated_at 保持 t0
    assert service.content_updated_at == t0


@pytest.mark.asyncio
async def test_content_unchanged_restart_still_fresh(tmp_path):
    """P0-18: 内容 3 天未变，但持续同步成功，重启后基于 health 持久化仍然判定为 FRESH。"""
    service1 = ScheduleService(tmp_path, ttl_seconds=300)
    ev = CanonicalEvent(
        id="stable:1",
        title="Stable Event",
        event_type="event",
        start_at=NOW - timedelta(days=5),
        end_at=NOW + timedelta(days=5),
    )
    class StableAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[ev], source="gamekee")

    service1.adapters = [StableAdapter()]
    await service1.refresh_schedule_data()
    assert service1.freshness == Freshness.FRESH.value

    # 重启新实例载入
    service2 = ScheduleService(tmp_path, ttl_seconds=300)
    assert service2.has_snapshot()
    assert service2.activity_count() == 1
    assert service2.freshness == Freshness.FRESH.value
    assert service2.data_quality == "DATA OK"


@pytest.mark.asyncio
async def test_per_source_lkg_gamekee_success_official_failure(tmp_path):
    """P0-11: GameKee 成功，Official 失败 -> 保留 Official 历史 LKG，Coverage=PARTIAL。"""
    service = ScheduleService(tmp_path)
    ev_gk = CanonicalEvent(
        id="gk:1",
        title="GK Event",
        event_type="event",
        start_at=NOW,
        end_at=NOW + timedelta(days=3),
        sources=["gamekee"],
        primary_source="gamekee",
    )
    ev_off = CanonicalEvent(
        id="off:1",
        title="Official Event",
        event_type="event",
        start_at=NOW,
        end_at=NOW + timedelta(days=4),
        sources=["official"],
        primary_source="official",
    )

    # Run 1: 两个源均成功
    service._source_datasets = {"gamekee": [ev_gk], "official": [ev_off]}
    service._merge_datasets()

    # Run 2: GameKee 成功返回新数据，Official 请求失败
    class GKAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[ev_gk], source="gamekee")

    class FailingOffAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "official"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.REQUEST_FAILED, error_message="500 Server Error", source="official")

    service.adapters = [GKAdapter(), FailingOffAdapter()]
    ok, msg = await service.refresh_schedule_data()
    assert ok
    # Official 的活动不得被误删，保留在合并集合中
    assert "off:1" in service._events
    assert "gk:1" in service._events
    # Official 为补充源 (required_for_complete=False)，其失败不把 COMPLETE 变成 PARTIAL
    assert service.coverage == Coverage.COMPLETE.value
    assert service.data_quality == "DATA OK"


@pytest.mark.asyncio
async def test_success_empty_complete_snapshot_clears_source(tmp_path):
    """P0-10 & P0-12: COMPLETE_SNAPSHOT 来源返回 SUCCESS_EMPTY 清空该源 dataset，不影响其他源。"""
    service = ScheduleService(tmp_path)
    ev_gk = CanonicalEvent(id="gk:1", title="GK", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=1), primary_source="gamekee")
    ev_off = CanonicalEvent(id="off:1", title="OFF", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=1), primary_source="official")
    service._source_datasets = {"gamekee": [ev_gk], "official": [ev_off]}

    class EmptyGKAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        @property
        def response_mode(self) -> ResponseMode:
            return ResponseMode.COMPLETE_SNAPSHOT
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_EMPTY, events=[], source="gamekee")

    class UnchangedOffAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "official"
        @property
        def response_mode(self) -> ResponseMode:
            return ResponseMode.INCREMENTAL
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.NOT_MODIFIED, source="official")

    service.adapters = [EmptyGKAdapter(), UnchangedOffAdapter()]
    await service.refresh_schedule_data()

    # GameKee 贡献被合法清空，Official 仍然保留
    assert "gk:1" not in service._events
    assert "off:1" in service._events


@pytest.mark.asyncio
async def test_parse_failed_retains_lkg(tmp_path):
    """P0-12: 来源返回 200 但无法解析 (PARSE_FAILED) 时不得清空旧 LKG。"""
    service = ScheduleService(tmp_path)
    ev_gk = CanonicalEvent(id="gk:1", title="GK Old", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=1), primary_source="gamekee")
    service._source_datasets = {"gamekee": [ev_gk]}

    class DriftingAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.PARSE_FAILED, error_message="Schema drift", source="gamekee")

    service.adapters = [DriftingAdapter()]
    ok, msg = await service.refresh_schedule_data()
    # 仍然可查，保留历史数据
    assert "gk:1" in service._events


def test_official_cancellation_preempts():
    """P0-13: 官方取消证据覆盖普通存在证据，标记 CANCELLED。"""
    event = CanonicalEvent(
        id="cancel:1",
        title="Cancelled Raid",
        event_type="union_raid",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=2),
        is_cancelled=True,
    )
    assert resolve_event_status(event, NOW) == EventStatus.CANCELLED.value
    assert "已取消" in event.remaining_display(NOW)


@pytest.mark.asyncio
async def test_manual_override_deletion_restores_base(tmp_path):
    """P0-16: 手动覆盖层配置存在时覆盖，删除配置自动恢复 Base 原值。"""
    service = ScheduleService(tmp_path)
    base_ev = CanonicalEvent(
        id="ev:1",
        title="Original Title",
        event_type="event",
        start_at=NOW,
        end_at=NOW + timedelta(days=2),
        primary_source="gamekee",
    )
    service._source_datasets = {"gamekee": [base_ev]}

    # 设置手动覆盖
    overrides_file = tmp_path / "schedule_overrides.json"
    overrides_file.write_text(json.dumps([
        {"event_id": "ev:1", "field": "title", "value": "Overridden Title"}
    ]), encoding="utf-8")

    class MockGK(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[base_ev], source="gamekee")

    service.adapters = [service.manual_adapter, MockGK()]
    await service.refresh_schedule_data()
    assert service._events["ev:1"].title == "Overridden Title"

    # 删除覆盖文件，再次刷新 -> 自动恢复原标题
    overrides_file.unlink()
    await service.refresh_schedule_data()
    assert service._events["ev:1"].title == "Original Title"


def test_same_title_different_cycle_not_merged():
    """P0-17: 同名但不同期次 (cycle_id) 必须拥有独立 identity，绝不合并。"""
    e1 = CanonicalEvent(
        id="sr:34",
        title="Solo Raid",
        event_type="solo_raid",
        cycle_id="season_34",
        start_at=NOW - timedelta(days=30),
        end_at=NOW - timedelta(days=23),
    )
    e2 = CanonicalEvent(
        id="sr:35",
        title="Solo Raid",
        event_type="solo_raid",
        cycle_id="season_35",
        start_at=NOW + timedelta(days=1),
        end_at=NOW + timedelta(days=8),
    )
    assert e1.identity_key != e2.identity_key
    assert e1.identity_key == "GLOBAL:solo_raid:season_34"
    assert e2.identity_key == "GLOBAL:solo_raid:season_35"


def test_same_title_different_scope_not_merged():
    """P0-17: 同名但不同服务器 Scope 必须拥有独立 identity，绝不合并。"""
    e1 = CanonicalEvent(
        id="ev:global",
        title="Coordinated Operation",
        event_type="coop",
        server_scope="GLOBAL",
        start_at=NOW,
        end_at=NOW + timedelta(days=3),
    )
    e2 = CanonicalEvent(
        id="ev:jp",
        title="Coordinated Operation",
        event_type="coop",
        server_scope="JP",
        start_at=NOW,
        end_at=NOW + timedelta(days=3),
    )
    assert e1.identity_key != e2.identity_key


@pytest.mark.asyncio
async def test_official_adapter_reads_real_announcement_deadlines():
    """P0-1: Official 适配器真实消费 AnnouncementService.list_deadlines() / DeadlineParser，返回结构化时间。"""
    from astrbot_plugin_nikke.features.announcement.service import GameDeadline
    from astrbot_plugin_nikke.features.calendar.schedule_adapters import OfficialAnnouncementScheduleAdapter

    mock_announcement = Mock()
    dl1 = GameDeadline(
        name="冠军竞技场开启",
        start_at=NOW,
        end_at=NOW + timedelta(days=7),
        event_id="ann_champion_arena",
        category="coop",
        source_url="https://nikke-en.com/news/1",
    )
    mock_announcement.list_deadlines = Mock(return_value=[dl1])

    adapter = OfficialAnnouncementScheduleAdapter(announcement_service=mock_announcement)
    res = await adapter.fetch_result()

    assert res.outcome == FetchOutcome.SUCCESS_DATA
    assert len(res.events) == 1
    ev = res.events[0]
    assert ev.id == "official:ann_champion_arena"
    assert ev.title == "冠军竞技场开启"
    assert ev.start_at == NOW
    assert ev.end_at == NOW + timedelta(days=7)
    assert ev.start_precision == TimePrecision.EXACT.value
    assert ev.end_precision == TimePrecision.EXACT.value
    assert ev.confidence == 0.95
    assert ev.primary_source == "official"


@pytest.mark.asyncio
async def test_official_timezone_utc9_conversion():
    """P0-1: Official UTC+9 时间解析后统一转为 aware UTC，并在 CST 场景下输出精确对应时间。"""
    from astrbot_plugin_nikke.features.announcement.service import GameDeadline
    from astrbot_plugin_nikke.features.calendar.schedule_adapters import OfficialAnnouncementScheduleAdapter
    from astrbot_plugin_nikke.features.calendar.canonical_models import CST

    # 构造东九区时间：2026-09-20 18:00:00+09:00 -> UTC 为 2026-09-20 09:00:00+00:00 -> CST 为 2026-09-20 17:00:00+08:00
    tz_utc9 = timezone(timedelta(hours=9))
    t_start_utc9 = datetime(2026, 9, 20, 18, 0, 0, tzinfo=tz_utc9)
    t_end_utc9 = datetime(2026, 9, 27, 23, 59, 59, tzinfo=tz_utc9)

    mock_ann = Mock()
    dl = GameDeadline(
        name="联合作战公告",
        start_at=t_start_utc9,
        end_at=t_end_utc9,
        event_id="ann_utc9_test",
        category="event",
    )
    mock_ann.list_deadlines = Mock(return_value=[dl])

    adapter = OfficialAnnouncementScheduleAdapter(announcement_service=mock_ann)
    res = await adapter.fetch_result()
    assert res.outcome == FetchOutcome.SUCCESS_DATA
    ev = res.events[0]

    assert ev.start_at.tzinfo == timezone.utc
    assert ev.start_at == datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc)
    # CST 转换
    assert ev.start_at.astimezone(CST).hour == 17
    assert ev.start_at.astimezone(CST).minute == 0


def test_official_confidence_field_arbitration():
    """P0-4: 官方置信度 0.95 成功覆写 GameKee 错误时间；0.75 低置信度不覆写 GameKee 权威时间。"""
    from astrbot_plugin_nikke.features.calendar.schedule_service import _merge_two_events

    t_gk_start = NOW
    t_gk_end = NOW + timedelta(days=2)
    t_off_end = NOW + timedelta(days=5)

    ev_gk = CanonicalEvent(
        id="gamekee:101",
        title="协同作战",
        event_type="coop",
        start_at=t_gk_start,
        end_at=t_gk_end,
        confidence=0.85,
        primary_source="gamekee",
        sources=["gamekee"],
        field_evidence={
            "title": [FieldEvidence("协同作战", "gamekee", 0.85).to_dict()],
            "start": [FieldEvidence(t_gk_start, "gamekee", 0.85).to_dict()],
            "end": [FieldEvidence(t_gk_end, "gamekee", 0.85).to_dict()],
        }
    )

    # 1. 官方置信度 0.95 -> 成功覆写 end_at 为 t_off_end，保留 GameKee 中文标题
    ev_off_high = CanonicalEvent(
        id="official:101",
        title="Coordinated Operation Notice",
        event_type="coop",
        start_at=t_gk_start,
        end_at=t_off_end,
        confidence=0.95,
        primary_source="official",
        sources=["official"],
        field_evidence={
            "title": [FieldEvidence("Coordinated Operation Notice", "official", 0.95).to_dict()],
            "start": [FieldEvidence(t_gk_start, "official", 0.95).to_dict()],
            "end": [FieldEvidence(t_off_end, "official", 0.95).to_dict()],
        }
    )
    merged_high = _merge_two_events(ev_gk, ev_off_high)
    assert merged_high.end_at == t_off_end
    assert merged_high.title == "协同作战"

    # 2. 官方置信度 0.75 -> 保持 GameKee 原 end_at
    ev_off_low = CanonicalEvent(
        id="official:101",
        title="Coordinated Operation Notice",
        event_type="coop",
        start_at=t_gk_start,
        end_at=t_off_end,
        confidence=0.75,
        primary_source="official",
        sources=["official"],
        field_evidence={
            "title": [FieldEvidence("Coordinated Operation Notice", "official", 0.75).to_dict()],
            "start": [FieldEvidence(t_gk_start, "official", 0.75).to_dict()],
            "end": [FieldEvidence(t_off_end, "official", 0.75).to_dict()],
        }
    )
    merged_low = _merge_two_events(ev_gk, ev_off_low)
    assert merged_low.end_at == t_gk_end
    assert merged_low.title == "协同作战"


def test_field_evidence_independent_start_end_arbitration():
    """P0-4: 官方仅提供 end_at 时，与 GameKee 合并后保留 GameKee 的 start_at 和官方的 end_at，互不破坏。"""
    from astrbot_plugin_nikke.features.calendar.schedule_service import _merge_two_events

    t_start = NOW - timedelta(days=1)
    t_end_gk = NOW + timedelta(days=3)
    t_end_off = NOW + timedelta(days=4)

    ev_gk = CanonicalEvent(
        id="gamekee:201",
        title="单人突袭 第10期",
        event_type="solo_raid",
        start_at=t_start,
        end_at=t_end_gk,
        start_precision="EXACT",
        end_precision="EXACT",
        confidence=0.85,
        primary_source="gamekee",
        sources=["gamekee"],
        field_evidence={
            "title": [FieldEvidence("单人突袭 第10期", "gamekee", 0.85).to_dict()],
            "start": [FieldEvidence(t_start, "gamekee", 0.85, precision="EXACT").to_dict()],
            "end": [FieldEvidence(t_end_gk, "gamekee", 0.85, precision="EXACT").to_dict()],
        }
    )

    # 官方只提供截止时间公告（start_at 为 None），置信度 0.95
    ev_off = CanonicalEvent(
        id="official:201",
        title="Solo Raid Season 10 Deadline",
        event_type="solo_raid",
        start_at=None,
        end_at=t_end_off,
        start_precision="UNKNOWN",
        end_precision="EXACT",
        confidence=0.95,
        primary_source="official",
        sources=["official"],
        field_evidence={
            "title": [FieldEvidence("Solo Raid Season 10 Deadline", "official", 0.95).to_dict()],
            "end": [FieldEvidence(t_end_off, "official", 0.95, precision="EXACT").to_dict()],
        }
    )

    merged = _merge_two_events(ev_gk, ev_off)
    # start_at 保留 GameKee，绝不因为官方为空抹除
    assert merged.start_at == t_start
    assert merged.start_precision == "EXACT"
    # end_at 采用官方高置信度时间
    assert merged.end_at == t_end_off
    assert merged.end_precision == "EXACT"
    assert merged.title == "单人突袭 第10期"


@pytest.mark.asyncio
async def test_per_source_lkg_restart_persistence(tmp_path):
    """P0-2: Schema 4 格式写入及重启恢复：gamekee 和 official 在 schedule_events.json 中独立保存并成功还原为各源独立数据集。"""
    service1 = ScheduleService(tmp_path)
    ev_gk = CanonicalEvent(
        id="gamekee:301",
        title="GK Event",
        event_type="event",
        start_at=NOW,
        end_at=NOW + timedelta(days=2),
        primary_source="gamekee",
        sources=["gamekee"],
    )
    ev_off = CanonicalEvent(
        id="official:301",
        title="Official Event",
        event_type="update",
        start_at=NOW + timedelta(days=1),
        end_at=NOW + timedelta(days=3),
        primary_source="official",
        sources=["official"],
    )

    service1._source_datasets = {
        "gamekee": [ev_gk],
        "official": [ev_off],
    }
    service1.content_updated_at = NOW
    service1.last_success_at = NOW
    effective = service1._merge_datasets()
    service1._sync_internal_stores(effective)
    service1._save_cache(force_events=True)

    # 验证磁盘持久化为 Schema 4
    data = json.loads((tmp_path / "schedule_events.json").read_text(encoding="utf-8"))
    assert data["schema"] == 4
    assert "source_datasets" in data
    assert len(data["source_datasets"]["gamekee"]) == 1
    assert len(data["source_datasets"]["official"]) == 1
    assert data["source_datasets"]["gamekee"][0]["id"] == "gamekee:301"
    assert data["source_datasets"]["official"][0]["id"] == "official:301"

    # 重启新实例读取缓存
    service2 = ScheduleService(tmp_path)
    assert not service2.migrated_from_merged_snapshot
    assert "gamekee" in service2._source_datasets
    assert "official" in service2._source_datasets
    assert len(service2._source_datasets["gamekee"]) == 1
    assert len(service2._source_datasets["official"]) == 1
    assert service2.has_snapshot()


def test_manual_override_not_baked_and_restorable(tmp_path):
    """P0-2 & P0-3: Manual Override 仅作为动态覆盖层存在，不污染 Base 数据；当移除 Override 后，Base 数据完好恢复。"""
    service = ScheduleService(tmp_path)
    t_base_end = NOW + timedelta(days=2)
    t_override_end = NOW + timedelta(days=10)

    base_ev = CanonicalEvent(
        id="gk:401",
        title="Base Title",
        event_type="event",
        start_at=NOW,
        end_at=t_base_end,
        primary_source="gamekee",
    )
    service._source_datasets = {"gamekee": [base_ev]}
    service._merge_datasets()
    service._sync_internal_stores(service._base_events)

    # 1. 写入 Manual Override
    overrides_file = tmp_path / "schedule_overrides.json"
    overrides_file.write_text(json.dumps([
        {"event_id": "gk:401", "field": "end_at", "value": t_override_end.isoformat()}
    ]), encoding="utf-8")

    service.reload_overrides()
    assert service._events["gk:401"].end_at == t_override_end
    # Base 数据集本身未被篡改
    assert service._base_events["gk:401"].end_at == t_base_end

    # 2. 移除 Manual Override，无网络请求下重载
    overrides_file.unlink()
    service.reload_overrides()
    assert service._events["gk:401"].end_at == t_base_end


@pytest.mark.asyncio
async def test_manual_empty_does_not_refresh_freshness(tmp_path):
    """P0-3: Manual 覆盖层返回 SUCCESS_EMPTY 时，不将 last_success_at 刷新为当前时间（保持不变）。"""
    service = ScheduleService(tmp_path)
    t_old = NOW - timedelta(hours=10)
    service.last_success_at = t_old

    class FailingRemoteAdapter(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.REQUEST_FAILED, error_message="Net error", source="gamekee")

    # 手动覆盖层返回 SUCCESS_EMPTY，远端源失败
    service.adapters = [service.manual_adapter, FailingRemoteAdapter()]
    ok, msg = await service.refresh_schedule_data()

    assert not ok
    # last_success_at 绝不能被手动空覆盖层刷新为当前时间
    assert service.last_success_at == t_old


def test_t2i_payload_purged_legacy_groups(tmp_path):
    """P0-6: CalendarT2IPayloadBuilder 返回的字典中彻底不存在 groups, ending_soon, active, upcoming 键。"""
    from astrbot_plugin_nikke.ui.t2i_payloads import CalendarT2IPayloadBuilder

    service = ScheduleService(tmp_path)
    ev = CanonicalEvent(
        id="gk:501",
        title="Active Event",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=2),
    )
    service._source_datasets = {"gamekee": [ev]}
    service._merge_datasets()
    service._sync_internal_stores(service._base_events)
    service._has_snapshot = True

    builder = CalendarT2IPayloadBuilder()
    payload = builder.build(service, days=14, now=NOW)

    # 严格断言已净化移除旧版键
    assert "groups" not in payload
    assert "ending_soon" not in payload
    assert "active" not in payload
    assert "upcoming" not in payload

    # 严格断言保留规范键
    assert "pages" in payload
    assert "page_number" in payload
    assert "page_total" in payload
    assert "active_items" in payload
    assert "next_items" in payload
    assert "global_has_active" in payload
    assert "health_display" in payload
    assert "source_display" in payload


def test_compatible_sorting_with_none_datetimes(tmp_path):
    """P0-7: 当存在 start_at 或 end_at 为 None 的活动时，group_window / list_window / list_reminder_deadlines 排序不抛出 TypeError。"""
    service = ScheduleService(tmp_path)
    e1 = CanonicalEvent(
        id="none:1",
        title="No End Event",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=None,
        end_precision="UNKNOWN",
    )
    e2 = CanonicalEvent(
        id="none:2",
        title="No Start Event",
        event_type="event",
        start_at=None,
        end_at=NOW + timedelta(days=2),
        has_started_evidence=True,
    )
    e3 = CanonicalEvent(
        id="normal:3",
        title="Normal Event",
        event_type="event",
        start_at=NOW - timedelta(days=1),
        end_at=NOW + timedelta(days=3),
    )

    service._source_datasets = {"gamekee": [e1, e2, e3]}
    service._merge_datasets()
    service._sync_internal_stores(service._base_events)
    service._has_snapshot = True

    # 均不应抛出 TypeError
    win = service.list_window(14, now=NOW)
    assert len(win) >= 1

    reminders = service.list_reminder_deadlines(now=NOW)
    assert isinstance(reminders, list)

    groups = service.group_window(14, now=NOW)
    assert "active" in groups
    assert "upcoming" in groups


@pytest.mark.asyncio
async def test_required_for_complete_governs_coverage(tmp_path):
    """验证 required_for_complete 真正参与 Coverage 计算：
    - Scenario A: GameKee success, Official failure -> Coverage == COMPLETE
    - Scenario B: GameKee failure, Official cache/success -> Coverage != COMPLETE (PARTIAL)
    - Scenario C: Manual success only -> Coverage != COMPLETE (PARTIAL)
    """
    ev_gk = CanonicalEvent(id="gk:1", title="GK Event", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=2), primary_source="gamekee")
    ev_off = CanonicalEvent(id="off:1", title="OFF Event", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=2), primary_source="official")

    # Scenario A: GameKee 成功，Official 失败 -> COMPLETE
    service_a = ScheduleService(tmp_path / "sa")
    class GKSuccess(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        @property
        def required_for_complete(self) -> bool:
            return True
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[ev_gk], source="gamekee")

    class OffFail(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "official"
        @property
        def required_for_complete(self) -> bool:
            return False
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.REQUEST_FAILED, error_message="Network error", source="official")

    service_a.adapters = [GKSuccess(), OffFail()]
    ok, _ = await service_a.refresh_schedule_data()
    assert ok
    assert service_a.coverage == Coverage.COMPLETE.value

    # Scenario B: GameKee 失败，Official 成功/有缓存 -> PARTIAL (不得为 COMPLETE)
    service_b = ScheduleService(tmp_path / "sb")
    class GKFail(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        @property
        def required_for_complete(self) -> bool:
            return True
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.REQUEST_FAILED, error_message="GK Down", source="gamekee")

    class OffSuccess(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "official"
        @property
        def required_for_complete(self) -> bool:
            return False
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[ev_off], source="official")

    service_b.adapters = [GKFail(), OffSuccess()]
    await service_b.refresh_schedule_data()
    assert service_b.coverage != Coverage.COMPLETE.value
    assert service_b.coverage == Coverage.PARTIAL.value

    # Scenario C: 仅 Manual 成功 -> PARTIAL (不得为 COMPLETE)
    service_c = ScheduleService(tmp_path / "sc")
    ev_man = CanonicalEvent(id="gk:1", title="Manual Title", event_type="event", start_at=NOW, end_at=NOW + timedelta(days=2), primary_source="manual")
    service_c._events = {"gk:1": ev_man}
    service_c._source_datasets = {"manual": [ev_man]}
    service_c._update_health_state()
    assert service_c.coverage != Coverage.COMPLETE.value
    assert service_c.coverage == Coverage.PARTIAL.value


@pytest.mark.asyncio
async def test_official_local_cache_does_not_refresh_freshness(tmp_path):
    """验证 Official 本地缓存读取成功不能刷新 Calendar 的全局 Freshness。"""
    service = ScheduleService(tmp_path)
    now = datetime.now(timezone.utc)
    old_success = now - timedelta(hours=10)
    service.last_success_at = old_success

    ev_off = CanonicalEvent(id="off:1", title="Official Deadline", event_type="event", start_at=now, end_at=now + timedelta(days=2), primary_source="official")

    class FailingGK(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "gamekee"
        @property
        def contributes_to_freshness(self) -> bool:
            return True
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.REQUEST_FAILED, error_message="Timeout", source="gamekee")

    class LocalCacheOff(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "official"
        @property
        def contributes_to_freshness(self) -> bool:
            return False
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_DATA, events=[ev_off], source="official")

    class EmptyManual(BaseScheduleAdapter):
        @property
        def source_name(self) -> str:
            return "manual"
        @property
        def contributes_to_freshness(self) -> bool:
            return False
        async def fetch_result(self) -> FetchResult:
            return FetchResult(outcome=FetchOutcome.SUCCESS_EMPTY, events=[], source="manual")

    service.adapters = [EmptyManual(), FailingGK(), LocalCacheOff()]
    ok, _ = await service.refresh_schedule_data()

    # Calendar.last_success_at 必须保持 old_success，不能变成当前时间
    assert service.last_success_at == old_success
    # Freshness 根据 10 小时前的 old_success 推导应为 STALE，不得被刷成 FRESH
    assert service.freshness == Freshness.STALE.value


@pytest.mark.asyncio
async def test_event_schedule_without_snapshot_does_not_await_remote_sync():
    """验证 /妮姬 日程 在无 snapshot 时立即返回提示，不同步 await 远程网络。"""
    from astrbot_plugin_nikke.main import NikkePlugin
    from unittest.mock import Mock, AsyncMock

    plugin = NikkePlugin.__new__(NikkePlugin)
    mock_cal = Mock()
    mock_cal.has_snapshot.return_value = False
    mock_cal.sync_from_source = AsyncMock()
    mock_cal.refresh_schedule_data = AsyncMock()
    plugin.calendar = mock_cal

    spawn_mock = Mock(side_effect=lambda coro: coro.close() if asyncio.iscoroutine(coro) else None)
    plugin._spawn_background_task = spawn_mock

    dummy_event = Mock()
    dummy_event.plain_result = lambda text: text

    replies = [r async for r in plugin.event_schedule(dummy_event)]
    assert len(replies) == 1
    assert "日程数据尚未就绪，正在后台同步，请稍后重试。" in replies[0]

    # 关键断言：绝对没有同步 await 任何远程刷新方法
    mock_cal.sync_from_source.assert_not_awaited()
    mock_cal.refresh_schedule_data.assert_not_awaited()
    # 验证后台任务已被触发登记
    spawn_mock.assert_called_once()


def test_source_roles_and_freshness_completeness_contract():
    """验证各数据源的 SourceRole、contributes_to_freshness 与 required_for_complete 契约规范。"""
    from astrbot_plugin_nikke.features.calendar.schedule_adapters import (
        GameKeeScheduleAdapter,
        OfficialAnnouncementScheduleAdapter,
        ManualOverrideScheduleAdapter,
    )
    from astrbot_plugin_nikke.features.calendar.canonical_models import SourceRole

    gk = GameKeeScheduleAdapter()
    assert gk.source_role == SourceRole.PRIMARY
    assert gk.contributes_to_freshness is True
    assert gk.required_for_complete is True

    off = OfficialAnnouncementScheduleAdapter()
    assert off.source_role == SourceRole.AUTHORITATIVE_SUPPLEMENT
    assert off.contributes_to_freshness is False
    assert off.required_for_complete is False

    man = ManualOverrideScheduleAdapter()
    assert man.source_role == SourceRole.LOCAL_OVERRIDE
    assert man.contributes_to_freshness is False
    assert man.required_for_complete is False
