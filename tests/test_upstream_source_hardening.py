# SPDX-License-Identifier: GPL-3.0-or-later
"""AUD-020 / AUD-021（预取槽位）：Nikke-DB、素材下载、FetchClient、日程视觉与公告同步加固。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.core.assets.downloader import AssetDownloader
from astrbot_plugin_nikke.core.assets.image_cache import AssetImageCache
from astrbot_plugin_nikke.core.assets.prefetcher import CharacterCardPrefetcher
from astrbot_plugin_nikke.core.assets.spine_manifest import SpineManifestStore
from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord
from astrbot_plugin_nikke.features.announcement.repository import AnnouncementRepository
from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
from astrbot_plugin_nikke.integrations.announcement.information_feeds import InformationFeedsSource
from astrbot_plugin_nikke.integrations.blablalink.fetch_client import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    FetchClient,
    FetchDecodeError,
    FetchHTTPStatusError,
)
from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider


def _png(size: tuple[int, int] = (16, 16), color: str = "teal") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# NikkeDbProvider
# ---------------------------------------------------------------------------


def _write_tree(root: Path, entries: list[dict[str, str]]) -> None:
    path = root / "nikke-db" / "index" / "l2d-tree.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"commit_sha": "f" * 40, "tree_sha": "1" * 40, "fetched_at": time.time(), "entries": entries}),
        encoding="utf-8",
    )


def test_subdirectory_bundle_only_maps_textures_inside_its_atlas_directory(tmp_path: Path) -> None:
    _write_tree(tmp_path, [
        {"path": "l2d/c191", "sha": "a" * 40, "type": "tree"},
        {"path": "l2d/c191/aim", "sha": "b" * 40, "type": "tree"},
        {"path": "l2d/c191/aim/body.skel", "sha": "c" * 40, "type": "blob"},
        {"path": "l2d/c191/aim/body.atlas", "sha": "d" * 40, "type": "blob"},
        {"path": "l2d/c191/aim/pages/body.png", "sha": "e" * 40, "type": "blob"},
        # 不在 skeleton/atlas 目录内：旧实现按 parent 长度切片得到 "r/cover.png" 这类错位键。
        {"path": "l2d/c191/cover/cover.png", "sha": "9" * 40, "type": "blob"},
        {"path": "l2d/c191/c191_page.png", "sha": "8" * 40, "type": "blob"},
    ])
    source = NikkeDbProvider(tmp_path, tmp_path).resolve_spine_bundle_source("191", allow_remote=False)
    assert source is not None
    assert set(source.urls) == {"skel", "atlas", "pages/body.png"}
    assert source.urls["pages/body.png"].endswith("/l2d/c191/aim/pages/body.png")
    assert set(source.blob_hashes.values()) == {"c" * 40, "d" * 40, "e" * 40}


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.json_calls = 0
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        self.json_calls += 1
        return self.payload


def _fake_async_client(responses: dict[str, _FakeResponse], requested: list[str]):
    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, **_kwargs):
            requested.append(url)
            return responses["tree" if "/git/trees/" in url else "commit"]

    return Client


def test_deadline_tree_fetch_parses_commit_once(tmp_path: Path) -> None:
    commit = _FakeResponse({"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}})
    tree = _FakeResponse({"truncated": False, "tree": [
        {"path": "l2d/c020", "sha": "c" * 40, "type": "tree"},
        {"path": "l2d/c020/hero.skel", "sha": "d" * 40, "type": "blob"},
    ]})
    requested: list[str] = []
    provider = NikkeDbProvider(tmp_path, tmp_path, remote=True)
    with patch(
        "astrbot_plugin_nikke.integrations.nikke_db.provider.httpx.AsyncClient",
        _fake_async_client({"commit": commit, "tree": tree}, requested),
    ):
        result = provider.get_l2d_file_tree(deadline=time.monotonic() + 5)
    assert result is not None and result["commit_sha"] == "a" * 40
    assert commit.json_calls == 1, "限时路径不得重复解析 commit 响应"
    assert requested[1].endswith("/git/trees/" + "b" * 40 + "?recursive=1")


def test_deadline_tree_fetch_rejects_invalid_commit_before_tree_request(tmp_path: Path) -> None:
    commit = _FakeResponse({"sha": "not-a-sha", "commit": {"tree": {"sha": "b" * 40}}})
    requested: list[str] = []
    provider = NikkeDbProvider(tmp_path, tmp_path, remote=True)
    with patch(
        "astrbot_plugin_nikke.integrations.nikke_db.provider.httpx.AsyncClient",
        _fake_async_client({"commit": commit, "tree": _FakeResponse({})}, requested),
    ):
        assert provider.get_l2d_file_tree(deadline=time.monotonic() + 5) is None
    assert len(requested) == 1
    assert provider.is_failed("index:l2d-tree")


# ---------------------------------------------------------------------------
# SpineManifestStore
# ---------------------------------------------------------------------------


def test_shared_skin_render_id_is_declared_and_loadable(tmp_path: Path) -> None:
    asset_dir = tmp_path / "assets"
    rendered = asset_dir / "spine-rendered"
    rendered.mkdir(parents=True)
    payload = _png((12, 18))
    (rendered / "c010_skin01.png").write_bytes(payload)
    (asset_dir / "spine_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "characters": {
            "c010@skin01": {"png_file": "c010_skin01.png", "sha256": hashlib.sha256(payload).hexdigest()},
            "c010@Bad Skin": {"png_file": "bad.png", "sha256": "0" * 64},
        },
    }), encoding="utf-8")
    store = SpineManifestStore(asset_dir, tmp_path / "cache")
    assert store.is_declared("c010@skin01")
    assert not store.is_declared("c010@bad skin")
    path, declared = store.resolve_png("c010@skin01")
    assert declared and path == (rendered / "c010_skin01.png").resolve()
    image = store.load_png("c010@skin01")
    assert image is not None and image.size == (12, 18)


# ---------------------------------------------------------------------------
# 角色卡预取槽位（AUD-021）
# ---------------------------------------------------------------------------


def test_prefetch_slots_fit_concurrent_cards() -> None:
    assert CharacterCardPrefetcher.MAX_PREFETCH_TASKS >= 2 * CharacterCardPrefetcher.TASKS_PER_CARD
    assert AssetManager.MAX_PREFETCH_TASKS == CharacterCardPrefetcher.MAX_PREFETCH_TASKS


def test_second_card_is_not_starved_while_first_card_holds_slots(tmp_path: Path) -> None:
    from astrbot_plugin_nikke.tests.test_card_builder import build_card

    manager = AssetManager(tmp_path, tmp_path)
    held = 0
    try:
        actual_submit = manager._executor.submit
        submitted: list[object] = []

        def counting_submit(func, *args, **kwargs):
            submitted.append(func)
            return actual_submit(func, *args, **kwargs)

        with patch.object(manager._executor, "submit", side_effect=counting_submit):
            manager.resolve_character_assets(build_card(), timeout=2.0)
        assert len(submitted) == CharacterCardPrefetcher.TASKS_PER_CARD
        # 模拟另一张卡的全部任务仍在途，第二张卡也必须完整提交而不是降级。
        for _ in range(CharacterCardPrefetcher.TASKS_PER_CARD):
            assert manager._prefetch_slots.acquire(timeout=1.0)
            held += 1
        submitted.clear()
        with patch.object(manager._executor, "submit", side_effect=counting_submit):
            manager.resolve_character_assets(build_card(), timeout=2.0)
        assert len(submitted) == CharacterCardPrefetcher.TASKS_PER_CARD
    finally:
        for _ in range(held):
            manager._prefetch_slots.release()
        manager.close()


# ---------------------------------------------------------------------------
# AssetDownloader
# ---------------------------------------------------------------------------


def test_download_slots_are_per_instance(tmp_path: Path) -> None:
    assert not hasattr(AssetDownloader, "_remote_download_slots"), "不得保留类级全局信号量"
    first = AssetDownloader(AssetImageCache(tmp_path / "a", tmp_path / "assets"), remote_enabled=True)
    second = AssetDownloader(AssetImageCache(tmp_path / "b", tmp_path / "assets"), remote_enabled=True)
    for _ in range(AssetDownloader.REMOTE_DOWNLOAD_LIMIT):
        assert first._remote_download_slots.acquire(blocking=False)
    response = httpx.Response(200, content=_png(), request=httpx.Request("GET", "https://example.com/x.png"))

    class Stream:
        def __enter__(self):
            return response

        def __exit__(self, *_args):
            return False

    try:
        second.stream = lambda *_args, **_kwargs: Stream()
        image = second.load("icons/x.png", ["https://example.com/x.png"])
        assert image is not None and image.size == (16, 16)
    finally:
        for _ in range(AssetDownloader.REMOTE_DOWNLOAD_LIMIT):
            first._remote_download_slots.release()


def test_failure_cooldown_is_locked_and_expired_entries_are_pruned(tmp_path: Path) -> None:
    downloader = AssetDownloader(AssetImageCache(tmp_path, tmp_path / "assets"), remote_enabled=True)
    downloader.stream = lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ConnectError("offline"))
    assert downloader.load("icons/a.png", ["https://example.com/a.png"]) is None
    assert "icons/a.png" in downloader.failed_until
    calls: list[str] = []
    downloader.stream = lambda *args, **_kwargs: calls.append(args[1]) or (_ for _ in ()).throw(httpx.ConnectError("x"))
    assert downloader.load("icons/a.png", ["https://example.com/a.png"]) is None
    assert calls == [], "冷却期内不得重复访问上游"
    downloader.failed_until["icons/a.png"] = time.monotonic() - 1
    assert downloader._cooling_down("icons/a.png") is False
    assert "icons/a.png" not in downloader.failed_until

    errors: list[BaseException] = []

    def hammer(index: int) -> None:
        try:
            for step in range(200):
                key = f"icons/{index}-{step % 7}.png"
                downloader._mark_failed(key)
                downloader._cooling_down(key)
        except BaseException as exc:  # pragma: no cover - 失败时由断言报告
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors


# ---------------------------------------------------------------------------
# FetchClient 熔断器
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_errors_do_not_trip_circuit_breaker() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": "missing"}, request=request)

    client = FetchClient(max_retries=0, circuit_failure_threshold=2, transport=httpx.MockTransport(handler))
    for _ in range(5):
        with pytest.raises(FetchHTTPStatusError):
            await client.get_json("https://api.example.com/item")
    assert calls == 5
    assert client._get_breaker("api.example.com").state == "CLOSED"
    await client.aclose()


@pytest.mark.asyncio
async def test_server_errors_still_trip_circuit_breaker() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    client = FetchClient(max_retries=0, circuit_failure_threshold=2, transport=httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(FetchHTTPStatusError):
            await client.get_json("https://api.example.com/item")
    with pytest.raises(CircuitBreakerOpenError):
        await client.get_json("https://api.example.com/item")
    assert calls == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_half_open_admits_a_single_probe() -> None:
    release = asyncio.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await release.wait()
        return httpx.Response(200, json={"ok": True}, request=request)

    client = FetchClient(
        max_retries=0, circuit_failure_threshold=1, circuit_recovery_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )
    breaker = client._get_breaker("api.example.com")
    breaker.record_failure()
    assert breaker.state == "OPEN"
    await asyncio.sleep(0.02)

    probe = asyncio.create_task(client.get_json("https://api.example.com/item"))
    await asyncio.sleep(0.01)
    assert breaker.state == "HALF_OPEN" and breaker.probe_in_flight
    for _ in range(3):
        with pytest.raises(CircuitBreakerOpenError):
            await client.get_json("https://api.example.com/item")
    assert calls == 1
    release.set()
    assert await probe == {"ok": True}
    assert breaker.state == "CLOSED" and not breaker.probe_in_flight
    assert await client.get_json("https://api.example.com/item") == {"ok": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_probe_permit_is_returned_when_probe_ends_without_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>", request=request)

    client = FetchClient(
        max_retries=0, circuit_failure_threshold=1, circuit_recovery_seconds=0.01,
        transport=httpx.MockTransport(handler),
    )
    breaker = client._get_breaker("api.example.com")
    breaker.record_failure()
    await asyncio.sleep(0.02)
    with pytest.raises(FetchDecodeError):
        await client.get_json("https://api.example.com/item")
    assert breaker.state == "HALF_OPEN" and not breaker.probe_in_flight
    # 下一请求仍可作为新探针，不会因上一个探针未归还而被永久熔断。
    with pytest.raises(FetchDecodeError):
        await client.get_json("https://api.example.com/item")
    await client.aclose()


def test_failed_probe_reopens_and_restarts_recovery_window() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=60)
    for _ in range(3):
        breaker.record_failure()
    breaker.tripped_at -= 61
    assert breaker.try_acquire() == "probe"
    assert breaker.try_acquire() is None
    breaker.record_failure()
    assert breaker.state == "OPEN" and not breaker.can_request()


# ---------------------------------------------------------------------------
# CalendarVisualCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blabla_cdn_fake_ip_is_resolved_without_gamekee_headers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.20", 443))])
    seen: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "dns.google":
            return httpx.Response(200, json={"Status": 0, "Answer": [{"type": 1, "data": "43.152.10.20"}]})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=_png())

    cache = CalendarVisualCache(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        data, width, height = await cache._download_image(
            client, "https://sg-tools-cdn.blablalink.com/ab-12/cd-34/banner.webp"
        )
    assert data and (width, height) == (16, 16)
    image_request = seen[-1]
    assert image_request.url.host == "43.152.10.20"
    assert image_request.headers["host"] == "sg-tools-cdn.blablalink.com"
    assert image_request.extensions["sni_hostname"] == "sg-tools-cdn.blablalink.com"
    assert "referer" not in image_request.headers and "game-alias" not in image_request.headers


@pytest.mark.asyncio
async def test_gamekee_headers_only_sent_to_gamekee_hops(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    seen: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "cdnimg-v2.gamekee.com":
            return httpx.Response(302, headers={"location": "https://sg-tools-cdn.blablalink.com/x/y.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=_png())

    cache = CalendarVisualCache(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await cache._download_image(client, "https://cdnimg-v2.gamekee.com/image.png")
    assert [request.url.host for request in seen] == ["cdnimg-v2.gamekee.com", "sg-tools-cdn.blablalink.com"]
    assert seen[0].headers["referer"] == "https://www.gamekee.com/nikke/"
    assert seen[0].headers["game-alias"] == "nikke"
    assert "referer" not in seen[1].headers and "game-alias" not in seen[1].headers


# ---------------------------------------------------------------------------
# 公告同步
# ---------------------------------------------------------------------------


def _record(identifier: str) -> AnnouncementRecord:
    return AnnouncementRecord(identifier, "合成公告", "正文", datetime.now(timezone.utc).isoformat(), locale="en")


class _GatedSource:
    """可控完成时机的公告来源，记录调用次数与并发度。"""

    def __init__(self, counters: dict[str, int], gate: asyncio.Event, records: list[AnnouncementRecord]) -> None:
        self.counters = counters
        self.gate = gate
        self.records = records
        self.last_scan = {"pages_scanned": 1}

    async def fetch(self) -> list[AnnouncementRecord]:
        self.counters["calls"] += 1
        self.counters["active"] += 1
        self.counters["peak"] = max(self.counters["peak"], self.counters["active"])
        try:
            await self.gate.wait()
            return list(self.records)
        finally:
            self.counters["active"] -= 1


@pytest.mark.asyncio
async def test_concurrent_identical_syncs_share_one_upstream_fetch(tmp_path: Path) -> None:
    counters = {"calls": 0, "active": 0, "peak": 0}
    gate = asyncio.Event()
    service = AnnouncementService(
        tmp_path,
        source_factory=lambda locale, *, max_pages, page_size: _GatedSource(counters, gate, [_record("informationfeeds:en:1")]),
    )
    first = asyncio.create_task(service.sync_from_source())
    await asyncio.sleep(0)
    others = [asyncio.create_task(service.sync_from_source()) for _ in range(3)]
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(first, *others)
    assert counters["calls"] == 1
    assert len({result for result in results}) == 1 and results[0][0] is True
    # 已完成的同步不会被之后的新请求复用。
    assert (await service.sync_from_source())[0] is True
    assert counters["calls"] == 2


@pytest.mark.asyncio
async def test_different_syncs_are_serialized(tmp_path: Path) -> None:
    counters = {"calls": 0, "active": 0, "peak": 0}
    gate = asyncio.Event()
    service = AnnouncementService(
        tmp_path,
        source_factory=lambda locale, *, max_pages, page_size: _GatedSource(counters, gate, [_record(f"informationfeeds:{locale}:1")]),
    )
    tasks = [
        asyncio.create_task(service.sync_from_source(locale="en")),
        asyncio.create_task(service.sync_from_source(locale="en", deep=True)),
        asyncio.create_task(service.sync_from_source(locale="ja")),
    ]
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert all(result[0] for result in results)
    assert counters == {"calls": 3, "active": 0, "peak": 1}


def _feeds_handler(failing: set[str]):
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "GetLabelList":
            data = {"primary_label_list": [{"raw_label_name": "official_news", "label_id": 309, "default_secondary_label_id": 496}]}
        elif endpoint == "GetContentByLabel":
            data = {"info_content": [{"content_id": str(index)} for index in range(4)], "is_finish": True}
        else:
            identifier = payload["content_id"]
            if identifier in failing:
                return httpx.Response(500, json={"code": 1}, request=request)
            data = {"content_id": identifier, "title": f"公告 {identifier}", "content": "<p>正文</p>", "pub_timestamp": 1_788_566_400}
        return httpx.Response(200, json={"code": 0, "data": dict(data, result=0)})

    return handle


@pytest.mark.asyncio
async def test_one_failed_detail_does_not_discard_the_batch() -> None:
    source = InformationFeedsSource(transport=httpx.MockTransport(_feeds_handler({"2"})))
    records = await source.fetch()
    assert sorted(record.content_id for record in records) == [
        "informationfeeds:en:0", "informationfeeds:en:1", "informationfeeds:en:3",
    ]
    assert source.last_scan["failed_details"] == 1
    assert source.last_scan["unique_records"] == 3


@pytest.mark.asyncio
async def test_all_failed_details_still_fail_the_scan() -> None:
    source = InformationFeedsSource(transport=httpx.MockTransport(_feeds_handler({"0", "1", "2", "3"})))
    with pytest.raises(httpx.HTTPStatusError):
        await source.fetch()


@pytest.mark.asyncio
async def test_sync_reports_partial_detail_failures(tmp_path: Path) -> None:
    service = AnnouncementService(
        tmp_path,
        source_factory=lambda locale, *, max_pages, page_size: InformationFeedsSource(
            locale, max_pages=max_pages, page_size=page_size, transport=httpx.MockTransport(_feeds_handler({"1"})),
        ),
    )
    success, message = await service.sync_from_source()
    assert success and "收到 3 条" in message and "1 条全文获取失败" in message
    assert service.last_sync_report["scan"]["failed_details"] == 1


def test_cache_save_uses_unique_temporary_file(tmp_path: Path) -> None:
    # 旧实现固定写 announcements_cache.tmp；该路径被占用（如并发写入者）时保存失败。
    (tmp_path / "announcements_cache.tmp").mkdir()
    repository = AnnouncementRepository(tmp_path)
    repository.add_or_update(_record("informationfeeds:en:9"), persist=False)
    repository.save_cache()
    saved = json.loads((tmp_path / "announcements_cache.json").read_text(encoding="utf-8"))
    assert [row["content_id"] for row in saved["records"]] == ["informationfeeds:en:9"]
    leftovers = [path.name for path in tmp_path.iterdir() if path.name.endswith(".tmp") and path.is_file()]
    assert leftovers == []


def test_concurrent_cache_saves_never_corrupt_the_file() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repository = AnnouncementRepository(root)
        repository.add_or_update(_record("informationfeeds:en:1"), persist=False)
        errors: list[str] = []
        with patch("astrbot_plugin_nikke.features.announcement.repository.logger.error", side_effect=lambda *a: errors.append(str(a))):
            threads = [threading.Thread(target=lambda: [repository.save_cache() for _ in range(20)]) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        assert errors == []
        json.loads((root / "announcements_cache.json").read_text(encoding="utf-8"))
        assert not [path for path in root.iterdir() if path.name.endswith(".tmp")]
