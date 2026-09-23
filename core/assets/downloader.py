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
    _remote_download_slots = threading.BoundedSemaphore(REMOTE_DOWNLOAD_LIMIT)

    def __init__(self, cache: AssetImageCache, *, remote_enabled: bool) -> None:
        self.cache = cache
        self.remote_enabled = remote_enabled
        self.failed_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, _InflightDownload] = {}
        self._stream_override = None

    @property
    def stream(self):
        return self._stream_override or httpx.stream

    @stream.setter
    def stream(self, value) -> None:
        self._stream_override = value

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
            if self.failed_until.get(normalized, 0) > time.monotonic():
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
                self.failed_until[normalized] = time.monotonic() + 300
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
