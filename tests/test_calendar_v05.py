"""日程 v0.5 候选回退、事务与保留策略回归。"""
import io
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from PIL import Image
import pytest

from astrbot_plugin_nikke.features.calendar.models import CalendarActivity
from astrbot_plugin_nikke.features.calendar.sources import GameKeeNikkeScheduleSource, _extract_image_urls
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.features.calendar.visuals import CalendarVisualCache

NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def activity(key="one", **kw):
    return CalendarActivity(key, key, NOW - timedelta(days=1), NOW + timedelta(days=3), **kw)


def png():
    stream = io.BytesIO()
    Image.new("RGB", (30, 40), "red").save(stream, "PNG")
    return stream.getvalue()


def test_url_text_and_nested_json():
    urls = ("https://example.test/a.png", "https://example.test/b.png")
    assert _extract_image_urls(" ".join(urls)) == urls
    assert _extract_image_urls(",".join(urls)) == urls
    assert len(_extract_image_urls([f"https://example.test/{i}" for i in range(20)])) == 20
    assert _extract_image_urls(json.dumps([{"src": urls[0]}, {"nested": {"image": urls[1]}}])) == urls


def test_visual_url_rejects_local_network_targets_and_credentials():
    assert CalendarVisualCache._safe_url("https://cdn.example/image.png")
    for value in (
        "http://localhost/image.png",
        "http://127.0.0.1/image.png",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/image.png",
        "http://192.168.1.10/image.png",
        "http://[::1]/image.png",
        "https://user:pass@cdn.example/image.png",
        "file:///tmp/image.png",
    ):
        assert not CalendarVisualCache._safe_url(value), value


@pytest.mark.asyncio
async def test_visual_redirect_to_private_target_is_rejected(tmp_path):
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private.png"})

    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(respond))
    result = await cache.sync([activity(key_visual_url="https://example.test/start")], now=NOW)

    assert result["failed"] == 1
    assert seen == ["https://example.test/start"]


@pytest.mark.asyncio
async def test_visual_public_redirect_is_followed_with_manual_validation(tmp_path):
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/good.png"})
        return httpx.Response(200, content=png(), headers={"content-type": "image/png"})

    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(respond))
    result = await cache.sync([activity(key_visual_url="https://example.test/start")], now=NOW)

    assert result["downloaded"] == 1
    assert seen == ["/start", "/good.png"]


@pytest.mark.asyncio
async def test_visual_non_image_content_type_is_rejected(tmp_path):
    cache = CalendarVisualCache(
        tmp_path,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=png(), headers={"content-type": "text/html"})
        ),
    )

    result = await cache.sync([activity(key_visual_url="https://example.test/not-image")], now=NOW)

    assert result["failed"] == 1
    assert cache.resolve_path("one") is None


@pytest.mark.asyncio
async def test_real_candidate_chain_and_retry(tmp_path):
    count = 0
    def source_response(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"code": 0, "data": [{"id": 1, "title": "event",
            "begin_at": int((NOW - timedelta(days=1)).timestamp()), "end_at": int((NOW + timedelta(days=3)).timestamp()),
            "big_picture": "https://example.test/bad", "picture": "https://example.test/good"}]})
    source = GameKeeNikkeScheduleSource(transport=httpx.MockTransport(source_response))
    events = await source.fetch()
    assert count == 2
    assert events[0].visual_candidates == ("https://example.test/bad", "https://example.test/good")
    seen = []
    def image_response(request):
        seen.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/bad" else httpx.Response(200, content=png(), headers={"content-type": "image/png"})
    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(image_response))
    assert (await cache.sync(events, now=NOW))["downloaded"] == 1
    assert seen == ["/bad", "/good"]
    assert (await cache.sync(events, now=NOW))["cache_hits"] == 1
    with Image.open(cache.resolve_path(events[0].event_id)) as im:
        assert im.format == "WEBP"


@pytest.mark.asyncio
async def test_save_failure_keeps_memory_disk_version_and_timestamp(tmp_path):
    service = CalendarService(tmp_path, visual_cache=False)
    assert (await service.sync_from_source(lambda: [activity()]))[0]
    old_bytes = service.cache_path.read_bytes()
    old = service.list_activities()[0]
    timestamp = service.last_updated_at
    with patch.object(service, "_save_cache", side_effect=OSError("disk full")):
        assert not (await service.sync_from_source(lambda: [activity("new")]))[0]
    assert service.list_activities() == [old]
    assert service.last_updated_at == timestamp and service.cache_path.read_bytes() == old_bytes
    assert not (await service.sync_from_source(lambda: [object()]))[0]
    assert service.list_activities() == [old]


@pytest.mark.asyncio
async def test_retention_empty_sync_capacity_and_path_safety(tmp_path):
    cache = CalendarVisualCache(tmp_path / "cache")
    outside = tmp_path / "keep.webp"
    outside.write_bytes(png())
    for index in range(70):
        path = cache.visual_dir / f"{index}.webp"
        path.write_bytes(png())
        cache._manifest[str(index)] = {"filename": path.name, "fetched_at": NOW.isoformat()}
    cache._manifest["escape"] = {"filename": "../../keep.webp", "fetched_at": (NOW - timedelta(days=9)).isoformat()}
    await cache.sync([], now=NOW)
    assert len(cache._manifest) == 64 and outside.exists()
    await cache.sync([], now=NOW + timedelta(days=8))
    assert cache._manifest == {} and outside.exists()


@pytest.mark.asyncio
async def test_bad_image_keeps_old_cached_visual(tmp_path):
    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(lambda _: httpx.Response(200, content=png())))
    old = activity(key_visual_url="https://example.test/old")
    await cache.sync([old], now=NOW)
    path = cache.resolve_path(old.event_id)
    cache.transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"invalid", headers={"content-type": "text/html"}))
    assert (await cache.sync([activity(key_visual_url="https://example.test/new")], now=NOW))["failed"] == 1
    assert cache.resolve_path(old.event_id) == path


def test_schema_one_is_readable(tmp_path):
    row = activity().to_dict()
    for key in ("image_urls", "key_visual_url", "activity_kind"):
        row.pop(key)
    (tmp_path / "calendar_cache.json").write_text(json.dumps({"schema": 1, "activities": [row]}), encoding="utf-8")
    assert CalendarService(tmp_path, visual_cache=False).activity_count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503])
async def test_server_error_retry_is_bounded(status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status)
    source = GameKeeNikkeScheduleSource(transport=httpx.MockTransport(respond), max_retries=1)
    with pytest.raises(httpx.HTTPStatusError):
        await source.fetch()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_image_size_and_pixel_limits(tmp_path):
    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(lambda _: httpx.Response(200, content=png())))
    item = activity(key_visual_url="https://example.test/image")
    cache.MAX_BYTES = 8
    assert (await cache.sync([item], now=NOW))["failed"] == 1
    cache.MAX_BYTES = 1024 * 1024
    cache.MAX_PIXELS = 100
    assert (await cache.sync([item], now=NOW))["failed"] == 1
    assert cache.resolve_path(item.event_id) is None


@pytest.mark.asyncio
async def test_selection_concurrency_and_selected_retention(tmp_path):
    running = peak = 0
    async def respond(request):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(.01)
        running -= 1
        return httpx.Response(200, content=png())
    cache = CalendarVisualCache(tmp_path, transport=httpx.MockTransport(respond))
    items = [activity(str(i), key_visual_url=f"https://example.test/{i}") for i in range(20)]
    items.append(CalendarActivity("future", "future", NOW + timedelta(days=31), NOW + timedelta(days=32),
                                  key_visual_url="https://example.test/future"))
    stats = await cache.sync(items, now=NOW)
    assert stats["selected"] == stats["downloaded"] == 16
    assert peak == 3 and "future" not in cache._manifest
    selected = set(cache._manifest)
    cache._prune(selected, NOW + timedelta(days=10))
    assert set(cache._manifest) == selected
