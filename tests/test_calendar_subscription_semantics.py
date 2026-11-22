# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-3A：通行证精确分类、提醒阻断边界、时间文案与公告/日程双订阅解耦。"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.features.announcement.application import AnnouncementApplication
from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, SourceHealth
from astrbot_plugin_nikke.features.calendar.merge import CalendarMergePolicy
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService
from astrbot_plugin_nikke.features.calendar.subscriptions import (
    pass_category,
    remaining_hours_text,
    sync_blocks_reminders,
)

UTC = timezone.utc


def _event(title, *, official_type=None, start=None, end=None, precision="EXACT"):
    now = datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
    return CanonicalEvent(
        id="e", title=title, event_type="pass",
        start_at=start or now - timedelta(days=1), end_at=end or now + timedelta(hours=10),
        time_precision=precision,
        metadata={"official_type": official_type} if official_type else {},
    )


# ------------------------------------------------------------------ AUD-012 通行证

@pytest.mark.parametrize(
    ("title", "official", "expected"),
    [
        ("月度通行证 · 冬季", "SeasonPass", "monthly_pass"),
        ("活动通行证 · 冬季限定", "EventPass", "event_pass"),
        ("Winter Pass", "SeasonPass", "monthly_pass"),          # 官方类型优先于标题
        ("11月 Pass", "EventPass", "event_pass"),
        ("月度通行证 · 冬季", None, "monthly_pass"),             # 无官方类型时按标题回退
        ("活动通行证 · 冬季", None, "event_pass"),
    ],
)
def test_pass_category_prefers_official_type(title, official, expected) -> None:
    assert pass_category(_event(title, official_type=official)) == expected


# ------------------------------------------------------------------ AUD-012 PARTIAL 不阻断

def _calendar(error, *, failing=False):
    return SimpleNamespace(last_sync_error=error, has_failed_sources=lambda: failing)


def test_partial_parse_warning_does_not_block_all_reminders() -> None:
    assert not sync_blocks_reminders(_calendar(""))
    assert not sync_blocks_reminders(_calendar("blabla: 数据范围不完整，保留未验证的旧记录"))


@pytest.mark.parametrize(
    "calendar",
    [
        _calendar("blabla: timeout", failing=True),
        _calendar("persistence failed: disk full"),
        _calendar("blabla: 数据范围不完整，保留未验证的旧记录", failing=True),
        SimpleNamespace(last_sync_error="blabla: timeout"),  # 无法判断来源健康时 fail-closed
    ],
)
def test_real_failures_still_block_reminders(calendar) -> None:
    assert sync_blocks_reminders(calendar)


def test_default_ttl_exceeds_scheduler_interval() -> None:
    default = inspect.signature(ScheduleService.__init__).parameters["ttl_seconds"].default
    assert default == 900.0 > 300.0


def test_expired_snapshot_is_not_promoted_back_to_stale() -> None:
    adapter = SimpleNamespace(source_name="blabla", required_for_complete=True, contributes_to_freshness=True)
    service = SimpleNamespace(
        adapters=[adapter], _events={"e": object()}, _source_datasets={"blabla": {"e": object()}},
        _source_health={"blabla": SourceHealth("blabla", consecutive_failures=3, completeness="COMPLETE")},
        last_success_at=datetime.now(UTC) - timedelta(days=5), ttl_seconds=900.0,
        freshness="FRESH", coverage="COMPLETE",
    )
    CalendarMergePolicy._update_health_state(service)
    assert service.freshness == "EXPIRED"

    service.last_success_at = datetime.now(UTC) - timedelta(seconds=60)
    CalendarMergePolicy._update_health_state(service)
    assert service.freshness == "STALE"  # 新近成功但当前全部失败：FRESH 降为 STALE


# ------------------------------------------------------------------ 倒计时文案

@pytest.mark.parametrize(
    ("remaining", "expected"),
    [(timedelta(minutes=30), "剩余不足1小时"), (timedelta(hours=1, minutes=1), "剩余不足2小时"),
     (timedelta(hours=23, minutes=30), "剩余不足24小时")],
)
def test_remaining_hours_text_is_not_overcounted(remaining, expected) -> None:
    assert remaining_hours_text(remaining) == expected


def test_upcoming_event_shows_time_until_start() -> None:
    now = datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
    event = _event("活动", start=now + timedelta(hours=5, minutes=30), end=now + timedelta(days=7))
    assert event.remaining_display(now) == "距开始 5小时30分"


def test_date_only_deadline_uses_beijing_dates_on_both_sides() -> None:
    # 北京时间 11-23 00:30 == UTC 11-22 16:30；截止北京时间 11-23 23:59（UTC 15:59）→ 今日截止
    now = datetime(2026, 11, 22, 16, 30, tzinfo=UTC)
    end = datetime(2026, 11, 23, 15, 59, tzinfo=UTC)
    event = _event("活动", start=now - timedelta(days=2), end=end, precision="DATE_ONLY")
    assert event.remaining_display(now) == "11.23 截止 (今日截止)"


# ------------------------------------------------------------------ Decision 4b 解耦

@pytest.mark.asyncio
async def test_admin_announcement_push_never_sends_calendar_deadlines() -> None:
    announcements = SimpleNamespace(
        list_announcements=lambda limit: [],
        list_active_deadlines=lambda: pytest.fail("公告推送不应再读取日程截止"),
    )
    delivery = SimpleNamespace(dispatch=AsyncMock(return_value={"succeeded": 0, "failed": 0, "unknown": 0}))
    application = AnnouncementApplication(announcements=announcements, delivery=delivery)

    await application.dispatch_pushes(AsyncMock())

    assert delivery.dispatch.await_args.args[1] == ()


# ------------------------------------------------------------------ 未决投递上限

class _Store:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


@pytest.mark.asyncio
async def test_delivery_stops_when_pending_intents_reach_cap(monkeypatch) -> None:
    store = _Store()
    delivery = AnnouncementDelivery(store)
    monkeypatch.setattr(AnnouncementDelivery, "MAX_PENDING_INTENTS", 2)
    state = delivery._state()
    now = datetime.now(UTC)
    for index in range(2):
        state["dispatch_intents"][f"k{index}"] = {
            "status": AnnouncementDelivery.UNKNOWN_AFTER_ACTION, "created_at": now.isoformat(),
            "target": "t", "entity_id": str(index), "version": 1, "push_type": "announcement",
        }
    store.set_setting(AnnouncementDelivery.SETTING, state)
    sender = AsyncMock(return_value=True)

    result = await delivery.dispatch([], (), sender, now=now)

    assert result["blocked"] == 2
    assert delivery.pending_count() == 2
    sender.assert_not_awaited()
