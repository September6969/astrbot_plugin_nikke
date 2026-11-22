# SPDX-License-Identifier: GPL-3.0-or-later
"""Operations Feed 的日程领域规则：分类标签、时间显示、紧急度、进度与背景候选。

这些纯函数原先内联在 ui/payloads/calendar.py（PR-6B G5-calendar-d 下沉）。UI
构建器只负责几何、分页、背景编码与字典组装；这里的输出与下沉前逐字节一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .canonical_models import CST
from .query import CAT_LABELS

# Operations Feed 对少数分类使用更具体的展示名，其余沿用 CAT_LABELS。
DISPLAY_CATEGORY_LABELS = {
    "double_reward": "限时双倍",
    "pass": "活动通行证",
}

# 背景优先选择的主活动分类。
PRIMARY_BACKGROUND_CATEGORIES = frozenset({"event", "story_event", "solo_raid", "union_raid"})


def display_category_label(category: str) -> str:
    """返回 Operations Feed 使用的中文分类名。"""
    return DISPLAY_CATEGORY_LABELS.get(category, CAT_LABELS.get(category, "活动"))


def precision_value(precision: Any) -> str:
    """把 TimePrecision 枚举或字符串统一为字符串。"""
    return precision.value if hasattr(precision, "value") else str(precision)


def card_datetime_label(value: datetime | None) -> str:
    """卡片 start/end 字段：北京时间 ``%m/%d %H:%M``，缺失为“未知”。"""
    return value.astimezone(CST).strftime("%m/%d %H:%M") if value else "未知"


def _feed_point(value: datetime | None, precision: str) -> str:
    if value and precision == "EXACT":
        return value.astimezone(CST).strftime("%m.%d %H:%M")
    if value and precision == "DATE_ONLY":
        return value.astimezone(CST).strftime("%m.%d")
    return "待确认"


def active_time_range(
    start_at: datetime | None, end_at: datetime | None, start_precision: str, end_precision: str
) -> str:
    """进行中卡片的精度感知时间范围，固定标注 UTC+8。"""
    start_display = _feed_point(start_at, start_precision)
    end_display = _feed_point(end_at, end_precision)
    if start_at and end_at:
        return f"{start_display} → {end_display} · UTC+8"
    if start_at:
        return f"{start_display} 起 · UTC+8"
    if end_at:
        return f"{end_display} 截止 · UTC+8"
    return "时间待确认 · UTC+8"


def active_urgency(end_at: datetime | None, end_precision: str, current: datetime) -> str:
    """紧急度：只有 EXACT 结束时间参与小时级紧迫度；非精确结束时间返回空串。"""
    urgency = "NORMAL"
    if end_precision == "EXACT" and end_at and end_at > current:
        diff_sec = (end_at - current).total_seconds()
        if diff_sec <= 3600:
            urgency = "CRITICAL"
        elif diff_sec <= 21600:
            urgency = "URGENT"
        elif diff_sec <= 86400:
            urgency = "CLOSING"
    elif end_precision != "EXACT":
        urgency = ""
    return urgency


def upcoming_start(
    start_at: datetime | None, start_precision: str, current: datetime
) -> tuple[str, str]:
    """预告卡片的开始时间显示与倒计时文案 (start_time_display, starts_in)。"""
    if start_at and start_precision == "EXACT":
        start_time_display = start_at.astimezone(CST).strftime("%m.%d %H:%M")
        diff = start_at - current
        days_diff = diff.days
        hours_diff = diff.seconds // 3600
        if days_diff >= 3:
            starts_in = f"{days_diff} 天后开始"
        elif days_diff > 0:
            starts_in = f"{days_diff} 天 {hours_diff} 小时后开始"
        elif hours_diff > 0:
            starts_in = f"{hours_diff} 小时后开始"
        else:
            mins_diff = max(1, diff.seconds // 60)
            starts_in = f"{mins_diff} 分钟后开始"
        return start_time_display, starts_in
    if start_at and start_precision == "DATE_ONLY":
        start_time_display = start_at.astimezone(CST).strftime("%m.%d")
        # 日期级开始日按北京时间理解；两侧都换算到 UTC+8 再取日期，
        # 避免北京 08:00–23:59 之间 UTC 日期落后一天导致天数少算（AUD-024）。
        diff_days = max(
            1,
            (start_at.astimezone(CST).date() - current.astimezone(CST).date()).days,
        )
        return start_time_display, f"约 {diff_days} 天后（日期级）"
    return "时间待定", "即将开始"


def activity_progress(start, end, current, start_precision: str, end_precision: str):
    """精确时间按秒计算；日期级时间只给出明确标识的按日估算。"""
    known = {"EXACT", "DATE_ONLY"}
    if start is None or end is None or start_precision not in known or end_precision not in known:
        return None, "unknown"
    if start_precision == end_precision == "EXACT":
        if end <= start or not start <= current <= end:
            return None, "unknown"
        return max(0.0, min(1.0, (current - start).total_seconds() / (end - start).total_seconds())), "exact"
    start_day = start.astimezone(CST).date()
    end_day = end.astimezone(CST).date()
    today = current.astimezone(CST).date()
    if end_day < start_day or not start_day <= today <= end_day:
        return None, "unknown"
    # 日期级结束日期包含当日，不把未知时分冒充精确时间。
    duration_days = (end_day - start_day).days + 1
    return (today - start_day).days / duration_days, "date"


def background_candidate_ids(active: Iterable[Any], upcoming: Iterable[Any]) -> list[str]:
    """背景候选只来自当前日程：进行中主活动 → 其余进行中 → 即将开始。

    与 docs/operations/BLABLA_CALENDAR_SOURCE.md 的文档规则一致（PR-6B G5-calendar-e）：
    不回退到视觉缓存清单中任意旧事件（例如已结束活动或已删除来源）的图片。
    """
    active = list(active)
    candidate_ids: list[str] = []
    for event in active:
        if event.category in PRIMARY_BACKGROUND_CATEGORIES:
            candidate_ids.append(event.event_id)
    for event in active:
        if event.event_id not in candidate_ids:
            candidate_ids.append(event.event_id)
    for event in upcoming:
        if event.event_id not in candidate_ids:
            candidate_ids.append(event.event_id)
    return candidate_ids


__all__ = [
    "DISPLAY_CATEGORY_LABELS",
    "PRIMARY_BACKGROUND_CATEGORIES",
    "active_time_range",
    "active_urgency",
    "activity_progress",
    "background_candidate_ids",
    "card_datetime_label",
    "display_category_label",
    "precision_value",
    "upcoming_start",
]
