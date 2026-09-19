# SPDX-License-Identifier: GPL-3.0-or-later
"""结构化活动日程数据模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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


@dataclass(slots=True)
class CalendarActivity:
    event_id: str
    title: str
    start_at: datetime
    end_at: datetime
    category: str = "event"
    source: str = "gamekee"
    source_id: str = ""
    source_url: str = ""
    banner_url: str = ""
    key_visual_url: str = ""
    image_urls: tuple[str, ...] = ()
    description: str = ""
    importance: int = 0
    tag: str = ""
    activity_kind: str = ""
    version: int = 1
    start_precision: str = "EXACT"
    end_precision: str = "EXACT"

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id 必须是非空字符串")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title 必须是非空字符串")
        if type(self.importance) is not int:
            raise ValueError(f"importance 必须是真正的整数: {self.importance!r}")
        if type(self.version) is not int or self.version < 1:
            raise ValueError(f"version 必须是正整数: {self.version!r}")

        urls = self.image_urls
        if isinstance(urls, list):
            urls = tuple(urls)
        if not isinstance(urls, tuple) or any(not isinstance(url, str) for url in urls):
            raise ValueError("image_urls 必须是字符串 tuple/list")
        object.__setattr__(self, "image_urls", tuple(url for url in urls if url))

        utc_start = _aware_utc(self.start_at)
        utc_end = _aware_utc(self.end_at)
        if utc_end <= utc_start:
            raise ValueError(f"结束时间必须严格晚于开始时间 (end_at > start_at): {utc_start} -> {utc_end}")
        object.__setattr__(self, "start_at", utc_start)
        object.__setattr__(self, "end_at", utc_end)

    @property
    def name(self) -> str:
        return self.title

    @property
    def deadline_version(self) -> int:
        return self.version

    @property
    def visual_candidates(self) -> tuple[str, ...]:
        """按 KV > 图集 > banner 的顺序返回去重后的远端视觉素材 URL。"""
        ordered = [self.key_visual_url, *self.image_urls, self.banner_url]
        seen: set[str] = set()
        result: list[str] = []
        for value in ordered:
            value = str(value or "").strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return tuple(result)

    def is_active(self, now: datetime | None = None) -> bool:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        return self.start_at <= current <= self.end_at

    def is_upcoming(self, now: datetime | None = None) -> bool:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        return current < self.start_at

    def is_ended(self, now: datetime | None = None) -> bool:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        return current > self.end_at

    def remaining_display(self, now: datetime | None = None) -> str:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        if current > self.end_at:
            return "已结束"
        if getattr(self, "end_precision", "EXACT") != "EXACT":
            from datetime import timedelta
            CST = timezone(timedelta(hours=8))
            return f"{self.end_at.astimezone(CST).strftime('%m.%d')} 截止"
        if current < self.start_at:
            diff = self.start_at - current
            days = diff.days
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            if days > 0:
                return f"距开始 {days}天 {hours}小时"
            if hours > 0:
                return f"距开始 {hours}小时 {minutes}分钟"
            return f"距开始 {max(1, minutes)}分钟"

        diff = self.end_at - current
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        if days > 0:
            return f"剩余 {days}天 {hours}小时"
        if hours > 0:
            return f"剩余 {hours}小时 {minutes}分钟"
        return f"剩余 {max(1, minutes)}分钟"

    @property
    def fingerprint(self) -> str:
        data = {
            "title": self.title,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "category": self.category,
            "source": self.source,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "banner_url": self.banner_url,
            "key_visual_url": self.key_visual_url,
            "image_urls": list(self.image_urls),
            "description": self.description,
            "importance": self.importance,
            "tag": self.tag,
            "activity_kind": self.activity_kind,
        }
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "category": self.category,
            "source": self.source,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "banner_url": self.banner_url,
            "key_visual_url": self.key_visual_url,
            "image_urls": list(self.image_urls),
            "description": self.description,
            "importance": self.importance,
            "tag": self.tag,
            "activity_kind": self.activity_kind,
            "version": self.version,
            "start_precision": self.start_precision,
            "end_precision": self.end_precision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalendarActivity":
        if not isinstance(data, dict):
            raise ValueError(f"CalendarActivity 数据必须为 dict: {data!r}")
        raw_urls = data.get("image_urls", ())
        if raw_urls is None:
            raw_urls = ()
        if not isinstance(raw_urls, (list, tuple)):
            raw_urls = ()
        return cls(
            event_id=str(data["event_id"]),
            title=str(data["title"]),
            start_at=_aware_utc(data["start_at"]),
            end_at=_aware_utc(data["end_at"]),
            category=str(data.get("category", "event")),
            source=str(data.get("source", "gamekee")),
            source_id=str(data.get("source_id", "")),
            source_url=str(data.get("source_url", "")),
            banner_url=str(data.get("banner_url", "")),
            key_visual_url=str(data.get("key_visual_url", "")),
            image_urls=tuple(str(url) for url in raw_urls if isinstance(url, str)),
            description=str(data.get("description", "")),
            importance=data.get("importance", 0),
            tag=str(data.get("tag", "")),
            activity_kind=str(data.get("activity_kind", "")),
            version=data.get("version", 1),
            start_precision=str(data.get("start_precision", data.get("time_precision", "EXACT"))),
            end_precision=str(data.get("end_precision", data.get("time_precision", "EXACT"))),
        )
