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

import json
from datetime import datetime, timedelta, timezone
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
    assert service.coverage == Coverage.PARTIAL.value
    assert service.data_quality == "PARTIAL DATA"


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
