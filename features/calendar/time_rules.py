# SPDX-License-Identifier: GPL-3.0-or-later
"""唯一共享的 Calendar 时间范围、精度与提醒资格规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Sequence

class TimePrecision(str, Enum):
    EXACT = "EXACT"
    DATE_ONLY = "DATE_ONLY"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class EventStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"


CST = timezone(timedelta(hours=8))


def _aware_utc(value: Any) -> datetime:
    """强制转换为 timezone-aware UTC datetime，拒绝 naive datetime。"""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"时间必须是 ISO 8601 字符串或 datetime 对象: {value!r}")
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError(f"时间必须包含明确时区信息 (拒绝 naive datetime): {value!r}")
    return parsed.astimezone(timezone.utc)


def resolve_event_status(
    event: Any,
    now: datetime | None = None,
    evidence: Sequence[Any] | None = None,
) -> str:
    """在单一时间规则入口动态解析日程状态，绝不信任快照中的旧状态。"""
    current = _aware_utc(now) if now else datetime.now(timezone.utc)
    if hasattr(event, "is_valid_interval") and not event.is_valid_interval:
        return EventStatus.INVALID.value

    start = getattr(event, "start_at", None)
    end = getattr(event, "end_at", None)
    if start and end and end <= start:
        return EventStatus.INVALID.value
    if getattr(event, "is_cancelled", False):
        return EventStatus.CANCELLED.value
    if evidence and any(item.is_cancelled for item in evidence):
        return EventStatus.CANCELLED.value
    if start is None and end is None:
        return EventStatus.UNKNOWN.value

    has_started = getattr(event, "has_started_evidence", False)
    if not has_started and evidence:
        has_started = any(item.is_started_evidence for item in evidence)
    if start is None:
        if not has_started:
            return EventStatus.UNKNOWN.value
        return EventStatus.ENDED.value if end is not None and current >= end else EventStatus.ACTIVE.value
    if current < start:
        return EventStatus.UPCOMING.value
    if end is None:
        return EventStatus.ACTIVE.value
    if current >= end:
        return EventStatus.ENDED.value
    return EventStatus.ACTIVE.value


@dataclass(frozen=True, slots=True)
class CalendarEventGroups:
    ending_soon: tuple[Any, ...]
    active: tuple[Any, ...]
    active_including_soon: tuple[Any, ...]
    upcoming: tuple[Any, ...]


class CalendarTimeRules:
    """封装展示窗口规则；事件状态仍由 canonical resolver 唯一计算。"""

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """只接受 7、14、30 天，默认 14 天。"""
        if value is None or value == "":
            return 14
        if type(value) is bool:
            raise ValueError("日程范围只支持 7、14、30 天")
        if type(value) is int:
            if value in (7, 14, 30):
                return value
            raise ValueError("日程范围只支持 7、14、30 天")
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return 14
            if normalized.isascii() and normalized.isdecimal():
                days = int(normalized)
                if days in (7, 14, 30):
                    return days
        raise ValueError("日程范围只支持 7、14、30 天")

    @staticmethod
    def classify_events(
        events: Sequence[Any], now: datetime, horizon_days: int = 14
    ) -> CalendarEventGroups:
        current = _aware_utc(now)
        horizon = current + timedelta(days=horizon_days)
        ending_soon: list[Any] = []
        active: list[Any] = []
        active_including_soon: list[Any] = []
        upcoming: list[Any] = []
        for event in events:
            status = resolve_event_status(event, current)
            if status == EventStatus.ACTIVE.value:
                active_including_soon.append(event)
                if (
                    event.end_at is not None
                    and event.end_precision == TimePrecision.EXACT.value
                    and event.end_at - current <= timedelta(hours=24)
                ):
                    ending_soon.append(event)
                else:
                    active.append(event)
            elif (
                status == EventStatus.UPCOMING.value
                and event.start_at is not None
                and event.start_at <= horizon
            ):
                upcoming.append(event)
        return CalendarEventGroups(
            tuple(ending_soon),
            tuple(active),
            tuple(active_including_soon),
            tuple(upcoming),
        )

    @staticmethod
    def reminder_deadlines(
        events: Sequence[Any], now: datetime
    ) -> list[Any]:
        current = _aware_utc(now)
        eligible = [
            event for event in events
            if event.is_valid_interval
            and event.end_precision == TimePrecision.EXACT.value
            and event.end_at is not None
            and event.end_at > current
            and resolve_event_status(event, current) == EventStatus.ACTIVE.value
        ]
        return sorted(eligible, key=lambda event: (event.end_at, event.id))
