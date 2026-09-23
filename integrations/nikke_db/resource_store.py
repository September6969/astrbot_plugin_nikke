# SPDX-License-Identifier: GPL-3.0-or-later
"""Nikke-DB L2D 的持久化本地镜像与受限远端补齐。

请求线程只读本地文件；索引刷新和 Spine bundle 下载由后台 warm 任务调用。
所有写入都先落到同一文件系统的临时文件，再原子替换，避免半个 bundle
在重启后被当成可用资源。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..spine.local_resolver import LocalSpineBundle, LocalSpineBundleResolver, LocalSpineResolveError
from ..spine.prerenderer import SpineRenderError

logger = logging.getLogger("nikke.nikke_db.store")


class NikkeDbResourceStore:
    """维护 ``vendor/nikke-db`` 的索引和 L2D bundle。"""

    DEFAULT_ROOT = Path("/AstrBot/data/vendor/nikke-db")
    INDEX_URL = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/js/json/l2d.json"
    ALLOWED_HOST = "raw.githubusercontent.com"
    ALLOWED_PREFIX = "/Nikke-db/Nikke-db.github.io/main/l2d/"
    INDEX_TTL = 12 * 3600
    MAX_INDEX_BYTES = 8 * 1024 * 1024
    MAX_SKELETON_BYTES = 16 * 1024 * 1024
    MAX_ATLAS_BYTES = 4 * 1024 * 1024
    MAX_TEXTURE_BYTES = 12 * 1024 * 1024
    MAX_TOTAL_BYTES = 32 * 1024 * 1024
    ASSET_ID = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        remote: bool = False,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.root = Path(root) if root is not None else self.DEFAULT_ROOT
        self.root = self.root.expanduser().resolve()
        self.remote = bool(remote)
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 30.0))
        self.index_path = self.root / "index" / "l2d.json"
        self.bundle_root = self.root / "l2d"
        self._index_lock = threading.RLock()
        self._bundle_locks: dict[str, threading.Lock] = {}
        self._bundle_locks_guard = threading.Lock()
        self._index: dict[str, dict] | None = None
        self._index_loaded_at = 0.0

    @classmethod
    def _asset_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise SpineRenderError("Nikke-DB render_id 类型无效")
        value = value.strip().lower()
        if not cls.ASSET_ID.fullmatch(value):
            raise SpineRenderError("Nikke-DB render_id 含有非法路径字符")
        return value

    @classmethod
    def _validate_url(cls, value: object) -> str:
        if not isinstance(value, str):
            raise SpineRenderError("Nikke-DB URL 类型无效")
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != cls.ALLOWED_HOST
            or not parsed.path.startswith(cls.ALLOWED_PREFIX)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SpineRenderError("Nikke-DB URL 不在允许的公开资源范围")
        return value

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _json_index(data: object) -> dict[str, dict]:
        if isinstance(data, list):
            return {
                str(item.get("id")): item
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        if isinstance(data, dict):
            return {
                str(key): value
                for key, value in data.items()
                if isinstance(key, str) and isinstance(value, dict)
            }
        return {}

    def _read_index_file(self) -> dict[str, dict]:
        try:
            if self.index_path.stat().st_size > self.MAX_INDEX_BYTES:
                return {}
            return self._json_index(json.loads(self.index_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValueError):
            return {}

    def get_index(self, *, allow_remote: bool = False, ttl: float | None = None) -> dict[str, dict]:
        """读取本地索引；只在明确允许且过期/缺失时刷新公开索引。"""
        now = time.monotonic()
        max_age = self.INDEX_TTL if ttl is None else max(0.0, float(ttl))
        with self._index_lock:
            if self._index is not None and now - self._index_loaded_at < max_age:
                return dict(self._index)

            local = self._read_index_file()
            fresh = False
            try:
                fresh = time.time() - self.index_path.stat().st_mtime < max_age
            except OSError:
                pass
            if local and (fresh or not allow_remote or not self.remote):
                self._index = local
                self._index_loaded_at = now
                return dict(local)

            if allow_remote and self.remote:
                try:
                    url = self.INDEX_URL
                    with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
                        response = client.get(url)
                        response.raise_for_status()
                        body = response.content
                    if len(body) > self.MAX_INDEX_BYTES:
                        raise SpineRenderError("Nikke-DB 索引超过大小预算")
                    downloaded = self._json_index(json.loads(body.decode("utf-8")))
                    if downloaded:
                        self._atomic_write(self.index_path, body)
                        local = downloaded
                except (httpx.HTTPError, OSError, UnicodeError, ValueError, SpineRenderError) as exc:
                    logger.warning("Nikke-DB L2D 索引刷新失败: %s", type(exc).__name__)

            self._index = local
            self._index_loaded_at = now
            return dict(local)

    def get_entry(self, render_id: str, *, allow_remote: bool = False) -> dict | None:
        asset_id = self._asset_id(render_id)
        return self.get_index(allow_remote=allow_remote).get(asset_id)

    def source_version(self, render_id: str, *, allow_remote: bool = False) -> str:
        """返回可进入缓存 key 的 source identity，不用名称或顺序猜测。"""
        asset_id = self._asset_id(render_id)
        entry = self.get_entry(asset_id, allow_remote=allow_remote) or {}
        for key in ("sha256", "source_sha256", "version", "updated_at"):
            value = entry.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                # source identity 会进入 SpineJob/cache key；去除时间戳等
                # 外部字段可能带来的路径字符，但不改变其身份来源。
                normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value).strip())
                return normalized[:96] or "unknown"
        try:
            bundle = self.resolve_local(asset_id)
            return hashlib.sha256(bundle.skel_path.read_bytes()).hexdigest()[:24]
        except (OSError, LocalSpineResolveError):
            return "unknown"

    def resolve_local(self, render_id: str) -> LocalSpineBundle:
        return LocalSpineBundleResolver(self.root).resolve(self._asset_id(render_id))

    def _lock_for(self, render_id: str) -> threading.Lock:
        with self._bundle_locks_guard:
            return self._bundle_locks.setdefault(render_id, threading.Lock())

    @classmethod
    def _limit_for(cls, name: str) -> int:
        return {"skel": cls.MAX_SKELETON_BYTES, "atlas": cls.MAX_ATLAS_BYTES, "png": cls.MAX_TEXTURE_BYTES}[name]

    def _download(self, url: str, target: Path, *, limit: int, total: int) -> int:
        self._validate_url(url)
        body = bytearray()
        try:
            with httpx.stream("GET", url, timeout=self.timeout_seconds, follow_redirects=False) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit or total + len(body) > self.MAX_TOTAL_BYTES:
                        raise SpineRenderError("Nikke-DB bundle 超过大小预算")
        except (httpx.HTTPError, OSError) as exc:
            raise SpineRenderError("Nikke-DB bundle 下载失败") from exc
        self._atomic_write(target, bytes(body))
        return len(body)

    def _bundle_urls(self, render_id: str, urls: dict[str, str]) -> dict[str, str]:
        asset_id = self._asset_id(render_id)
        result = {key: value for key, value in urls.items() if key in {"skel", "atlas", "png"}}
        if set(result) != {"skel", "atlas", "png"}:
            raise SpineRenderError(f"Nikke-DB bundle URL 不完整: {asset_id}")
        for value in result.values():
            self._validate_url(value)
        return result

    def ensure_bundle(
        self,
        render_id: str,
        urls: dict[str, str],
        *,
        allow_remote: bool | None = None,
    ) -> LocalSpineBundle | None:
        """本地优先解析 bundle；缺失时在后台安全补齐并再次验证版本。"""
        asset_id = self._asset_id(render_id)
        try:
            return self.resolve_local(asset_id)
        except LocalSpineResolveError:
            pass
        if allow_remote is None:
            allow_remote = self.remote
        if not allow_remote or not self.remote:
            return None

        with self._lock_for(asset_id):
            try:
                return self.resolve_local(asset_id)
            except LocalSpineResolveError:
                pass
            urls = self._bundle_urls(asset_id, urls)
            staging_root = self.root / ".staging"
            staging_id_root = staging_root / "l2d" / asset_id
            staging_id_root.mkdir(parents=True, exist_ok=True)
            total = 0
            try:
                total += self._download(urls["skel"], staging_id_root / f"{asset_id}_00.skel", limit=self.MAX_SKELETON_BYTES, total=total)
                total += self._download(urls["atlas"], staging_id_root / f"{asset_id}_00.atlas", limit=self.MAX_ATLAS_BYTES, total=total)
                pages = LocalSpineBundleResolver._atlas_pages(staging_id_root / f"{asset_id}_00.atlas")
                for page in pages:
                    page_path = Path(page)
                    target = (staging_id_root / page_path).resolve()
                    if (
                        page_path.is_absolute()
                        or page_path.drive
                        or any(part in {"", ".", ".."} for part in page_path.parts)
                        or not target.is_relative_to(staging_id_root.resolve())
                    ):
                        raise SpineRenderError("Nikke-DB atlas 纹理页路径越界")
                    page_url = urls["png"]
                    if Path(urlparse(page_url).path).name != page:
                        page_url = f"{page_url.rsplit('/', 1)[0]}/{page}"
                    total += self._download(page_url, target, limit=self.MAX_TEXTURE_BYTES, total=total)
                staged = LocalSpineBundleResolver(staging_root).resolve(asset_id)
                destination = self.bundle_root / asset_id
                destination.mkdir(parents=True, exist_ok=True)
                for source in staged.bundle_root.iterdir():
                    if source.is_file():
                        os.replace(source, destination / source.name)
                return self.resolve_local(asset_id)
            except (OSError, ValueError, LocalSpineResolveError, SpineRenderError, httpx.HTTPError) as exc:
                logger.warning("Nikke-DB bundle %s 未能进入本地镜像: %s", asset_id, type(exc).__name__)
                return None
            finally:
                for child in sorted(staging_id_root.glob("*"), reverse=True):
                    child.unlink(missing_ok=True)
                staging_id_root.rmdir() if staging_id_root.exists() and not any(staging_id_root.iterdir()) else None

    ensure_spine_bundle = ensure_bundle


__all__ = ["NikkeDbResourceStore"]
