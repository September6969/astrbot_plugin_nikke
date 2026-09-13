# SPDX-License-Identifier: GPL-3.0-or-later
"""GameKee 结构化活动日程数据源。

遵循 Calendar v0.4 规格：
1. 仅作为辅助的结构化日程源，不覆写 AnnouncementRecord；
2. 固定请求合同与参数，绝不携带玩家凭据；
3. 严格整数类型校验（拒绝 bool/float）；
4. 支持单行 malformed 跳过并记录 last_scan 诊断指标；
5. 上游非空且全部无法解析时，抛出异常触发 schema drift 保护，促使上层保留旧快照。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .calendar_models import CalendarActivity
from .log_privacy import safe_exception_message

logger = logging.getLogger("nikke.calendar.sources")


def _canonical_int(value: Any) -> int | None:
    """规范化整数解析 helper。

    显式拒绝 bool（因 bool 是 int 的子类）、float 以及格式不符的字符串。
    """
    if type(value) is int:
        return value
    if isinstance(value, str):
        s = value.strip()
        if s and s.isascii() and s.isdecimal():
            return int(s)
    return None


def _classify_category(title: str, tag: str) -> str:
    """确定性分类标签映射，仅用于日程卡片展示。"""
    text = f"{title} {tag}".casefold()
    if any(k in text for k in ("协同", "co-op", "coop", "coordinated operation")):
        return "coop"
    if any(k in text for k in ("联盟突袭", "union raid")):
        return "union_raid"
    if any(k in text for k in ("单人突袭", "solo raid")):
        return "solo_raid"
    if any(k in text for k in ("招募", "recruit", "pick up", "pickup")):
        return "recruit"
    return "event"


class GameKeeNikkeScheduleSource:
    API_URL = "https://www.gamekee.com/v1/activity/page-list"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.transport = transport
        self.timeout = timeout
        self.last_scan: dict[str, int] = {
            "rows": 0,
            "valid": 0,
            "malformed": 0,
            "duplicates": 0,
        }

    async def fetch(self) -> list[CalendarActivity]:
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

        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout) as client:
            response = await client.get(self.API_URL, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()

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
        valid_activities: list[CalendarActivity] = []
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
            banner_url = big_picture or picture

            link_url = str(row.get("link_url") or "").strip()
            source_url = link_url or "https://www.gamekee.com/nikke/"

            description = str(row.get("description") or "").strip()
            tag = str(row.get("tag") or "").strip()
            importance = _canonical_int(row.get("importance")) or 0
            category = _classify_category(title, tag)

            try:
                activity = CalendarActivity(
                    event_id=event_id,
                    title=title,
                    start_at=start_dt,
                    end_at=end_dt,
                    category=category,
                    source="gamekee",
                    source_id=str(row_id),
                    source_url=source_url,
                    banner_url=banner_url,
                    description=description,
                    importance=importance,
                    tag=tag,
                    version=1,
                )
                valid_activities.append(activity)
            except Exception as exc:
                logger.debug("[NIKKE] GameKee 活动条目构造失败: %s", safe_exception_message(exc))
                malformed_count += 1

        self.last_scan = {
            "rows": rows_count,
            "valid": len(valid_activities),
            "malformed": malformed_count,
            "duplicates": duplicate_count,
        }

        # Schema drift 保护：如果上游返回了非空列表，但 0 条解析成功，必须抛出异常阻止覆盖旧缓存
        if rows_count > 0 and len(valid_activities) == 0:
            raise ValueError(
                f"GameKee 返回了 {rows_count} 条数据但全部无法解析 (malformed={malformed_count})，上游数据结构可能已漂移"
            )

        return valid_activities
