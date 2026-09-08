# SPDX-License-Identifier: GPL-3.0-or-later
"""Nikke-DB 资源适配器。

负责角色/皮肤 ID 映射、静态全身像 CDN 地址解析、Spine 索引与版本探测、
并发锁管理以及负缓存退避机制。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger("nikke.nikke_db")


class NikkeDbProvider:
    CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"
    L2D_CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d"
    INDEX_URL = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d.json"

    INDEX_TTL = 12 * 3600  # 12 小时本地索引缓存
    NEGATIVE_CACHE_TTL = 600  # 10 分钟失败退避冷却

    NIKKE_DB_ID_OVERRIDES: dict[str, str] = {}
    COSTUME_OVERRIDES: dict[str, str] = {}
    _ID_PATTERN = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")

    def __init__(self, cache_dir: str | Path, asset_dir: str | Path, *, remote: bool = False):
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.remote = remote

        self._failed: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

        self._index: dict[str, dict] | None = None
        self._index_loaded_at: float = 0

        self.costume_errors: list[str] = []
        self.costume_map = self._load_costume_map()

    def _load_costume_map(self) -> dict[str, str]:
        """读取严格的已核验皮肤映射；坏条目不能进入运行时合同。"""
        path = self.asset_dir / "costumes.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.costume_errors.append("costumes.json 不存在")
            return {}
        except (OSError, ValueError) as exc:
            self.costume_errors.append(f"costumes.json 无法读取: {type(exc).__name__}")
            return {}
        if not isinstance(raw, dict):
            self.costume_errors.append("costumes.json 顶层必须是对象")
            return {}

        verified: dict[str, str] = {}
        for api_id, asset_id in raw.items():
            key = self._normalize_id_component(api_id)
            value = self._normalize_id_component(asset_id)
            if not key or key in {"0", "default"} or not value or not value.startswith("c"):
                self.costume_errors.append(f"非法皮肤映射: {api_id!r}")
                continue
            verified[key] = value
        return verified

    def get_character_lock(self, character_id: str) -> threading.Lock:
        with self._global_lock:
            if character_id not in self._locks:
                self._locks[character_id] = threading.Lock()
            return self._locks[character_id]

    def is_failed(self, key: str) -> bool:
        return self._failed.get(key, 0) > time.monotonic()

    def mark_failed(self, key: str, duration: float | None = None) -> None:
        self._failed[key] = time.monotonic() + (duration if duration is not None else self.NEGATIVE_CACHE_TTL)

    @classmethod
    def _normalize_id_component(cls, value: object) -> str:
        if isinstance(value, bool):
            return ""
        if type(value) is int:
            return str(value) if value >= 0 else ""
        if not isinstance(value, str):
            return ""
        candidate = value.strip().lower()
        return candidate if cls._ID_PATTERN.fullmatch(candidate) else ""

    @classmethod
    def normalize_resource_id(cls, resource_id: int | str) -> str:
        s = cls._normalize_id_component(resource_id)
        if s.startswith("c") and s[1:].isdigit():
            return s
        if s.isdigit():
            return f"c{s.zfill(3)}"
        return s if s else "missing"

    @classmethod
    def classify_costume_id(cls, costume_id: int | str | None) -> tuple[str, str]:
        """返回 ``(状态, 规范化令牌)``，严格区分默认、未知与非法皮肤。"""
        if costume_id is None:
            return "default", "default"
        if isinstance(costume_id, bool):
            return "invalid", "invalid"
        if type(costume_id) is int:
            if costume_id == 0:
                return "default", "default"
            if costume_id < 0:
                return "invalid", "invalid"
        if isinstance(costume_id, str) and not costume_id.strip():
            return "default", "default"
        normalized = cls._normalize_id_component(costume_id)
        if normalized in {"0", "default"}:
            return "default", "default"
        if not normalized:
            return "invalid", "invalid"
        return "known", normalized

    def costume_cache_token(self, costume_id: int | str | None) -> tuple[str, str]:
        """结合当前映射把皮肤令牌分成 default/known/unknown/invalid。"""
        state, token = self.classify_costume_id(costume_id)
        if state != "known":
            return state, token
        mapped = self.COSTUME_OVERRIDES.get(token) or self.costume_map.get(token)
        if mapped is None:
            return "unknown", f"unknown:{token}"
        normalized_mapping = self._normalize_id_component(mapped)
        if not normalized_mapping:
            return "invalid", f"invalid:{token}"
        return "known", f"known:{token}:{normalized_mapping}"

    def resolve_character_id(self, resource_id: int | str, costume_id: int | str | None = None) -> str:
        res_str = self._normalize_id_component(resource_id)
        if not res_str:
            return "missing"
        default_id = self.NIKKE_DB_ID_OVERRIDES.get(res_str) or self.normalize_resource_id(res_str)

        state, token = self.costume_cache_token(costume_id)
        if state == "default":
            return default_id
        if state == "known":
            costume_key = token.split(":", 2)[1]
            mapped = self.COSTUME_OVERRIDES.get(costume_key) or self.costume_map.get(costume_key)
            normalized_mapping = self._normalize_id_component(mapped)
            return normalized_mapping or "missing"

        # 未知或非法皮肤禁止回退到默认角色，否则会把另一套立绘伪装成目标皮肤。
        return "missing"

    def get_full_body_url(self, resource_id: int | str, costume_id: int | str | None = None, pose: str = "00") -> str:
        char_id = self.resolve_character_id(resource_id, costume_id)
        pose_id = self._normalize_id_component(pose)
        if not char_id or char_id == "missing" or not pose_id:
            return ""
        return f"{self.CDN}/FB/{char_id}_{pose_id}.png"

    @classmethod
    def compute_cache_key(
        cls,
        character_id: str,
        costume_id: str | int | None = None,
        source_version: str | None = None,
        runtime_version: str | None = None,
        renderer_version: str = "1.0",
    ) -> str:
        _, costume_token = cls.classify_costume_id(costume_id)
        parts = [
            str(character_id or "unknown"),
            costume_token,
            str(source_version or "src"),
            str(runtime_version or "none"),
            str(renderer_version),
        ]
        return "_".join(parts)

    def get_l2d_index(self) -> dict[str, dict]:
        now = time.monotonic()
        if self._index is not None and (now - self._index_loaded_at) < self.INDEX_TTL:
            return self._index

        index_file = self.cache_dir / "nikke-db" / "index" / "l2d.json"
        if index_file.is_file():
            try:
                mtime = index_file.stat().st_mtime
                if (time.time() - mtime) < self.INDEX_TTL:
                    data = json.loads(index_file.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        self._index = {item.get("id"): item for item in data if isinstance(item, dict) and "id" in item}
                        self._index_loaded_at = now
                        return self._index
                    if isinstance(data, dict):
                        self._index = data
                        self._index_loaded_at = now
                        return self._index
            except (OSError, ValueError):
                pass

        if self.remote and not self.is_failed("index:l2d"):
            try:
                with httpx.Client(timeout=5) as client:
                    resp = client.get(self.INDEX_URL)
                    resp.raise_for_status()
                    data = resp.json()
                    index_file.parent.mkdir(parents=True, exist_ok=True)
                    index_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    if isinstance(data, list):
                        self._index = {item.get("id"): item for item in data if isinstance(item, dict) and "id" in item}
                    elif isinstance(data, dict):
                        self._index = data
                    else:
                        self._index = {}
                    self._index_loaded_at = now
                    return self._index
            except (httpx.HTTPError, OSError, ValueError):
                self.mark_failed("index:l2d", 300)

        if index_file.is_file():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._index = {item.get("id"): item for item in data if isinstance(item, dict) and "id" in item}
                elif isinstance(data, dict):
                    self._index = data
                else:
                    self._index = {}
                self._index_loaded_at = now
                return self._index
            except (OSError, ValueError):
                pass

        self._index = {}
        self._index_loaded_at = now
        return self._index

    def resolve_spine_version(self, character_id: str) -> float | str | None:
        index = self.get_l2d_index()
        entry = index.get(character_id)
        if entry and isinstance(entry, dict) and "version" in entry:
            return entry["version"]
        return None

    def resolve_spine_bundle_urls(self, character_id: str, action: str = "aim") -> dict[str, str]:
        char_id = self.normalize_resource_id(character_id)
        action_id = self._normalize_id_component(action)
        if char_id == "missing" or not action_id:
            return {}
        base = f"{self.L2D_CDN}/{char_id}/{action_id}"
        return {
            "skel": f"{base}/{char_id}_00.skel",
            "atlas": f"{base}/{char_id}_00.atlas",
            "png": f"{base}/{char_id}_00.png",
        }


NikkeDbAssetProvider = NikkeDbProvider

