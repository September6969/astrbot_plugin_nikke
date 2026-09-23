# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 查询快照、窗口投影与兼容文本输出。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import CalendarActivity, _aware_utc
from .content_quality import sort_operations_display_events
from .canonical_models import CanonicalEvent, QueryContext, compute_health_badge
from .time_rules import CalendarTimeRules

CAT_LABELS = {
    "coop": "协同",
    "union_raid": "联盟突袭",
    "solo_raid": "单人突袭",
    "special_arena": "特殊竞技场",
    "mini_game": "小游戏",
    "limited_stage": "限时通关",
    "double_reward": "活动",
    "recruit": "招募",
    "pass": "活动",
    "costume_gacha": "转盘时装",
    "limited_costume": "限定时装",
    "maintenance": "维护",
    "update": "更新",
    "announcement": "公告",
    "package": "礼包",
    "event": "活动",
}

from .canonical_models import CST

class CalendarScheduleQueries:


    @staticmethod
    def normalize_horizon(value: Any) -> int:
        return CalendarTimeRules.normalize_horizon(value)

    @staticmethod
    def freeze_query_context(service, now: datetime | None = None) -> QueryContext:
        """冻结单次查询上下文 (QueryContext)。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        service._update_health_state()

        used_sources = set()
        for ev in service._events.values():
            used_sources.update(ev.sources)
        if not used_sources:
            source_display = "LOCAL SNAPSHOT"
        else:
            source_display = " + ".join(sorted(s.upper() for s in used_sources))

        return QueryContext(
            now=current,
            snapshot_version=service._snapshot_version,
            events=tuple(service._events.values()),
            source_health=dict(service._source_health),
            freshness=service.freshness,
            coverage=service.coverage,
            health_display=compute_health_badge(service.freshness, service.coverage),
            source_display=source_display,
        )

    @staticmethod
    def get_current(service) -> list[CanonicalEvent]:
        return list(service._events.values())

    @staticmethod
    def list_window(service, days: int = 14, now: datetime | None = None) -> list[CalendarActivity]:
        """查询在指定 horizon 范围内的活动。"""
        context = service.freeze_query_context(now)
        groups = CalendarTimeRules.classify_events(context.events, context.now, days)
        active = groups.active_including_soon
        ordered = sort_operations_display_events(active, "ACTIVE")
        ordered.extend(sort_operations_display_events(groups.upcoming, "UPCOMING"))
        return [event.to_calendar_activity() for event in ordered]

    @staticmethod
    def list_reminder_deadlines(service, now: datetime | None = None) -> list[CalendarActivity]:
        """只返回有效、ACTIVE 且具备 EXACT 截止时间的活动。"""
        context = service.freeze_query_context(now)
        activities: list[CalendarActivity] = []
        for event in CalendarTimeRules.reminder_deadlines(context.events, context.now):
            activity = event.to_calendar_activity()
            object.__setattr__(activity, "end_precision", event.end_precision)
            activities.append(activity)
        return activities

    @staticmethod
    def group_window(
        service,
        days: int = 14,
        now: datetime | None = None,
        *,
        context: QueryContext | None = None,
    ) -> dict[str, list[CalendarActivity]]:
        """按共享的时间精度规则分组展示活动。"""
        ctx = context or service.freeze_query_context(now)
        groups = CalendarTimeRules.classify_events(
            ctx.events, ctx.now, service.normalize_horizon(days)
        )
        soon = sort_operations_display_events(groups.ending_soon, "ACTIVE")
        active = sort_operations_display_events(groups.active, "ACTIVE")
        upcoming = sort_operations_display_events(groups.upcoming, "UPCOMING")
        return {
            "ending_soon": [event.to_calendar_activity() for event in soon],
            "active": [event.to_calendar_activity() for event in active],
            "upcoming": [event.to_calendar_activity() for event in upcoming],
        }

    @staticmethod
    def format_schedule_text(
        service,
        days: int = 14,
        now: datetime | None = None,
        fallback_error: str = "",
        *,
        context: QueryContext | None = None,
    ) -> str:
        """基于同一 QueryContext 输出文本回退。"""
        ctx = context or service.freeze_query_context(now)
        if not service._has_snapshot:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方日程，请稍候。"

        lines: list[str] = [f"【NIKKE 近期日程 · 未来 {days} 天】"]
        if service.content_updated_at:
            try:
                updated_dt = service.content_updated_at.astimezone(CST)
                lines.append(f"（{ctx.health_display} · 数据源: {ctx.source_display} · 更新: {updated_dt.strftime('%m-%d %H:%M')}）")
            except Exception:
                pass

        error_to_show = fallback_error or service.last_sync_error
        if error_to_show:
            lines.append(f"⚠️ 日程数据同步失败：{error_to_show}，以下为本地缓存。")

        groups = service.group_window(days, ctx.now, context=ctx)
        soon = groups["ending_soon"]
        active = groups["active"]
        upcoming = groups["upcoming"]
        if not soon and not active and not upcoming:
            lines.append(f"未来 {days} 天暂无已记录活动。")
            return "\n".join(lines).strip()

        def format_item(activity: CalendarActivity) -> str:
            label = CAT_LABELS.get(activity.category, "活动")
            start = activity.start_at.astimezone(CST).strftime("%m/%d %H:%M")
            end = activity.end_at.astimezone(CST).strftime("%m/%d %H:%M")
            return f"• [{label}] {activity.title}\n  {start} → {end} · {activity.remaining_display(ctx.now)}"

        for heading, events in (("【即将结束】", soon), ("【进行中】", active), ("【即将开始】", upcoming)):
            if events:
                lines.append(heading)
                lines.extend(format_item(activity) for activity in events)
        return "\n".join(lines).strip()
