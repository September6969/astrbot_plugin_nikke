# SPDX-License-Identifier: GPL-3.0-or-later
"""官方 YouTube 频道 Atom 只读适配器（05）。

只读取官方频道公开 Atom feed 的标题与链接，不下载视频、不解析未公开接口。
上游地址由官网 ``Subscribe our channel`` 指向的频道 ID 固定：
``https://www.youtube.com/feeds/videos.xml?channel_id=UCmmgZwsqQRD6PKeo87uq1bA``。

后台调度通过 ``refresh`` 拉取并缓存；命令入口只读取热缓存，上游异常时保留旧缓存
并记录明确原因。参考：https://developers.google.com/youtube/data/guides/push_notifications
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx

from ...features.announcement.feeds import FeedItem

CHANNEL_ID = "UCmmgZwsqQRD6PKeo87uq1bA"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MAX_ENTRIES = 15
MAX_FEED_BYTES = 2 * 1024 * 1024


def parse_atom(xml_text: str) -> tuple[FeedItem, ...]:
    """解析官方频道 Atom；只保留稳定 ID、标题、链接与发布时间。"""
    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ValueError("Atom 内容为空")
    if len(xml_text.encode("utf-8")) > MAX_FEED_BYTES:
        raise ValueError("Atom 内容超出大小限制")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError("Atom XML 无法解析") from exc
    if root.tag != f"{ATOM}feed":
        raise ValueError("Atom 根节点不是 feed")
    items: list[FeedItem] = []
    for entry in root.findall(f"{ATOM}entry"):
        video_id = (entry.findtext(f"{YT}videoId") or "").strip()
        entry_id = (entry.findtext(f"{ATOM}id") or "").strip()
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        link = ""
        for node in entry.findall(f"{ATOM}link"):
            if node.get("rel", "alternate") == "alternate" and node.get("href"):
                link = str(node.get("href") or "").strip()
                break
        published_raw = (
            entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated") or ""
        ).strip()
        entity_id = video_id or entry_id.rsplit(":", 1)[-1]
        if not entity_id or not title or not link or not published_raw:
            continue
        try:
            published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.tzinfo is None:
            continue
        items.append(
            FeedItem(
                kind="video",
                entity_id=entity_id[:120],
                version=1,
                title=title[:200],
                url=link[:500],
                published_at=published.astimezone(timezone.utc).isoformat(),
            )
        )
        if len(items) >= MAX_ENTRIES:
            break
    if not items:
        raise ValueError("Atom 没有可用条目")
    return tuple(items)


class YouTubeAtomSource:
    """带缓存、节流与单飞的后台读取器；失败时保留上一次成功结果。"""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
        ttl_seconds: float = 900.0,
        monotonic=time.monotonic,
    ) -> None:
        if not 30 <= ttl_seconds <= 86400:
            raise ValueError("视频缓存周期必须在 30–86400 秒")
        self._transport = transport
        self._timeout = timeout
        self._ttl = ttl_seconds
        self._monotonic = monotonic
        self._items: tuple[FeedItem, ...] = ()
        self._last_fetch = float("-inf")
        self._last_error = ""
        self._lock = asyncio.Lock()

    @property
    def cached_items(self) -> tuple[FeedItem, ...]:
        return self._items

    @property
    def last_error(self) -> str:
        return self._last_error

    async def refresh(self, *, now: datetime | None = None) -> tuple[FeedItem, ...]:
        """按 TTL 刷新；异常时若已有缓存则降级返回缓存，否则抛出。"""
        async with self._lock:
            current = self._monotonic()
            if self._items and current - self._last_fetch < self._ttl:
                return self._items
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    transport=self._transport,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(
                        FEED_URL,
                        headers={
                            "Accept": "application/atom+xml, application/xml;q=0.9",
                            "User-Agent": "astrbot-plugin-nikke/1.0 (+local feed reader)",
                        },
                    )
                    response.raise_for_status()
                items = parse_atom(response.text)
            except Exception as exc:
                self._last_error = type(exc).__name__
                if self._items:
                    return self._items
                raise RuntimeError("官方视频来源暂不可用") from exc
            self._items = items
            self._last_fetch = current
            self._last_error = ""
            return items


__all__ = ["CHANNEL_ID", "FEED_URL", "YouTubeAtomSource", "parse_atom"]
