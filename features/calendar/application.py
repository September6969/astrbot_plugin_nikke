# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 查询与操作用例。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .canonical_models import (
    EventStatus,
    QueryContext,
    resolve_event_status,
)


class CalendarQueryService(Protocol):
    """Calendar 查询与刷新所需的服务端口。"""

    last_updated_at: str | None
    last_sync_error: str
    data_quality: str

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """验证支持的查询范围。"""

    def freeze_query_context(self, now: datetime | None = None) -> QueryContext:
        """冻结当前本地日程快照。"""

    def has_snapshot(self) -> bool:
        """返回是否已有可查询快照。"""

    def activity_count(self) -> int:
        """返回当前快照中的活动数。"""

    def format_schedule_text(
        self,
        days: int,
        now: datetime,
        fallback_error: str = "",
        *,
        context: QueryContext | None = None,
    ) -> str:
        """用给定查询上下文生成文本回退。"""

    def cached_visual_event_ids(self) -> tuple[str, ...]:
        """返回本地已有活动宣传图的事件键。"""

    def resolve_visual_path(self, event_id: str) -> Path | None:
        """读取本地活动宣传图，不执行网络请求。"""

    async def refresh_schedule_data(self) -> tuple[bool, str]:
        """从日程来源刷新并持久化快照。"""


@dataclass(frozen=True, slots=True)
class CalendarScheduleSnapshot:
    """一次热查询使用的不可变快照及展示元数据。"""

    context: QueryContext
    horizon_days: int
    has_snapshot: bool
    activity_count: int
    data_quality: str
    last_updated_at: str | None
    sync_warning: str
    background_path: Path | None = None
    fallback_text: str = ""
    service_available: bool = True


@dataclass(frozen=True, slots=True)
class CalendarRefreshResult:
    """显式日程刷新操作的框架无关结果。"""

    success: bool
    message: str
    activity_count: int
    data_quality: str


class CalendarApplication:
    """集中管理本地热查询快照与显式日程刷新。"""

    def __init__(
        self,
        calendar: CalendarQueryService | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._calendar = calendar
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def query_schedule(
        self,
        horizon: Any = None,
        *,
        now: datetime | None = None,
    ) -> CalendarScheduleSnapshot:
        """只读并冻结已有快照；此热查询不触发日程或背景图片网络请求。"""
        days = (
            self._calendar.normalize_horizon(horizon)
            if self._calendar is not None
            else self.normalize_horizon(horizon)
        )
        current = now or self._clock()
        if self._calendar is None:
            context = QueryContext(
                now=current,
                snapshot_version="unavailable",
                events=(),
                source_health={},
                freshness="EXPIRED",
                coverage="UNAVAILABLE",
                health_display="SCHEDULE DATA UNAVAILABLE",
                source_display="LOCAL SNAPSHOT",
            )
            return CalendarScheduleSnapshot(
                context=context,
                horizon_days=days,
                has_snapshot=False,
                activity_count=0,
                data_quality="SCHEDULE DATA UNAVAILABLE",
                last_updated_at=None,
                sync_warning="",
                fallback_text="功能尚未就绪，正在同步官方日程，请稍候。",
                service_available=False,
            )

        context = self._calendar.freeze_query_context(current)
        has_snapshot = self._calendar.has_snapshot()
        warning = self._calendar.last_sync_error
        fallback_text = self._calendar.format_schedule_text(
            days, context.now, warning, context=context
        )
        background_path = self._resolve_background_path(context, days)
        return CalendarScheduleSnapshot(
            context=context,
            horizon_days=days,
            has_snapshot=has_snapshot,
            activity_count=self._calendar.activity_count(),
            data_quality=self._calendar.data_quality,
            last_updated_at=self._calendar.last_updated_at,
            sync_warning=warning,
            background_path=background_path,
            fallback_text=fallback_text,
        )

    async def refresh_schedule(self) -> CalendarRefreshResult:
        """执行被显式请求的公开只读日程源刷新。"""
        if self._calendar is None:
            return CalendarRefreshResult(
                success=False,
                message="日程服务尚未就绪",
                activity_count=0,
                data_quality="SCHEDULE DATA UNAVAILABLE",
            )
        success, message = await self._calendar.refresh_schedule_data()
        return CalendarRefreshResult(
            success=success,
            message=message,
            activity_count=self._calendar.activity_count(),
            data_quality=self._calendar.data_quality,
        )

    def reminder_deadlines(self, fallback: list[Any]) -> list[Any]:
        """优先返回日程快照的截止提醒，否则使用调用方的本地回退。"""
        if self._calendar is None:
            return fallback
        if self._calendar.has_snapshot() and self._calendar.activity_count() > 0:
            return self._calendar.list_reminder_deadlines()
        return fallback

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """只接受 7、14、30 天；服务未装配时仍可返回准确用法错误。"""
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

    def _resolve_background_path(
        self, context: QueryContext, horizon_days: int
    ) -> Path | None:
        """按 Operations Feed 优先级选取已缓存背景，不触发缓存同步。"""
        if self._calendar is None:
            return None
        active: list[Any] = []
        upcoming: list[Any] = []
        horizon = context.now + timedelta(days=horizon_days)
        for event in context.events:
            status = resolve_event_status(event, context.now)
            if status == EventStatus.ACTIVE:
                active.append(event)
            elif status == EventStatus.UPCOMING and (
                event.start_at is None or event.start_at <= horizon
            ):
                upcoming.append(event)

        candidate_ids: list[str] = []
        primary_categories = {"event", "solo_raid", "union_raid"}
        for event in active:
            if event.category in primary_categories:
                candidate_ids.append(event.event_id)
        for event in active:
            if event.event_id not in candidate_ids:
                candidate_ids.append(event.event_id)
        for event in upcoming:
            if event.event_id not in candidate_ids:
                candidate_ids.append(event.event_id)
        cached_ids = getattr(self._calendar, "cached_visual_event_ids", None)
        if callable(cached_ids):
            for event_id in cached_ids():
                if event_id not in candidate_ids:
                    candidate_ids.append(str(event_id))

        for event_id in candidate_ids:
            path = self._calendar.resolve_visual_path(event_id)
            if isinstance(path, Path) and path.is_file():
                return path
        return None
