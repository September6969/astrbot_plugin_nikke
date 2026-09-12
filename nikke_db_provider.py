# SPDX-License-Identifier: GPL-3.0-or-later
"""Nikke-DB 资源适配器。

负责角色/皮肤 ID 映射、canonical Spine identity、Spine 索引与版本探测、
并发锁管理以及负缓存退避机制。角色官方视觉不再通过 FB URL 提供。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

try:
    from .character_master_resolver import CharacterMasterResolver
except ImportError:
    from character_master_resolver import CharacterMasterResolver

logger = logging.getLogger("nikke.nikke_db")


class NikkeDbProvider:
    L2D_CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d"
    INDEX_URL = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/js/json/l2d.json"

    INDEX_TTL = 12 * 3600  # 12 小时本地索引缓存
    NEGATIVE_CACHE_TTL = 600  # 10 分钟失败退避冷却

    NIKKE_DB_ID_OVERRIDES: dict[str, str] = {}
    COSTUME_OVERRIDES: dict[str, str] = {
        "c010_02": "c010_02",
        "c010_03": "c010_03",
    }
    # 仅登记已实际读取 skeleton 头部并记录 SHA-256 的版本；未知 canonical ID 仍返回 None。
    VERIFIED_SPINE_VERSIONS: dict[str, tuple[str, str]] = {
        "c010": ("4.0", "c7cf080108f99c048b7a2681be9cf635a750c5f7367c67fac2e5dd60aa3451a1"),
        "c010_01": ("4.0", "76c7a8b528fd02eb7a7db433b67fcb2c6bcbc2a51966fcd2f2d663ea97309156"),
        "c010_02": ("4.0", "00f3a7c1c3ac873c13a09e30d785636a2e5ff3c26835de889ef0cba9b45b792b"),
        "c010_03": ("4.1", "6ce465eced20ef1ef336debeb39497b5567e5840c66dc5427fe764701d76998f"),
    }
    _ID_PATTERN = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")

    def __init__(
        self,
        cache_dir: str | Path,
        asset_dir: str | Path,
        *,
        remote: bool = False,
        master_resolver: CharacterMasterResolver | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.remote = remote

        self._failed: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

        self._index: dict[str, dict] | None = None
        self._index_loaded_at: float = 0

        self.costume_errors: list[str] = []
        self.costume_character_map: dict[str, str] = {}
        self.costume_render_map: dict[str, str] = {}
        self.costume_map = self._load_costume_map()
        self.master_resolver: CharacterMasterResolver | None = (
            master_resolver if master_resolver is not None else self._load_master_resolver()
        )

    def _load_master_resolver(self) -> CharacterMasterResolver | None:
        candidate_paths = [
            self.asset_dir / "character_master.json",
            Path(__file__).parent / "assets" / "character_master.json",
        ]
        for p in candidate_paths:
            if p.is_file():
                try:
                    return CharacterMasterResolver(p)
                except Exception as exc:
                    logger.warning("Failed to load %s in NikkeDbProvider: %s", p, exc)
        return None

    def _is_default_costume_for_resource(
        self, resource_id: int | str, costume_id: int | str | None
    ) -> bool:
        if costume_id is None:
            return True
        if costume_id in (0, "0", "default", ""):
            return True
        if hasattr(self, "master_resolver") and self.master_resolver is not None:
            return self.master_resolver.is_default_costume(resource_id, costume_id)
        return False

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
        if not isinstance(raw, dict) or raw.get("schema_version") not in {2, 3}:
            self.costume_errors.append("costumes.json 必须使用 schema_version=2 或 3")
            return {}
        entries = raw.get("entries")
        if not isinstance(entries, list):
            self.costume_errors.append("costumes.json 缺少 entries 数组")
            return {}

        verified: dict[str, str] = {}
        for row in entries:
            if not isinstance(row, dict):
                self.costume_errors.append("非法皮肤映射条目")
                continue
            key = self._normalize_id_component(row.get("costume_id"))
            spine = row.get("spine")
            if isinstance(spine, dict):
                mode = spine.get("mode")
                value = self._normalize_id_component(spine.get("asset_id"))
                raw_skin = spine.get("skin_name")
                skin = self._normalize_id_component(raw_skin) if isinstance(raw_skin, str) else ""
                if mode not in {"independent_asset", "shared_skin"} or (mode == "independent_asset" and raw_skin is not None) or (mode == "shared_skin" and not skin):
                    self.costume_errors.append(f"非法皮肤 Spine 表示: {row!r}")
                    continue
                render_id = value if mode == "independent_asset" else f"{value}@{skin}"
            else:  # schema v2 兼容读取；禁止据此推导任何缺失 Costume。
                value = self._normalize_id_component(row.get("spine_asset_id"))
                render_id = value
            owner = self._normalize_id_component(row.get("character_resource_id"))
            source = row.get("source")
            source_hash = row.get("source_sha256")
            checked_at = row.get("verified_at")
            if (
                not key or key in {"0", "default"} or not value or not value.startswith("c")
                or not owner or not isinstance(source, str) or not source.strip()
                or not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash)
                or not isinstance(checked_at, str) or not checked_at.strip()
            ):
                self.costume_errors.append(f"非法皮肤映射: {row!r}")
                continue
            if key in verified:
                self.costume_errors.append(f"重复皮肤映射: {key}")
                continue
            verified[key] = value
            self.costume_character_map[key] = self.normalize_resource_id(owner)
            self.costume_render_map[key] = render_id
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

    def costume_cache_token(
        self, costume_id: int | str | None, resource_id: int | str | None = None
    ) -> tuple[str, str]:
        """结合当前映射把皮肤令牌分成 default/known/unknown/invalid。"""
        if resource_id is not None and self._is_default_costume_for_resource(resource_id, costume_id):
            return "default", "default"
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

        if self._is_default_costume_for_resource(resource_id, costume_id):
            return default_id

        state, token = self.costume_cache_token(costume_id, resource_id=resource_id)
        if state == "default":
            return default_id
        if state == "known":
            costume_key = token.split(":", 2)[1]
            mapped = self.COSTUME_OVERRIDES.get(costume_key) or self.costume_map.get(costume_key)
            normalized_mapping = self._normalize_id_component(mapped)
            owner = self.costume_character_map.get(costume_key)
            if owner is not None and owner != default_id:
                return "missing"
            return normalized_mapping or "missing"

        # 未知或非法皮肤禁止回退到默认角色，否则会把另一套立绘伪装成目标皮肤。
        return "missing"

    def resolve_render_id(self, resource_id: int | str, costume_id: int | str | None = None) -> str:
        """返回 manifest 专用 render ID；shared skin 不与默认 skeleton 共用键。"""
        default_id = self.resolve_character_id(resource_id)
        if default_id == "missing":
            return "missing"
        if self._is_default_costume_for_resource(resource_id, costume_id):
            return default_id
        state, token = self.costume_cache_token(costume_id, resource_id=resource_id)
        if state == "default":
            return default_id
        if state != "known":
            return "missing"
        costume_key = token.split(":", 2)[1]
        owner = self.costume_character_map.get(costume_key)
        if owner is not None and owner != default_id:
            return "missing"
        return self.costume_render_map.get(costume_key, "missing")

    def resolve_spine_asset_id(
        self,
        resource_id: int | str,
        costume_id: int | str | None = None,
        *,
        allow_remote: bool = False,
    ) -> str:
        """返回已在 L2D 索引中存在的 canonical cXXX/cXXX_YY。"""
        character_id = self.resolve_character_id(resource_id, costume_id)
        if character_id == "missing":
            return "missing"
        index = self.get_l2d_index(allow_remote=allow_remote)
        return character_id if character_id in index else "missing"

    @classmethod
    def compute_cache_key(
        cls,
        character_id: str,
        costume_id: str | int | None = None,
        source_version: str | None = None,
        runtime_version: str | None = None,
        renderer_version: str = "1.0",
        animation: str | None = None,
    ) -> str:
        _, costume_token = cls.classify_costume_id(costume_id)
        parts = [
            str(character_id or "unknown"),
            costume_token,
            str(source_version or "src"),
            str(runtime_version or "none"),
            str(renderer_version),
        ]
        if animation:
            parts.append(str(animation))
        return "_".join(parts)

    def get_l2d_index(self, *, allow_remote: bool = True) -> dict[str, dict]:
        """读取 L2D 索引；角色卡路径可明确禁止为单个角色触发索引网络请求。"""
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

        if allow_remote and self.remote and not self.is_failed("index:l2d"):
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

    def resolve_spine_version(
        self, character_id: str, *, allow_remote: bool = True
    ) -> float | str | None:
        """解析 Spine 版本；默认可刷新索引，角色卡热路径应传 ``False``。"""
        index = self.get_l2d_index(allow_remote=allow_remote)
        entry = index.get(character_id)
        verified = self.VERIFIED_SPINE_VERSIONS.get(character_id)
        if verified is not None:
            return verified[0]
        if entry and isinstance(entry, dict) and "version" in entry:
            return entry["version"]
        return None

    def resolve_spine_bundle_urls(self, character_id: str, action: str = "setup") -> dict[str, str]:
        """生成 Nikke-DB 当前的 canonical bundle 路径。"""
        char_id = self.normalize_resource_id(character_id)
        action_id = self._normalize_id_component(action)
        if char_id == "missing" or not action_id:
            return {}
        if action_id in {"base", "setup", "static"}:
            base = f"{self.L2D_CDN}/{char_id}"
            file_prefix = char_id
        else:
            base = f"{self.L2D_CDN}/{char_id}/{action_id}"
            file_prefix = f"{char_id}_{action_id}"
        png_name = f"{file_prefix}_00.png"
        if char_id == "c010_02" and action_id in {"base", "setup", "static"}:
            png_name = "c010_01.png"
        elif char_id == "c010_03" and action_id in {"base", "setup", "static"}:
            png_name = "c010_02.png"
        return {
            "skel": f"{base}/{file_prefix}_00.skel",
            "atlas": f"{base}/{file_prefix}_00.atlas",
            "png": f"{base}/{png_name}",
        }


NikkeDbAssetProvider = NikkeDbProvider

