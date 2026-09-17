# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 标准化活动与日程模型 (CanonicalEvent)。

提供：
1. 统一的标准事件模型 CanonicalEvent；
2. 自算状态机（UPCOMING / ACTIVE / ENDED，不信任上游返回的状态）；
3. 分级时间精度（EXACT / DATE_ONLY / INFERRED / UNKNOWN，杜绝伪精度倒计时）；
4. 数据质量分级（FRESH / STALE / PARTIAL / UNAVAILABLE）；
5. 与 CalendarActivity 之间的无损双向转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from .models import CalendarActivity, _aware_utc

CST = timezone(timedelta(hours=8))

VALID_PRECISIONS = frozenset({"EXACT", "DATE_ONLY", "INFERRED", "UNKNOWN"})
VALID_STATUSES = frozenset({"UPCOMING", "ACTIVE", "ENDED"})
VALID_QUALITIES = frozenset({"FRESH", "STALE", "PARTIAL", "UNAVAILABLE"})


@dataclass
class CanonicalEvent:
    id: str
    title: str
    event_type: str  # coop, union_raid, solo_raid, recruit, event, maintenance, update
    start_at: datetime | None
    end_at: datetime | None
    status: str = "ACTIVE"
    banner_url: str | None = None
    detail_url: str | None = None
    time_precision: str = "EXACT"
    sources: list[str] = field(default_factory=list)
    primary_source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    fingerprint: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("CanonicalEvent.id 不能为空")
        if not self.title:
            raise ValueError("CanonicalEvent.title 不能为空")

        if self.start_at is not None:
            self.start_at = _aware_utc(self.start_at)
        if self.end_at is not None:
            self.end_at = _aware_utc(self.end_at)
        if self.fetched_at is not None:
            self.fetched_at = _aware_utc(self.fetched_at)
        if self.updated_at is not None:
            self.updated_at = _aware_utc(self.updated_at)

        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("CanonicalEvent end_at 必须晚于 start_at")

        if self.time_precision not in VALID_PRECISIONS:
            self.time_precision = "EXACT"

        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

        # 始终基于当前时间自算状态
        self.status = self.compute_status()

    def compute_status(self, now: datetime | None = None) -> str:
        """自算状态：不相信上游，完全基于自身起止时间与当前时间判定。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        if self.start_at and current < self.start_at:
            return "UPCOMING"
        elif self.end_at and current >= self.end_at:
            return "ENDED"
        return "ACTIVE"

    def is_active(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == "ACTIVE"

    def is_upcoming(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == "UPCOMING"

    def is_ended(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == "ENDED"

    def compute_fingerprint(self) -> str:
        """计算关键业务字段指纹。"""
        parts = [
            self.title.strip(),
            self.event_type.strip(),
            self.start_at.isoformat() if self.start_at else "",
            self.end_at.isoformat() if self.end_at else "",
            (self.banner_url or "").strip(),
        ]
        text = "|".join(parts)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def remaining_display(self, now: datetime | None = None) -> str:
        """格式化剩余时间。
        严格原则：只有 EXACT 精度才显示小时/分钟倒计时；
        DATE_ONLY / INFERRED / UNKNOWN 仅显示截止日期（如 '09.20 截止'），绝不制造伪精度倒计时。
        """
        current = _aware_utc(now) if now else datetime.now(timezone.utc)

        if not self.end_at:
            return "长期开放"

        if current >= self.end_at:
            return "已结束"

        if self.time_precision != "EXACT":
            # 粗粒度时间，仅展示日期
            end_cst = self.end_at.astimezone(CST)
            return f"{end_cst.strftime('%m.%d')} 截止"

        delta = self.end_at - current
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "已结束"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"剩余 {days}天{hours}小时"
        if hours > 0:
            return f"剩余 {hours}小时{minutes}分"
        return f"剩余 {max(1, minutes)}分钟"

    def to_calendar_activity(self) -> CalendarActivity:
        """转换为现有 T2I 渲染器所使用的 CalendarActivity 实例。"""
        # 如果缺少明确起止时间，构造最小占位范围避免崩溃
        start = self.start_at or datetime.now(timezone.utc)
        end = self.end_at or (start + timedelta(days=365))
        if end <= start:
            end = start + timedelta(hours=1)

        act = CalendarActivity(
            event_id=self.id,
            title=self.title,
            start_at=start,
            end_at=end,
            category=self.event_type,
            source=self.primary_source or (self.sources[0] if self.sources else "unknown"),
            source_id=self.id,
            source_url=self.detail_url or "",
            banner_url=self.banner_url or "",
            description="",
            importance=0,
            tag=self.event_type,
            version=self.version,
        )
        return act

    @classmethod
    def from_calendar_activity(cls, act: CalendarActivity) -> CanonicalEvent:
        """从已有 CalendarActivity 无损转为 CanonicalEvent。"""
        event = cls(
            id=act.event_id,
            title=act.title,
            event_type=act.category,
            start_at=act.start_at,
            end_at=act.end_at,
            banner_url=act.banner_url or None,
            detail_url=act.source_url or None,
            time_precision="EXACT",
            sources=[act.source] if act.source else ["gamekee"],
            primary_source=act.source or "gamekee",
            version=act.version,
        )
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "event_type": self.event_type,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "status": self.status,
            "banner_url": self.banner_url,
            "detail_url": self.detail_url,
            "time_precision": self.time_precision,
            "sources": list(self.sources),
            "primary_source": self.primary_source,
            "fetched_at": self.fetched_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalEvent:
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            event_type=str(data.get("event_type", "event")),
            start_at=_aware_utc(data["start_at"]) if data.get("start_at") else None,
            end_at=_aware_utc(data["end_at"]) if data.get("end_at") else None,
            status=str(data.get("status", "ACTIVE")),
            banner_url=data.get("banner_url"),
            detail_url=data.get("detail_url"),
            time_precision=str(data.get("time_precision", "EXACT")),
            sources=list(data.get("sources", [])),
            primary_source=str(data.get("primary_source", "")),
            fetched_at=_aware_utc(data.get("fetched_at", datetime.now(timezone.utc))),
            updated_at=_aware_utc(data.get("updated_at", datetime.now(timezone.utc))),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            fingerprint=str(data.get("fingerprint", "")),
            version=int(data.get("version", 1)),
        )


def quality_badge(quality: str, updated_at: datetime | None = None) -> str:
    """生成数据状态标签。"""
    if quality == "FRESH":
        return "DATA OK"
    if quality == "STALE":
        if updated_at:
            t = updated_at.astimezone(CST).strftime("%H:%M")
            return f"STALE · UPDATED {t}"
        return "STALE DATA"
    if quality == "PARTIAL":
        return "PARTIAL DATA"
    return "DATA UNAVAILABLE"
