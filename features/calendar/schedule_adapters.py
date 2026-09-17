# SPDX-License-Identifier: GPL-3.0-or-later
"""数据源适配器模块 (Schedule Adapters)。

将各个远程/本地源映射为标准 CanonicalEvent：
- GameKeeScheduleAdapter: GameKee 结构化活动数据
- OfficialAnnouncementScheduleAdapter: 官方公告/维护日程数据
- ManualOverrideScheduleAdapter: 手动配置覆盖
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from ...integrations.blablalink.fetch_client import FetchClient
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.adapters")


def _canonical_int(value: Any) -> int | None:
    """严格校验整数，拒绝 bool、float 与非纯数字字符串。"""
    if type(value) is int:
        return value
    if isinstance(value, str):
        s = value.strip()
        if s and s.isascii() and s.isdecimal():
            return int(s)
    return None


def _classify_category(title: str, tag: str) -> str:
    """确定性分类标签映射。"""
    text = f"{title} {tag}".casefold()
    if any(k in text for k in ("协同", "co-op", "coop", "coordinated operation")):
        return "coop"
    if any(k in text for k in ("联盟突袭", "union raid")):
        return "union_raid"
    if any(k in text for k in ("单人突袭", "solo raid")):
        return "solo_raid"
    if any(k in text for k in ("招募", "recruit", "pick up", "pickup")):
        return "recruit"
    if any(k in text for k in ("维护", "maintenance", "停服")):
        return "maintenance"
    if any(k in text for k in ("更新", "update", "版本")):
        return "update"
    return "event"


class BaseScheduleAdapter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    async def fetch(self) -> list[CanonicalEvent]:
        pass


class GameKeeScheduleAdapter(BaseScheduleAdapter):
    API_URL = "https://www.gamekee.com/v1/activity/page-list"

    def __init__(self, fetch_client: FetchClient | None = None):
        self.client = fetch_client or FetchClient()
        self.last_scan: dict[str, int] = {
            "rows": 0,
            "valid": 0,
            "malformed": 0,
            "duplicates": 0,
        }

    @property
    def source_name(self) -> str:
        return "gamekee"

    async def fetch(self) -> list[CanonicalEvent]:
        headers = {
            "game-alias": "nikke",
        }
        params = {
            "importance": 0,
            "sort": -1,
            "keyword": "",
            "limit": 999,
            "page_no": 1,
            "serverId": 19,
            "status": 0,
        }

        payload = await self.client.get_json(self.API_URL, headers=headers, params=params)

        if not isinstance(payload, dict):
            raise ValueError(f"GameKee 响应根节点必须是 JSON 对象: {type(payload)}")

        code = payload.get("code")
        if code is not None:
            canonical_code = _canonical_int(code)
            if canonical_code not in (0, 200):
                raise ValueError(f"GameKee 接口返回非成功业务码: {code!r}")

        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"GameKee 响应 data 节点必须是列表: {type(data)}")

        rows_count = len(data)
        valid_events: list[CanonicalEvent] = []
        seen_ids: set[str] = set()
        malformed_count = 0
        duplicate_count = 0

        for row in data:
            if not isinstance(row, dict):
                malformed_count += 1
                continue

            row_id = _canonical_int(row.get("id"))
            title = str(row.get("title") or "").strip()
            begin_at = _canonical_int(row.get("begin_at"))
            end_at = _canonical_int(row.get("end_at"))

            if (
                row_id is None
                or row_id <= 0
                or not title
                or begin_at is None
                or end_at is None
                or begin_at < 0
                or end_at <= begin_at
            ):
                malformed_count += 1
                continue

            event_id = f"gamekee:{row_id}"
            if event_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(event_id)

            try:
                start_dt = datetime.fromtimestamp(begin_at, tz=timezone.utc)
                end_dt = datetime.fromtimestamp(end_at, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                malformed_count += 1
                continue

            big_picture = str(row.get("big_picture") or "").strip()
            picture = str(row.get("picture") or "").strip()
            banner_url = big_picture or picture or None

            link_url = str(row.get("link_url") or "").strip()
            detail_url = link_url or "https://www.gamekee.com/nikke/"

            tag = str(row.get("tag") or "").strip()
            category = _classify_category(title, tag)

            try:
                event = CanonicalEvent(
                    id=event_id,
                    title=title,
                    event_type=category,
                    start_at=start_dt,
                    end_at=end_dt,
                    banner_url=banner_url,
                    detail_url=detail_url,
                    time_precision="EXACT",
                    sources=["gamekee"],
                    primary_source="gamekee",
                    confidence=0.85,
                    version=1,
                )
                valid_events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] GameKee 条目解析失败: %s", safe_exception_message(exc))
                malformed_count += 1

        self.last_scan = {
            "rows": rows_count,
            "valid": len(valid_events),
            "malformed": malformed_count,
            "duplicates": duplicate_count,
        }

        # Schema drift 保护
        if rows_count > 0 and len(valid_events) == 0:
            raise ValueError(
                f"GameKee 返回了 {rows_count} 条数据但全部无法解析 (malformed={malformed_count})，上游数据结构可能已漂移"
            )

        return valid_events


class OfficialAnnouncementScheduleAdapter(BaseScheduleAdapter):
    """从已获取的官方公告中提取维护和活动日程。"""

    def __init__(self, announcement_service: Any = None):
        self.announcement_service = announcement_service

    @property
    def source_name(self) -> str:
        return "official"

    async def fetch(self) -> list[CanonicalEvent]:
        if self.announcement_service is None:
            return []

        try:
            records = self.announcement_service.list_announcements(limit=50)
        except Exception as exc:
            logger.debug("[NIKKE] 官方公告读取跳过: %s", safe_exception_message(exc))
            return []

        events: list[CanonicalEvent] = []
        for rec in records:
            # 仅处理有明确起止时间的公告记录
            start_at = getattr(rec, "activity_start_at", None) or getattr(rec, "created_at", None)
            end_at = getattr(rec, "activity_end_at", None)
            title = getattr(rec, "title", "")
            if not title or not end_at:
                continue

            event_id = f"official:{getattr(rec, 'content_id', title)}"
            banner = getattr(rec, "banner_url", None)
            detail = getattr(rec, "detail_url", None)

            category = _classify_category(title, getattr(rec, "category", ""))
            # 官方公告起止若无具体时分，标记为 DATE_ONLY
            is_date_only = getattr(rec, "is_date_only", False)
            precision = "DATE_ONLY" if is_date_only else "EXACT"

            try:
                event = CanonicalEvent(
                    id=event_id,
                    title=title,
                    event_type=category,
                    start_at=start_at,
                    end_at=end_at,
                    banner_url=banner,
                    detail_url=detail,
                    time_precision=precision,
                    sources=["official"],
                    primary_source="official",
                    confidence=0.95,
                    version=1,
                )
                events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] 官方日程条目构造跳过: %s", safe_exception_message(exc))

        return events


class ManualOverrideScheduleAdapter(BaseScheduleAdapter):
    """手动配置覆盖适配器。"""

    def __init__(self, config_path: Path | str | None = None):
        self.config_path = Path(config_path) if config_path else None

    @property
    def source_name(self) -> str:
        return "manual"

    async def fetch(self) -> list[CanonicalEvent]:
        if not self.config_path or not self.config_path.is_file():
            return []

        try:
            content = self.config_path.read_text(encoding="utf-8")
            items = json.loads(content)
            if not isinstance(items, list):
                return []
            events: list[CanonicalEvent] = []
            for item in items:
                if isinstance(item, dict):
                    item["sources"] = ["manual"]
                    item["primary_source"] = "manual"
                    item["confidence"] = 1.0
                    events.append(CanonicalEvent.from_dict(item))
            return events
        except Exception as exc:
            logger.warning("[NIKKE] 手动日程配置解析失败: %s", safe_exception_message(exc))
            return []
