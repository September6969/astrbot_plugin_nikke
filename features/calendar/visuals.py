# SPDX-License-Identifier: GPL-3.0-or-later
"""活动宣传图（KV）下载与本地缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps

from .models import CalendarActivity, _aware_utc


class CalendarVisualCache:
    """缓存当前/近期活动的远端宣传大图。

    日程数据同步不依赖图片成功：图片失败仅影响视觉背景，不覆盖结构化日程快照。
    """

    MAX_BYTES = 12 * 1024 * 1024
    MAX_PIXELS = 30_000_000
    MAX_REDIRECT_HOPS = 3

    def __init__(
        self,
        data_dir: str | Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 12.0,
        concurrency: int = 3,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        if type(concurrency) is not int or concurrency < 1 or concurrency > 8:
            raise ValueError("concurrency 必须是 1~8 的整数")
        self.data_dir = Path(data_dir)
        self.visual_dir = self.data_dir / "visuals"
        self.visual_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.data_dir / "visual_cache.json"
        self.transport = transport
        self.timeout = float(timeout)
        self.concurrency = concurrency
        self._manifest: dict[str, dict[str, Any]] = {}
        self.last_sync: dict[str, int] = {"selected": 0, "downloaded": 0, "cache_hits": 0, "failed": 0}
        self._sync_lock = asyncio.Lock()
        self._load_manifest()

    @staticmethod
    def _safe_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
            hostname = parsed.hostname
            # 访问凭据、控制字符和异常端口都不属于视觉素材 URL 合同。
            if any(ord(char) < 0x20 for char in str(value)):
                return False
            if parsed.username is not None or parsed.password is not None:
                return False
            _ = parsed.port
        except (TypeError, ValueError):
            return False
        if parsed.scheme not in ("http", "https") or not parsed.netloc or not hostname:
            return False
        host = hostname.rstrip(".").casefold()
        if host == "localhost" or host.endswith(".localhost"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return True
        # is_global 为 False 覆盖 loopback/private/link-local/multicast/
        # reserved/unspecified 及共享地址段，避免把 URL parser 当作网络边界。
        return address.is_global

    async def _validate_remote_url(self, value: str) -> bool:
        """校验 URL 及解析后的每个地址，防止下载器成为 SSRF 跳板。"""
        if not self._safe_url(value):
            return False
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None:
            return address.is_global

        # 注入传输层只用于离线 MockTransport/测试服务器；它不会建立真实
        # socket，因此交给测试传输层解析主机名，但仍保留上面的 IP/localhost
        # 硬拒绝。生产客户端 transport=None，必须继续执行 DNS 校验。
        if self.transport is not None:
            return True

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except (OSError, socket.gaierror):
            # MockTransport 是离线行为测试边界；真实客户端不得把 DNS 失败
            # 当作可访问，避免测试例域名的例外泄漏到生产路径。
            return self.transport is not None

        resolved = {str(item[4][0]) for item in records if item and item[4]}
        if not resolved:
            return False
        try:
            return all(ipaddress.ip_address(item).is_global for item in resolved)
        except ValueError:
            return False

    def _load_manifest(self) -> None:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
            if isinstance(entries, dict):
                self._manifest = {str(k): v for k, v in entries.items() if isinstance(v, dict)}
        except (OSError, ValueError, UnicodeError):
            self._manifest = {}

    def _save_manifest(self) -> None:
        payload = {
            "schema": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "entries": self._manifest,
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        with open(tmp, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(self.manifest_path)

    def resolve_path(self, event_id: str) -> Path | None:
        entry = self._manifest.get(str(event_id))
        if not isinstance(entry, dict):
            return None
        filename = entry.get("filename")
        if not isinstance(filename, str) or not filename.endswith(".webp"):
            return None
        try:
            candidate = (self.visual_dir / filename).resolve()
            if not candidate.is_relative_to(self.visual_dir.resolve()):
                return None
            if not candidate.is_file() or candidate.stat().st_size > self.MAX_BYTES:
                return None
            return candidate
        except (OSError, RuntimeError, ValueError):
            return None

    def cached_event_ids(self) -> tuple[str, ...]:
        """返回视觉清单中的事件键；调用方只能据此探测本地缓存。"""
        return tuple(self._manifest)

    @staticmethod
    def _target_filename(event_id: str, source_url: str) -> str:
        digest = hashlib.sha256(f"{event_id}|{source_url}".encode("utf-8")).hexdigest()[:32]
        return f"{digest}.webp"

    def _entry_matches(self, activity: CalendarActivity, source_url: str) -> bool:
        entry = self._manifest.get(activity.event_id)
        return bool(
            isinstance(entry, dict)
            and entry.get("source_url") == source_url
            and self.resolve_path(activity.event_id) is not None
        )

    async def _download_image(self, client: httpx.AsyncClient, url: str) -> tuple[bytes, int, int]:
        headers = {
            "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "referer": "https://www.gamekee.com/nikke/",
            "game-alias": "nikke",
            "user-agent": "astrbot-plugin-nikke/calendar-visual",
        }
        current_url = url
        redirect_hops = 0
        while True:
            if not await self._validate_remote_url(current_url):
                raise ValueError(f"活动视觉素材 URL 不允许访问: {current_url}")
            async with client.stream("GET", current_url, headers=headers) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirect_hops >= self.MAX_REDIRECT_HOPS:
                        raise ValueError("活动视觉素材重定向次数超过限制")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("活动视觉素材重定向缺少 Location")
                    current_url = urljoin(current_url, location)
                    redirect_hops += 1
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not content_type.startswith("image/"):
                    raise ValueError(f"活动视觉素材不是图片 Content-Type: {content_type}")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.MAX_BYTES:
                        raise ValueError("活动视觉素材超过大小限制")
                    chunks.append(chunk)
                break
        raw = b"".join(chunks)
        if not raw:
            raise ValueError("活动视觉素材为空")

        return await asyncio.to_thread(self._normalize_image, raw)

    def _normalize_image(self, raw: bytes) -> tuple[bytes, int, int]:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > self.MAX_PIXELS:
                raise ValueError("活动视觉素材像素尺寸异常")
            image.load()
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=88, method=4)
            data = output.getvalue()
        if len(data) > self.MAX_BYTES:
            raise ValueError("活动视觉素材转换后超过大小限制")
        return data, width, height

    async def _ensure_one(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        activity: CalendarActivity,
    ) -> str:
        candidates = [url for url in activity.visual_candidates if self._safe_url(url)]
        if not candidates:
            return "failed"

        first = candidates[0]
        if self._entry_matches(activity, first):
            return "cache_hit"

        async with semaphore:
            for url in candidates:
                if self._entry_matches(activity, url):
                    return "cache_hit"
                try:
                    data, width, height = await asyncio.wait_for(self._download_image(client, url), timeout=self.timeout)
                except (httpx.HTTPError, ValueError, OSError, asyncio.TimeoutError, Image.DecompressionBombError):
                    continue

                filename = self._target_filename(activity.event_id, url)
                target = self.visual_dir / filename
                tmp = target.with_suffix(".webp.tmp")
                try:
                    with open(tmp, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    tmp.replace(target)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue

                old = self._manifest.get(activity.event_id)
                self._manifest[activity.event_id] = {
                    "source_url": url,
                    "filename": filename,
                    "width": width,
                    "height": height,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                if isinstance(old, dict):
                    old_name = old.get("filename")
                    if isinstance(old_name, str) and old_name != filename:
                        try:
                            self._remove_file(old_name)
                        except OSError:
                            pass
                return "downloaded"
        return "failed"

    def _remove_file(self, filename: str) -> None:
        """读取和删除均限制在视觉缓存目录内。"""
        candidate = (self.visual_dir / filename).resolve()
        if candidate.is_relative_to(self.visual_dir.resolve()) and candidate.suffix == ".webp":
            candidate.unlink(missing_ok=True)

    def _prune(self, selected_ids: set[str], now: datetime) -> None:
        def used(entry):
            try:
                return _aware_utc(entry.get("last_used_at") or entry.get("fetched_at"))
            except (ValueError, TypeError):
                return datetime.min.replace(tzinfo=timezone.utc)
        candidates = sorted(
            (key for key in self._manifest if key not in selected_ids),
            key=lambda key: (used(self._manifest[key]), key),
        )
        for key in candidates:
            entry = self._manifest[key]
            if used(entry) >= now - timedelta(days=7) and len(self._manifest) <= 64:
                continue
            filename = entry.get("filename")
            if isinstance(filename, str):
                try:
                    self._remove_file(filename)
                except (OSError, ValueError, RuntimeError):
                    continue
            del self._manifest[key]

    async def sync(self, activities, *, now=None, horizon_days=30, max_items=16):
        # 串行提交索引，避免多个同步任务竞争相同临时文件。
        async with self._sync_lock:
            return await self._sync(activities, now=now, horizon_days=horizon_days, max_items=max_items)

    async def _sync(
        self,
        activities: list[CalendarActivity],
        *,
        now: datetime | None = None,
        horizon_days: int = 30,
        max_items: int = 16,
    ) -> dict[str, int]:
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        if type(horizon_days) is not int or horizon_days < 1 or horizon_days > 90:
            raise ValueError("horizon_days 必须是 1~90 的整数")
        if type(max_items) is not int or max_items < 1 or max_items > 64:
            raise ValueError("max_items 必须是 1~64 的整数")

        horizon = current + timedelta(days=horizon_days)
        selected = [
            act for act in activities
            if act.visual_candidates
            and (act.is_active(current) or (act.is_upcoming(current) and act.start_at <= horizon))
        ]
        selected.sort(key=lambda act: (
            0 if act.is_active(current) else 1,
            -act.importance,
            act.end_at if act.is_active(current) else act.start_at,
        ))
        selected = selected[:max_items]

        stats = {"selected": len(selected), "downloaded": 0, "cache_hits": 0, "failed": 0}

        semaphore = asyncio.Semaphore(self.concurrency)
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            results = await asyncio.gather(
                *(self._ensure_one(client, semaphore, act) for act in selected)
            )
        for result in results:
            if result == "downloaded":
                stats["downloaded"] += 1
            elif result == "cache_hit":
                stats["cache_hits"] += 1
            else:
                stats["failed"] += 1

        selected_ids = {act.event_id for act in selected}
        for key in selected_ids:
            if key in self._manifest:
                self._manifest[key]["last_used_at"] = current.isoformat()
        self._prune(selected_ids, current)
        self._save_manifest()
        self.last_sync = stats
        return stats
