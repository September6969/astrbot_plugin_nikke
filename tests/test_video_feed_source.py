# SPDX-License-Identifier: GPL-3.0-or-later
"""05 官方视频 Atom：解析、缓存节流、失败降级与订阅隔离（合成 XML）。"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from astrbot_plugin_nikke.features.announcement.feeds import (
    FeedCatalog,
    FeedItem,
    FeedSubscriptions,
    VideoCatalog,
)
from astrbot_plugin_nikke.integrations.announcement.youtube_atom import (
    FEED_URL,
    YouTubeAtomSource,
    parse_atom,
)

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <title>NIKKE Official</title>
  <entry>
    <id>yt:video:abc123</id>
    <yt:videoId>abc123</yt:videoId>
    <title>Official Trailer</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <published>2026-09-20T10:00:00+00:00</published>
  </entry>
  <entry>
    <id>yt:video:def456</id>
    <yt:videoId>def456</yt:videoId>
    <title>Update Notice</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=def456"/>
    <published>2026-09-21T03:00:00+00:00</published>
  </entry>
</feed>
"""


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


class StaticCatalog:
    def __init__(self, items) -> None:
        self._items = list(items)

    def items(self, *, now):
        return tuple(self._items)


def source(handler=None, *, monotonic=None, ttl=900):
    transport = httpx.MockTransport(handler) if handler else None
    return YouTubeAtomSource(
        transport=transport,
        ttl_seconds=ttl,
        monotonic=monotonic or (lambda: 0.0),
    )


def test_parse_atom_keeps_only_stable_id_title_link_and_time() -> None:
    items = parse_atom(ATOM)
    assert [item.entity_id for item in items] == ["abc123", "def456"]
    assert [item.kind for item in items] == ["video", "video"]
    assert items[0].title == "Official Trailer"
    assert items[0].url == "https://www.youtube.com/watch?v=abc123"
    assert items[0].published_at == "2026-09-20T10:00:00+00:00"
    # FeedItem 只有固定字段，不保存缩略图、描述或视频内容。
    assert set(items[0].__dataclass_fields__) == {
        "kind", "entity_id", "version", "title", "url", "published_at"
    }

    with pytest.raises(ValueError, match="feed"):
        parse_atom("<html></html>")
    with pytest.raises(ValueError, match="没有可用条目"):
        parse_atom(
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>缺链接</title></entry></feed>'
        )


@pytest.mark.asyncio
async def test_refresh_uses_official_url_caches_and_throttles() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=ATOM)

    clock = [0.0]
    video = source(handler, monotonic=lambda: clock[0])
    items = await video.refresh()
    assert len(items) == 2
    assert requests == [FEED_URL]
    assert video.last_error == ""

    # TTL 内不重复请求。
    await video.refresh()
    assert len(requests) == 1
    clock[0] = 901
    await video.refresh()
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_upstream_failure_degrades_to_cache_or_reports_unavailable() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, text=ATOM)
        raise httpx.ConnectError("synthetic network failure", request=request)

    clock = [0.0]
    video = source(handler, monotonic=lambda: clock[0])
    await video.refresh()
    clock[0] = 901
    degraded = await video.refresh()
    assert len(degraded) == 2
    assert video.last_error == "ConnectError"

    down = source(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request)))
    with pytest.raises(RuntimeError, match="暂不可用"):
        await down.refresh()


@pytest.mark.asyncio
async def test_video_catalog_and_news_schedule_subscriptions_stay_isolated() -> None:
    news_item = FeedItem(
        kind="news", entity_id="n1", version=1, title="新闻",
        url="https://example.invalid/news", published_at="2026-09-20T00:00:00+00:00",
    )
    schedule_item = FeedItem(
        kind="schedule", entity_id="s1", version=1, title="日程",
        url="https://example.invalid/schedule", published_at="2026-09-20T00:00:00+00:00",
    )
    video_source = source(lambda request: httpx.Response(200, text=ATOM))
    catalog = FeedCatalog(
        {
            "news": StaticCatalog([news_item]),
            "schedule": StaticCatalog([schedule_item]),
            "video": VideoCatalog(video_source),
        }
    )
    store = MemoryStore()
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    subscriptions = FeedSubscriptions(store, catalog, clock=lambda: now)

    # 订阅时会同步读取缓存；先刷新一次视频，使基线包含视频条目。
    await catalog.refresh(now=now)
    subscriptions.command(FeedSubscriptions.target_key("group:1", "user-a", False), "订阅", "新闻")
    subscriptions.command(FeedSubscriptions.target_key("group:2", "user-b", False), "订阅", "视频")

    # 追加新新闻与新视频（同一官方源再刷新会得到新版本 ID 时才有新内容）。
    catalog._catalogs["news"]._items.append(
        FeedItem(
            kind="news", entity_id="n2", version=1, title="新新闻",
            url="https://example.invalid/news2", published_at="2026-09-21T00:00:00+00:00",
        )
    )
    new_video_xml = (
        ATOM.replace("abc123", "ghi789")
        .replace("def456", "jkl012")
        .replace("Official Trailer", "New Video")
        .replace("2026-09-20T10:00:00", "2026-09-22T10:00:00")
        .replace("2026-09-21T03:00:00", "2026-09-22T11:00:00")
    )
    await catalog.refresh(now=now)  # TTL 内不会重新请求，仍保留旧缓存
    video_source._items = parse_atom(new_video_xml)

    sent: list[tuple[str, str, str]] = []

    async def sender(conversation, actor, private, text):
        sent.append((conversation, actor, text))
        return True

    await subscriptions.dispatch_due(sender, now=now)
    user_a = [text for _, actor, text in sent if actor == "user-a"]
    user_b = [text for _, actor, text in sent if actor == "user-b"]
    assert any("新新闻" in text for text in user_a)
    assert any("New Video" in text for text in user_b)
    assert all("New Video" not in text for text in user_a)
    assert all("新新闻" not in text for text in user_b)
    assert all(text.startswith("【视频】") for text in user_b)

    # 再轮询不重复。
    before = list(sent)
    await subscriptions.dispatch_due(sender, now=now)
    assert sent == before
