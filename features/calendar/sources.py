# SPDX-License-Identifier: GPL-3.0-or-later
"""GameKee 结构化活动日程数据源。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .models import CalendarActivity
from .content_quality import classify_category
from .gamekee_parser import (
    _canonical_int,
    extract_image_urls,
    normalize_http_url,
    parse_gamekee_row,
    ParseFailure,
)
from astrbot_plugin_nikke.core.privacy import safe_exception_message

logger = logging.getLogger("nikke.calendar.sources")


def _extract_image_urls(value: Any, *, limit: int | None = None) -> tuple[str, ...]:
    """旧 API 兼容包装；新的 GameKee 解析路径使用默认 12 项上限。"""
    return extract_image_urls(value, limit=limit)


def _classify_category(title: str, tag: str = "", activity_kind: str = "", description: str = "") -> str:
    """旧 API 兼容包装，实际分类只保留一份实现。"""
    return classify_category(title, tag, activity_kind, description)


class GameKeeNikkeScheduleSource:
    API_URL = "https://www.gamekee.com/v1/activity/page-list"

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        if type(max_retries) is not int or max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries 必须是 0~5 的整数")
        self.transport = transport
        self.timeout = float(timeout)
        self.max_retries = max_retries
        self.last_scan: dict[str, int] = {
            "rows": 0,
            "valid": 0,
            "malformed": 0,
            "duplicates": 0,
            "with_visual": 0,
        }

    async def _request_payload(self) -> Any:
        headers = {
            "game-alias": "nikke",
            "accept": "application/json",
            "user-agent": "astrbot-plugin-nikke/calendar",
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
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.get(self.API_URL, headers=headers, params=params)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self.max_retries:
                            await asyncio.sleep(0.35 * (2 ** attempt))
                            continue
                    response.raise_for_status()
                    return response.json()
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt >= self.max_retries:
                        raise
                    await asyncio.sleep(0.35 * (2 ** attempt))
        raise RuntimeError("GameKee 请求重试逻辑异常退出")

    async def fetch(self) -> list[CalendarActivity]:
        payload = await self._request_payload()
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
        visual_count = 0
        malformed_reasons: dict[str, int] = {}

        for row_index, row in enumerate(data):
            parsed = parse_gamekee_row(row, row_index=row_index)
            if isinstance(parsed, ParseFailure):
                malformed_count += 1
                malformed_reasons[parsed.reason] = malformed_reasons.get(parsed.reason, 0) + 1
                continue

            event_id = f"gamekee:{parsed.source_id}"
            if event_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(event_id)

            if parsed.visual_candidates:
                visual_count += 1

            try:
                activity = CalendarActivity(
                    event_id=event_id,
                    title=parsed.title,
                    start_at=parsed.start_at,
                    end_at=parsed.end_at,
                    category=parsed.category,
                    source="gamekee",
                    source_id=parsed.source_id,
                    source_url=parsed.detail_url,
                    banner_url=parsed.banner_url,
                    key_visual_url=parsed.key_visual_url,
                    image_urls=parsed.image_urls,
                    description=parsed.description,
                    importance=parsed.importance,
                    tag=parsed.tag,
                    activity_kind=parsed.activity_kind,
                    version=1,
                )
                valid_activities.append(activity)
            except Exception as exc:
                logger.debug("[NIKKE] GameKee 活动条目构造失败: %s", safe_exception_message(exc))
                malformed_count += 1
                malformed_reasons["model"] = malformed_reasons.get("model", 0) + 1

        self.last_scan = {
            "rows": rows_count,
            "valid": len(valid_activities),
            "malformed": malformed_count,
            "duplicates": duplicate_count,
            "with_visual": visual_count,
            "malformed_reasons": malformed_reasons,
        }

        if rows_count > 0 and len(valid_activities) == 0:
            raise ValueError(
                f"GameKee 返回了 {rows_count} 条数据但全部无法解析 (malformed={malformed_count})，上游数据结构可能已漂移"
            )
        return valid_activities
