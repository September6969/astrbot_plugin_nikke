# SPDX-License-Identifier: GPL-3.0-or-later
"""GameKee 活动行的共享解析器。

所有 GameKee 入口都必须先经过本文件，再转换为 CalendarActivity 或
CanonicalEvent。解析失败带有稳定 reason，便于区分 schema drift、非法区间和
低展示相关性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from .content_quality import classify_category


GAMEKEE_BASE_URL = "https://www.gamekee.com"
MAX_IMAGE_CANDIDATES = 12
MAX_IMAGE_DEPTH = 5


@dataclass(frozen=True, slots=True)
class ParseFailure:
    """单行解析失败，供扫描统计使用。"""

    reason: str
    detail: str = ""
    row_index: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedGameKeeActivity:
    source_id: str
    title: str
    start_at: datetime
    end_at: datetime
    category: str
    description: str = ""
    tag: str = ""
    activity_kind: str = ""
    importance: int = 0
    detail_url: str = ""
    banner_url: str = ""
    key_visual_url: str = ""
    image_urls: tuple[str, ...] = ()
    visual_candidates: tuple[str, ...] = ()
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """生成适合 CanonicalEvent 持久化的轻量内容元数据。"""

        return {
            "source_id": self.source_id,
            "description": self.description,
            "tag": self.tag,
            "activity_kind": self.activity_kind,
            "importance": self.importance,
            "key_visual_url": self.key_visual_url,
            "image_urls": list(self.image_urls),
            "visual_candidates": list(self.visual_candidates),
        }


def _canonical_int(value: Any) -> int | None:
    """严格接受整数或 ASCII 十进制字符串，拒绝 bool/float。"""

    if type(value) is int:
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and text.isascii() and text.isdecimal():
            return int(text)
    return None


def normalize_http_url(value: Any, *, base: str = GAMEKEE_BASE_URL) -> str:
    """只接受无凭据的 HTTP(S) URL，支持站内相对路径。"""

    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw or any(char.isspace() for char in raw):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(base, raw)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in ("http", "https") or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    return raw


def extract_image_urls(value: Any, *, limit: int | None = MAX_IMAGE_CANDIDATES) -> tuple[str, ...]:
    """递归、去重、限深扫描 image_list。"""

    seen: set[str] = set()
    result: list[str] = []

    def add(candidate: Any) -> None:
        if limit is not None and len(result) >= limit:
            return
        normalized = normalize_http_url(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    def walk(node: Any, depth: int = 0) -> None:
        if depth > MAX_IMAGE_DEPTH or (limit is not None and len(result) >= limit):
            return
        if isinstance(node, str):
            text = node.strip()
            if not text:
                return
            if text[:1] in ("[", "{"):
                try:
                    walk(json.loads(text), depth + 1)
                    return
                except (TypeError, ValueError):
                    pass
            parts = re.split(r"[\s,;，；]+(?=(?:https?:)?//)", text)
            if len(parts) > 1:
                for part in parts:
                    walk(part, depth + 1)
                return
            if normalize_http_url(text):
                add(text)
                return
            for match in re.findall(r"(?:https?:)?//[^\s\"'<>]+", text):
                add(match.rstrip(",.;，。；》"))
            return
        if isinstance(node, dict):
            preferred = ("url", "src", "image", "image_url", "picture", "big_picture")
            for key in preferred:
                if key in node:
                    walk(node[key], depth + 1)
            for key, item in node.items():
                if key not in preferred:
                    walk(item, depth + 1)
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item, depth + 1)

    walk(value)
    return tuple(result)


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _timestamp(value: Any) -> datetime | None:
    epoch = _canonical_int(value)
    if epoch is not None:
        if epoch < 0:
            return None
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
                return None
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def parse_gamekee_row(row: Any, *, row_index: int | None = None) -> ParsedGameKeeActivity | ParseFailure:
    """把一个 GameKee row 转为统一结构，失败时不抛出业务异常。"""

    if not isinstance(row, dict):
        return ParseFailure("type", "row 必须是对象", row_index)

    raw_id = _first_value(row, "id", "activity_id", "activityId")
    row_id = _canonical_int(raw_id)
    if row_id is None or row_id <= 0:
        return ParseFailure("missing_id" if raw_id in (None, "") else "invalid_id", "id 无法解析", row_index)

    title_value = _first_value(row, "title", "name", "activity_name")
    title = str(title_value or "").strip()
    if not title:
        return ParseFailure("missing_title", "title 为空", row_index)

    start_raw = _first_value(row, "begin_at", "start_at", "start_time", "startTime", "begin_time")
    end_raw = _first_value(row, "end_at", "end_time", "endTime", "finish_at", "endAt")
    start_at = _timestamp(start_raw)
    end_at = _timestamp(end_raw)
    if start_at is None or end_at is None:
        return ParseFailure("invalid_timestamp", "开始或结束时间无法解析", row_index)
    if end_at <= start_at:
        return ParseFailure("invalid_interval", "end_at 必须严格晚于 begin_at", row_index)

    description = str(_first_value(row, "description", "desc", "content", "body") or "").strip()
    tag = str(_first_value(row, "tag", "tags") or "").strip()
    activity_kind = str(
        _first_value(row, "activity_kind_name", "activity_kind", "activity_type", "type_name") or ""
    ).strip()
    importance_raw = _first_value(row, "importance")
    importance = _canonical_int(importance_raw)
    if importance is None:
        importance = 0

    big_picture = normalize_http_url(_first_value(row, "big_picture", "bigPicture"))
    picture = normalize_http_url(_first_value(row, "picture", "cover", "banner"))
    image_list = _first_value(row, "image_list", "imageList", "image_urls", "images")
    image_list_urls = extract_image_urls(image_list)
    candidates: list[str] = []
    for candidate in (big_picture, *image_list_urls, picture):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    detail_url = normalize_http_url(_first_value(row, "link_url", "detail_url", "url"))
    if not detail_url:
        detail_url = f"{GAMEKEE_BASE_URL}/nikke/"

    return ParsedGameKeeActivity(
        source_id=str(row_id),
        title=title,
        start_at=start_at,
        end_at=end_at,
        category=classify_category(title, tag, activity_kind, description),
        description=description,
        tag=tag,
        activity_kind=activity_kind,
        importance=importance,
        detail_url=detail_url,
        banner_url=candidates[0] if candidates else "",
        key_visual_url=candidates[0] if candidates else "",
        image_urls=tuple(candidates),
        visual_candidates=tuple(candidates),
        raw_metadata=dict(row),
    )


__all__ = [
    "GAMEKEE_BASE_URL",
    "MAX_IMAGE_CANDIDATES",
    "MAX_IMAGE_DEPTH",
    "ParseFailure",
    "ParsedGameKeeActivity",
    "_canonical_int",
    "extract_image_urls",
    "normalize_http_url",
    "parse_gamekee_row",
]
