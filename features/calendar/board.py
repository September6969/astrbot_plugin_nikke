# SPDX-License-Identifier: GPL-3.0-or-later
"""日程命令的卡池 / 活动 / 皮肤 / 突袭分类视图（04）。

只消费已经同步并冻结的官方日程快照，按类型重新分组并计算进行状态与截止倒计时；
不发起网络请求，也不推断上游未提供的字段。UP 概率等字段缺失时显式标记为缺失。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

CST = timezone(timedelta(hours=8))

GROUPS: tuple[str, ...] = ("卡池", "活动", "皮肤", "突袭")
GROUP_ALIASES = {
    "卡池": "卡池", "招募": "卡池", "pickup": "卡池", "gacha": "卡池",
    "活动": "活动", "event": "活动", "events": "活动",
    "皮肤": "皮肤", "时装": "皮肤", "costume": "皮肤", "skin": "皮肤",
    "突袭": "突袭", "raid": "突袭", "raids": "突袭",
}
_TYPE_TO_GROUP = {
    "recruit": "卡池",
    "costume_gacha": "皮肤",
    "limited_costume": "皮肤",
    "union_raid": "突袭",
    "solo_raid": "突袭",
}
# 只有这些类型进入“活动”；维护、版本更新、礼包与公告不是可参与活动。
_ACTIVITY_TYPES = frozenset(
    {
        "event", "story_event", "coop", "pass", "double_reward",
        "login", "free_reward", "mini_game", "limited_stage", "special_arena",
    }
)
# 可作为 UP 概率出现的字段；只有结构化数值才展示，避免把营销文案当概率。
_UP_RATE_KEYS = ("up_rate", "up_rates", "pickup_rate", "pickup_rates", "featured_rate")


def normalize_group(value: str) -> str | None:
    """把用户输入的类型名归一为四个展示分组；未知类型返回 None。"""
    return GROUP_ALIASES.get(str(value or "").strip().casefold())


def group_of(event: Any) -> str | None:
    """按 event_type 判定展示分组；无法归类的类型返回 None（不猜测）。"""
    event_type = str(getattr(event, "event_type", getattr(event, "category", "")) or "")
    if event_type in _TYPE_TO_GROUP:
        return _TYPE_TO_GROUP[event_type]
    if event_type in _ACTIVITY_TYPES:
        return "活动"
    return None


def _cst_text(value: datetime | None) -> str:
    if not isinstance(value, datetime):
        return "时间待确认"
    return value.astimezone(CST).strftime("%m-%d %H:%M")


def _exact(value: Any) -> bool:
    return str(value or "") == "EXACT"


def _countdown(event: Any, now: datetime, status: str) -> str:
    """仅在时间精确时给出分秒级倒计时；粗粒度时间只显示日期。"""
    if status == "进行中":
        end = getattr(event, "end_at", None)
        if not isinstance(end, datetime):
            return "结束时间未知"
        if not _exact(getattr(event, "end_precision", "")):
            return f"{_cst_text(end)} 当日截止（仅日期）"
        remaining = end - now
        if remaining <= timedelta(0):
            return "已结束"
        return "剩余 " + _duration_text(remaining)
    if status == "即将开始":
        start = getattr(event, "start_at", None)
        if not isinstance(start, datetime):
            return "开始时间未知"
        if not _exact(getattr(event, "start_precision", "")):
            return f"{_cst_text(start)} 开始（仅日期）"
        return "距开始 " + _duration_text(start - now)
    if status == "已结束":
        return "已结束"
    return "时间待确认"


def _duration_text(value: timedelta) -> str:
    total = max(0, int(value.total_seconds()))
    days, remainder = divmod(total, 86400)
    hours = remainder // 3600
    minutes = (remainder % 3600) // 60
    if days > 0:
        return f"{days}天{hours}小时"
    if hours > 0:
        return f"{hours}小时{minutes}分钟"
    return f"{max(1, minutes)}分钟"


def status_text(event: Any, now: datetime) -> str:
    """用统一的领域状态解析，不读取快照里的旧状态字段。"""
    from .time_rules import EventStatus, resolve_event_status

    raw = resolve_event_status(event, now)
    return {
        EventStatus.ACTIVE.value: "进行中",
        EventStatus.UPCOMING.value: "即将开始",
        EventStatus.ENDED.value: "已结束",
        EventStatus.CANCELLED.value: "已取消",
        EventStatus.INVALID.value: "时间无效",
        EventStatus.UNKNOWN.value: "时间待确认",
    }.get(raw, "时间待确认")


def up_rate_of(event: Any) -> tuple[str | None, bool]:
    """读取结构化 UP 概率；返回 (展示文本, 是否缺失)。

    只接受 metadata 中的数值或数值映射；没有可靠字段时返回缺失，绝不写“未知百分比”之类
    看似已公布的数值。
    """
    metadata = getattr(event, "metadata", None)
    if not isinstance(metadata, dict):
        return None, True
    for key in _UP_RATE_KEYS:
        value = metadata.get(key)
        text = _format_rate(value)
        if text is not None:
            source = str(metadata.get(f"{key}_source") or "").strip()
            return (f"{text}（来源：{source}）" if source else text), False
    return None, True


def _format_rate(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return f"{value:g}%"
    if isinstance(value, dict):
        parts: list[str] = []
        for key in sorted(value, key=lambda item: str(item)):
            item = value[key]
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return None
            if isinstance(item, float) and not math.isfinite(item):
                return None
            parts.append(f"{key} {item:g}%")
        return "、".join(parts) if parts else None
    return None


@dataclass(frozen=True, slots=True)
class BoardItem:
    """一条分类后的日程记录。"""

    group: str
    event_id: str
    title: str
    status: str
    start_at: datetime | None
    end_at: datetime | None
    start_display: str
    end_display: str
    countdown: str
    source: str
    up_rate: str | None
    up_rate_missing: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "id": self.event_id,
            "title": self.title,
            "status": self.status,
            "start": self.start_display,
            "end": self.end_display,
            "countdown": self.countdown,
            "source": self.source,
            "up_rate": self.up_rate,
        }


@dataclass(frozen=True, slots=True)
class Board:
    """一次冻结快照生成的四类日历视图。"""

    now: datetime
    groups: tuple[str, ...]
    items: tuple[BoardItem, ...]
    unclassified: int = 0

    def by_group(self, group: str) -> tuple[BoardItem, ...]:
        return tuple(item for item in self.items if item.group == group)

    @property
    def up_rate_missing(self) -> bool:
        return any(item.up_rate_missing for item in self.by_group("卡池"))


def build_board(
    events: Iterable[Any],
    now: datetime,
    *,
    groups: Sequence[str] | None = None,
) -> Board:
    """把快照事件按类型分组并计算状态；未知类型计入 unclassified。"""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("日程分类需要带时区的当前时间")
    current = now.astimezone(CST)
    selected = tuple(groups) if groups else GROUPS
    unknown_groups = [group for group in selected if group not in GROUPS]
    if unknown_groups:
        raise ValueError("未知日程类型：" + "、".join(unknown_groups))

    items: list[BoardItem] = []
    unclassified = 0
    for event in events:
        group = group_of(event)
        if group is None:
            unclassified += 1
            continue
        if group not in selected:
            continue
        status = status_text(event, current)
        up_rate, up_missing = up_rate_of(event)
        # 只有卡池才讨论 UP 概率；其他类型不产生“缺失概率”噪音。
        if group != "卡池":
            up_rate, up_missing = None, False
        metadata = getattr(event, "metadata", None)
        source = str(
            getattr(event, "primary_source", "")
            or (getattr(event, "sources", None) or [""])[0]
            or (metadata.get("source", "") if isinstance(metadata, dict) else "")
            or "未知来源"
        )
        items.append(
            BoardItem(
                group=group,
                event_id=str(getattr(event, "id", getattr(event, "event_id", "")) or ""),
                title=str(getattr(event, "title", "") or "未命名日程"),
                status=status,
                start_at=getattr(event, "start_at", None),
                end_at=getattr(event, "end_at", None),
                start_display=_cst_text(getattr(event, "start_at", None)),
                end_display=_cst_text(getattr(event, "end_at", None)),
                countdown=_countdown(event, current, status),
                source=source,
                up_rate=up_rate,
                up_rate_missing=up_missing,
            )
        )
    # 进行中优先，其次即将开始，再按结束/开始时间与标题稳定排序。
    order = {"进行中": 0, "即将开始": 1, "时间待确认": 2, "已取消": 3, "时间无效": 4, "已结束": 5}
    items.sort(
        key=lambda item: (
            GROUPS.index(item.group),
            order.get(item.status, 6),
            item.end_at or datetime.max.replace(tzinfo=timezone.utc),
            item.start_at or datetime.max.replace(tzinfo=timezone.utc),
            item.event_id,
        )
    )
    return Board(now=current, groups=selected, items=tuple(items), unclassified=unclassified)


def render_board(board: Board) -> str:
    """渲染分类日历文本；UP 概率缺失时给出明确说明。"""
    lines = [
        "【NIKKE 日程 · 卡池与活动日历】",
        f"当前时间：{board.now.strftime('%Y-%m-%d %H:%M')}（北京时间 UTC+8）",
    ]
    if board.up_rate_missing:
        lines.append("UP 概率：官方日程未提供可靠概率字段（缺失，未推断）。")
    if not board.items:
        lines.append("当前快照在所选类型下没有记录；不代表游戏内没有活动。")
        return "\n".join(lines)
    for group in board.groups:
        rows = board.by_group(group)
        if not rows:
            continue
        lines.extend(("", f"【{group}】"))
        for item in rows:
            lines.append(f"· {item.title}")
            lines.append(
                f"  {item.status} · {item.start_display} → {item.end_display}"
                f"（北京时间） · {item.countdown}"
            )
            detail = f"  来源：{item.source}"
            if item.up_rate:
                detail += f" · UP 概率：{item.up_rate}"
            elif item.up_rate_missing:
                detail += " · UP 概率：上游未提供（缺失）"
            lines.append(detail)
    if board.unclassified:
        lines.extend(("", f"另有 {board.unclassified} 条记录不属于卡池/活动/皮肤/突袭，未在此视图展示。"))
    return "\n".join(lines)


__all__ = [
    "CST",
    "GROUPS",
    "Board",
    "BoardItem",
    "build_board",
    "group_of",
    "normalize_group",
    "render_board",
    "status_text",
    "up_rate_of",
]
