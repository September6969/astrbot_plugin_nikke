# SPDX-License-Identifier: GPL-3.0-or-later
"""限流、合并并验证远端资源下载。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import httpx
from PIL import Image

from .image_cache import AssetImageCache
from .image_codec import AssetImageCodec

logger = logging.getLogger("nikke.asset_downloader")


@dataclass(slots=True)
class _InflightDownload:
    event: threading.Event = field(default_factory=threading.Event)
    image: Image.Image | None = None


class AssetDownloader:
    """负责一次资源键的有界 HTTP 候选尝试和同键 single-flight。"""

    REMOTE_DOWNLOAD_LIMIT = 4
    MAX_ATTEMPTS_PER_URL = 2
    FAILURE_COOLDOWN_SECONDS = 300

    def __init__(self, cache: AssetImageCache, *, remote_enabled: bool) -> None:
        self.cache = cache
        self.remote_enabled = remote_enabled
        # 失败冷却与在途表都由 _lock 保护，多个素材线程不会并发改写同一字典（AUD-020）。
        self.failed_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, _InflightDownload] = {}
        # 并发槽位归属单个下载器实例；类级全局信号量会让无关实例互相占满槽位。
        self._remote_download_slots = threading.BoundedSemaphore(self.REMOTE_DOWNLOAD_LIMIT)
        self._stream_override = None

    @property
    def stream(self):
        return self._stream_override or httpx.stream

    @stream.setter
    def stream(self, value) -> None:
        self._stream_override = value

    def _cooling_down(self, key: str) -> bool:
        with self._lock:
            until = self.failed_until.get(key)
            if until is None:
                return False
            if until > time.monotonic():
                return True
            # 过期条目顺手清理，避免失败表随历史键无界增长。
            del self.failed_until[key]
            return False

    def _mark_failed(self, key: str) -> None:
        with self._lock:
            self.failed_until[key] = time.monotonic() + self.FAILURE_COOLDOWN_SECONDS

    def load(self, relative: str, urls: list[str] | tuple[str, ...]) -> Image.Image | None:
        normalized = self.cache.normalize_relative(relative)
        if normalized is None:
            return None
        image = self.cache.load(normalized)
        if image is not None:
            return image
        candidates = [url for url in urls if isinstance(url, str) and url.startswith("https://")]
        if not self.remote_enabled or not candidates:
            return None

        with self._lock:
            state = self._inflight.get(normalized)
            owner = state is None
            if owner:
                state = _InflightDownload()
                self._inflight[normalized] = state
        assert state is not None
        if not owner:
            if state.event.wait(timeout=7.0) and state.image is not None:
                return state.image
            return self.cache.load(normalized)

        image = None
        slot_acquired = False
        try:
            image = self.cache.load(normalized)
            if image is not None:
                return image
            if self._cooling_down(normalized):
                return None
            slot_acquired = self._remote_download_slots.acquire(blocking=False)
            if not slot_acquired:
                logger.warning("远端素材并发已满，使用占位素材: %s", normalized)
                return None

            started = time.monotonic()
            for url in candidates:
                for _attempt in range(self.MAX_ATTEMPTS_PER_URL):
                    if time.monotonic() - started > 6:
                        break
                    try:
                        content = bytearray()
                        with self.stream("GET", url, timeout=3, follow_redirects=True) as response:
                            response.raise_for_status()
                            for chunk in response.iter_bytes():
                                content.extend(chunk)
                                if len(content) > AssetImageCodec.MAX_BYTES or time.monotonic() - started > 6:
                                    raise ValueError("素材下载超过限制")
                        image = AssetImageCodec.decode(bytes(content))
                    except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
                        image = None
                    if image is not None:
                        break
                if image is not None:
                    break
            if image is None:
                self._mark_failed(normalized)
                return None
            self.cache.save(normalized, image)
            return image
        finally:
            with self._lock:
                current = self._inflight.pop(normalized, None)
                if current is not None:
                    current.image = image
                    current.event.set()
            if slot_acquired:
                self._remote_download_slots.release()
