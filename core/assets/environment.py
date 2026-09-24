# SPDX-License-Identifier: GPL-3.0-or-later
"""各资源领域共享的只读配置与基础存储端口。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .downloader import AssetDownloader
from .image_cache import AssetImageCache
from .image_codec import AssetImageCodec


@dataclass(slots=True)
class AssetEnvironment:
    cache_dir: Path
    asset_dir: Path
    remote: bool
    sources: dict[str, Any]
    image_cache: AssetImageCache
    downloader: AssetDownloader
    nikke_db: Any
    spine_renderer: Any
    spine_budget_seconds: float
    spine_manifest: Any
    character_master: Any
    registry: Any
    currency_registry: Any
    skill_resolver: Any
    costume_resolver: Any
    visual_resolver: Any
    lineup_resolver: Any
    boss_resolver: Any
    cube_icons_map: dict[str, dict[str, Any]]
    favorite_item_icons_map: dict[str, dict[str, Any]]

    @staticmethod
    def key(value: object) -> str:
        value = str(value or "").lower()
        return value if re.fullmatch(r"[a-z0-9_-]{1,80}", value) else "missing"

    @staticmethod
    def fallback(kind: str) -> Image.Image:
        return AssetImageCodec.fallback(kind)

    def load_cached(self, relative: str) -> Image.Image | None:
        return self.image_cache.load(relative)

    def load_path(self, relative: str, remote_urls: list[str] | str = "") -> Image.Image | None:
        image = self.image_cache.load(relative)
        if image is not None:
            return image
        urls = [remote_urls] if isinstance(remote_urls, str) else list(remote_urls)
        return self.downloader.load(relative, urls)

    def load(self, kind: str, key: str, remote_url: str = "", *, allow_source: bool = True) -> Image.Image | None:
        relative = f"{kind}/{self.key(key)}.png"
        url = self.sources.get(relative, remote_url) if allow_source else remote_url
        return self.load_path(relative, [url] if url else [])
