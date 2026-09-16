# SPDX-License-Identifier: GPL-3.0-or-later
"""GameKee 结构化活动日程数据源。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .models import CalendarActivity
from ...log_privacy import safe_exception_message

logger = logging.getLogger("nikke.calendar.sources")


def _canonical_int(value: Any) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str):
        s = value.strip()
        if s and s.isascii() and s.isdecimal():
            return int(s)
    return None


def _normalize_http_url(value: Any, *, base: str = "https://www.gamekee.com") -> str:
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(base, raw)
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return raw


def _extract_image_urls(value: Any, *, limit: int | None = None) -> tuple[str, ...]:
    """兼容 GameKee image_list 的 JSON / list / URL 文本形态，递归提取安全 HTTP(S) 图片 URL。"""
    seen: set[str] = set()
    result: list[str] = []

    def add(candidate: Any) -> None:
        if limit is not None and len(result) >= limit:
            return
        url = _normalize_http_url(candidate)
        if url and url not in seen:
            seen.add(url)
            result.append(url)

    def walk(node: Any, depth: int = 0) -> None:
        if (limit is not None and len(result) >= limit) or depth > 5:
            return
        if isinstance(node, str):
            text = node.strip()
            if not text:
                return
            if text[0:1] in ("[", "{"):
                try:
                    walk(json.loads(text), depth + 1)
                    return
                except (ValueError, TypeError):
                    pass
            parts = re.split(r"[\s,;，；]+(?=(?:https?:)?//)", text)
            if len(parts) > 1:
                for part in parts:
                    walk(part, depth + 1)
                return
            if not re.search(r"\s", text) and _normalize_http_url(text):
                add(text)
                return
            for match in re.findall(r"(?:https?:)?//[^\s\"'<>]+", text):
                add(match)
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


def _classify_category(title: str, tag: str, activity_kind: str = "") -> str:
    text = f"{title} {tag} {activity_kind}".casefold()
    if any(k in text for k in ("协同", "co-op", "coop", "coordinated operation")):
        return "coop"
    if any(k in text for k in ("联盟突袭", "union raid")):
        return "union_raid"
    if any(k in text for k in ("单人突袭", "solo raid")):
        return "solo_raid"
    if any(k in text for k in ("特殊竞技场", "special arena")):
        return "special_arena"
    if any(k in text for k in ("招募", "recruit", "pick up", "pickup")):
        return "recruit"
    if any(k in text for k in (
        "full burst", "full-burst", "fullburst", "双倍", "2倍", "奖励加倍", "奖励提升", "double reward", "double drop"
    )):
        return "double_reward"
    if any(k in text for k in ("维护", "maintenance")):
        return "maintenance"
    if any(k in text for k in ("版本更新", "客户端更新", "update")):
        return "update"
    return "event"


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

            big_picture = _normalize_http_url(row.get("big_picture"))
            picture = _normalize_http_url(row.get("picture"))
            image_urls = _extract_image_urls(row.get("image_list"))
            key_visual_url = big_picture or (image_urls[0] if image_urls else "") or picture
            banner_url = big_picture or picture or (image_urls[0] if image_urls else "")
            # 保持旧 banner 合同，同时把原始 picture 保留为最后候选。
            if picture and picture not in image_urls:
                image_urls = (*image_urls, picture)
            if key_visual_url:
                visual_count += 1

            link_url = _normalize_http_url(row.get("link_url"))
            source_url = link_url or "https://www.gamekee.com/nikke/"
            description = str(row.get("description") or "").strip()
            tag = str(row.get("tag") or "").strip()
            activity_kind = str(row.get("activity_kind_name") or "").strip()
            importance = _canonical_int(row.get("importance")) or 0
            category = _classify_category(title, tag, activity_kind)

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
                    key_visual_url=key_visual_url,
                    image_urls=image_urls,
                    description=description,
                    importance=importance,
                    tag=tag,
                    activity_kind=activity_kind,
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
            "with_visual": visual_count,
        }

        if rows_count > 0 and len(valid_activities) == 0:
            raise ValueError(
                f"GameKee 返回了 {rows_count} 条数据但全部无法解析 (malformed={malformed_count})，上游数据结构可能已漂移"
            )
        return valid_activities
