# SPDX-License-Identifier: GPL-3.0-or-later
"""Nikke-DB 资源适配器。

负责角色/皮肤 ID 映射、canonical Spine identity、Spine 索引与版本探测、
并发锁管理以及负缓存退避机制。角色官方视觉不再通过 FB URL 提供。
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

try:
    from ...features.character.master_resolver import CharacterMasterResolver
except ImportError:
    from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver

logger = logging.getLogger("nikke.nikke_db")


@dataclass(frozen=True, slots=True)
class SpineBundleSource:
    """由上游 Git tree 真实文件记录解析出的、固定版本 Spine bundle。"""

    asset_id: str
    source_version: str
    runtime_version: str | float | None
    urls: dict[str, str]
    blob_hashes: dict[str, str]
    commit_sha: str | None = None


class NikkeDbProvider:
    L2D_CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d"
    INDEX_URL = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/js/json/l2d.json"
    GITHUB_API = "https://api.github.com/repos/Nikke-db/Nikke-db.github.io"

    INDEX_TTL = 12 * 3600  # 12 小时本地索引缓存
    L2D_TREE_TTL = 12 * 3600
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
        self._l2d_tree: dict[str, object] | None = None
        self._l2d_tree_loaded_at: float = 0

        self.costume_errors: list[str] = []
        self.costume_character_map: dict[str, str] = {}
        self.costume_render_map: dict[str, str] = {}
        self.costume_map = self._load_costume_map()
        self.master_resolver: CharacterMasterResolver | None = (
            master_resolver if master_resolver is not None else self._load_master_resolver()
        )

    def _load_master_resolver(self) -> CharacterMasterResolver | None:
        candidate_paths = [
            self.asset_dir / "data" / "character_master.json",
            self.asset_dir / "character_master.json",
            (Path(__file__).resolve().parents[2] / "assets" / "data" / "character_master.json") if (Path(__file__).resolve().parents[2] / "assets" / "data" / "character_master.json").exists() else (Path(__file__).resolve().parent / "assets" / "data" / "character_master.json"),
            (Path(__file__).resolve().parents[2] / "assets" / "character_master.json") if (Path(__file__).resolve().parents[2] / "assets" / "character_master.json").exists() else (Path(__file__).resolve().parent / "assets" / "character_master.json"),
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
        path = self.asset_dir / "data" / "costumes.json"
        if not path.is_file():
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

    @staticmethod
    def _valid_tree_sha(value: object) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None

    @classmethod
    def _validated_l2d_tree(cls, payload: object) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        commit_sha = payload.get("commit_sha")
        tree_sha = payload.get("tree_sha")
        entries = payload.get("entries")
        if (
            not cls._valid_tree_sha(commit_sha)
            or not cls._valid_tree_sha(tree_sha)
            or not isinstance(entries, list)
            or len(entries) > 20000
        ):
            return None
        validated: list[dict[str, str]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            path, sha, kind = item.get("path"), item.get("sha"), item.get("type")
            if (
                not isinstance(path, str)
                or not path.startswith("l2d/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or not isinstance(sha, str)
                or not cls._valid_tree_sha(sha)
                or not isinstance(kind, str)
                or kind not in {"blob", "tree"}
            ):
                continue
            validated.append({"path": path, "sha": sha, "type": kind})
        if not validated:
            return None
        validated.sort(key=lambda row: row["path"])
        return {"commit_sha": commit_sha, "tree_sha": tree_sha, "entries": validated}

    def get_l2d_file_tree(self, *, allow_remote: bool = True) -> dict[str, object] | None:
        """读取缓存或 GitHub 的固定 L2D 文件树；不依赖推测的文件名。"""
        now = time.time()
        if self._l2d_tree is not None and now - self._l2d_tree_loaded_at < self.L2D_TREE_TTL:
            return self._l2d_tree

        cache_path = self.cache_dir / "nikke-db" / "index" / "l2d-tree.json"
        cached: dict[str, object] | None = None
        try:
            raw_cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = self._validated_l2d_tree(raw_cache)
            fetched_at = raw_cache.get("fetched_at") if isinstance(raw_cache, dict) else None
            if cached is not None and isinstance(fetched_at, (int, float)) and now - fetched_at < self.L2D_TREE_TTL:
                self._l2d_tree = cached
                self._l2d_tree_loaded_at = now
                return cached
        except (OSError, UnicodeError, ValueError):
            pass

        if allow_remote and self.remote and not self.is_failed("index:l2d-tree"):
            try:
                headers = {
                    "User-Agent": "astrbot-plugin-nikke-spine-portrait",
                    "Accept": "application/vnd.github+json",
                }
                with httpx.Client(timeout=8.0, headers=headers) as client:
                    commit_response = client.get(f"{self.GITHUB_API}/commits/main")
                    commit_response.raise_for_status()
                    commit_payload = commit_response.json()
                    commit_sha = commit_payload.get("sha") if isinstance(commit_payload, dict) else None
                    tree_info = commit_payload.get("commit", {}).get("tree", {}) if isinstance(commit_payload, dict) else {}
                    tree_sha = tree_info.get("sha") if isinstance(tree_info, dict) else None
                    if not self._valid_tree_sha(commit_sha) or not self._valid_tree_sha(tree_sha):
                        raise ValueError("GitHub commit 元数据无效")

                    tree_response = client.get(f"{self.GITHUB_API}/git/trees/{tree_sha}?recursive=1")
                    tree_response.raise_for_status()
                    if len(tree_response.content) > 12 * 1024 * 1024:
                        raise ValueError("GitHub L2D tree 响应超过大小限制")
                    tree_payload = tree_response.json()
                    if not isinstance(tree_payload, dict) or tree_payload.get("truncated") is not False:
                        raise ValueError("GitHub L2D tree 不完整")
                    raw_entries = tree_payload.get("tree")
                    if not isinstance(raw_entries, list) or len(raw_entries) > 20000:
                        raise ValueError("GitHub L2D tree 结构无效")
                    candidate = self._validated_l2d_tree(
                        {
                            "commit_sha": commit_sha,
                            "tree_sha": tree_sha,
                            "entries": [row for row in raw_entries if isinstance(row, dict) and str(row.get("path", "")).startswith("l2d/")],
                        }
                    )
                    if candidate is None:
                        raise ValueError("GitHub L2D tree 缺少有效资源项")
                    candidate["fetched_at"] = now
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_name(f".{cache_path.name}.{threading.get_ident()}.tmp")
                    try:
                        temporary.write_text(json.dumps(candidate, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                        temporary.replace(cache_path)
                    finally:
                        temporary.unlink(missing_ok=True)
                    validated = self._validated_l2d_tree(candidate)
                    if validated is not None:
                        self._l2d_tree = validated
                        self._l2d_tree_loaded_at = now
                        return validated
            except (httpx.HTTPError, OSError, UnicodeError, ValueError, TypeError, AttributeError) as exc:
                logger.info("Nikke-DB L2D tree unavailable: %s", type(exc).__name__)
                self.mark_failed("index:l2d-tree", 300)

        if cached is not None:
            self._l2d_tree = cached
            self._l2d_tree_loaded_at = now
            return cached
        return None

    def resolve_spine_bundle_source(
        self,
        character_id: str,
        action: str = "setup",
        *,
        allow_remote: bool = True,
    ) -> SpineBundleSource | None:
        """从上游 tree 元数据配对真实 skeleton/atlas，并解析 atlas 纹理页。"""
        asset_id = self.normalize_resource_id(character_id.split("@", 1)[0] if isinstance(character_id, str) else "")
        action_id = self._normalize_id_component(action)
        if not asset_id or not asset_id.startswith("c") or not action_id:
            return None
        tree = self.get_l2d_file_tree(allow_remote=allow_remote)
        if tree is None:
            return None
        commit_sha = tree.get("commit_sha")
        entries = tree.get("entries")
        if not isinstance(commit_sha, str) or not isinstance(entries, list):
            return None

        root = f"l2d/{asset_id}"
        requested_dir = root if action_id in {"base", "setup", "static"} else f"{root}/{action_id}"
        rows = [row for row in entries if isinstance(row, dict)]
        files = [
            row for row in rows
            if row.get("type") == "blob"
            and isinstance(row.get("path"), str)
            and row["path"].startswith(requested_dir + "/")
        ]
        grouped: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
        for row in files:
            path = row["path"]
            parent, name = path.rsplit("/", 1)
            suffix = Path(name).suffix.lower()
            kind = "skeleton" if suffix in {".skel", ".json"} else "atlas" if suffix == ".atlas" else "texture" if suffix in {".png", ".webp"} else ""
            if kind:
                grouped.setdefault((parent, Path(name).stem), {})[kind] = row
        pairs = [
            (parent, stem, values["skeleton"], values["atlas"])
            for (parent, stem), values in grouped.items()
            if "skeleton" in values and "atlas" in values
        ]
        direct_pairs = [pair for pair in pairs if pair[0] == requested_dir]
        if len(direct_pairs) == 1:
            parent, _stem, skeleton, atlas = direct_pairs[0]
        elif not direct_pairs and len(pairs) == 1:
            parent, _stem, skeleton, atlas = pairs[0]
        else:
            return None

        directory_entry = next(
            (row for row in rows if row.get("type") == "tree" and row.get("path") == parent),
            None,
        )
        if isinstance(directory_entry, dict) and isinstance(directory_entry.get("sha"), str):
            source_version = directory_entry["sha"]
        else:
            scoped = sorted(
                (row.get("path"), row.get("sha"), row.get("type"))
                for row in rows
                if isinstance(row.get("path"), str)
                and (row["path"] == parent or row["path"].startswith(parent + "/"))
            )
            source_version = hashlib.sha256(json.dumps(scoped, separators=(",", ":")).encode("utf-8")).hexdigest()

        def raw_url(path: str) -> str:
            return f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/{commit_sha}/{quote(path, safe='/')}"

        urls = {"skel": raw_url(skeleton["path"]), "atlas": raw_url(atlas["path"])}
        blob_hashes = {urls["skel"]: skeleton["sha"], urls["atlas"]: atlas["sha"]}
        for row in files:
            if row.get("type") != "blob" or Path(row["path"]).suffix.lower() not in {".png", ".webp"}:
                continue
            relative = row["path"][len(parent) + 1 :]
            image_url = raw_url(row["path"])
            urls[relative] = image_url
            blob_hashes[image_url] = row["sha"]
        return SpineBundleSource(
            asset_id=asset_id,
            source_version=source_version,
            runtime_version=None,
            urls=urls,
            blob_hashes=blob_hashes,
            commit_sha=commit_sha,
        )

    def resolve_spine_bundle_urls(self, character_id: str, action: str = "setup") -> dict[str, str]:
        """兼容旧调用方，但路径只来自已发现的上游文件树。"""
        source = self.resolve_spine_bundle_source(character_id, action)
        return dict(source.urls) if source is not None else {}


NikkeDbAssetProvider = NikkeDbProvider

