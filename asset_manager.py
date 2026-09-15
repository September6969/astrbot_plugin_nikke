# SPDX-License-Identifier: GPL-3.0-or-later
"""独立的图片资源缓存；任何缺图或网络错误均返回可渲染的占位素材。"""

from __future__ import annotations

import concurrent.futures
import io
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

from .card_models import CharacterCardAssets, CharacterCardData, SpineBundle
from .currency_registry import CurrencyRegistry
from .character_master_resolver import CharacterMasterResolver
from .idle_animation_resolver import IdleAnimationResolver
from .lineup_portrait_resolver import LineupPortraitResolver, LineupPortraitResolution
from .boss_asset_resolver import BossAssetResolver, BossAssetResolution
from .costume_asset_resolver import CostumeAssetResolver, CostumeResolution
try:
    from .character_visual_resolver import CharacterVisualAssetResolver, VisualAssetResolution
except ImportError:
    from character_visual_resolver import CharacterVisualAssetResolver, VisualAssetResolution
from .log_privacy import safe_exception_message, sanitize_log_text
from .nikke_db_provider import NikkeDbProvider
from .skill_icon_resolver import SkillIconResolver
from .spine_prerenderer import SpineBundleFetcher, SpineJob, SpinePreRenderer
from .static_registry import StaticDataRegistry

logger = logging.getLogger("nikke.asset_manager")


@dataclass(slots=True)
class AssetResult:
    """角色与皮肤视觉资源定位结果，严格区分精确匹配与降级。"""

    image: Image.Image | None = None
    exact_match: bool = True
    fallback_reason: str | None = None
    asset_key: str | None = None
    resource_id: str | None = None
    costume_id: str | None = None
    requested_kind: str | None = None
    resolved_kind: str | None = None
    source: str | None = None
    logical_key: str | None = None
    bundle: SpineBundle | None = None

    @property
    def asset(self) -> object | None:
        """统一资源实体访问：Spine 返回 bundle，图像返回 image。"""
        return self.bundle if self.bundle is not None else self.image



@dataclass
class _InflightAsset:
    """同一缓存键的共享下载状态；缓存写入失败时仍保留内存结果。"""

    event: threading.Event = field(default_factory=threading.Event)
    result: Image.Image | None = None


class AssetManager:
    MAX_BYTES = 12 * 1024 * 1024
    MAX_PIXELS = 20_000_000
    # 单张角色卡最多预取 11 项；保留少量余量，但禁止多张卡无限堆积在线程池队列。
    MAX_PREFETCH_TASKS = 16
    CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"
    # 跨实例限制不同缓存键的远端下载；缓存命中不占用名额。
    REMOTE_DOWNLOAD_LIMIT = 4
    _remote_download_slots = threading.BoundedSemaphore(REMOTE_DOWNLOAD_LIMIT)

    def __init__(
        self,
        cache_dir: str | Path,
        asset_dir: str | Path,
        *,
        remote: bool = False,
        spine_renderer: SpinePreRenderer | None = None,
        spine_budget_seconds: float = 20.0,
        spine_manifest_path: str | Path | None = None,
        spine_rendered_dir: str | Path | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.remote = remote
        mirror = self.asset_dir.parent / "data" / "nikke" / "blabla-assets"
        self.blabla_assets_dir = mirror
        self.lineup_portrait_resolver = LineupPortraitResolver(mirror, self.asset_dir)
        self.boss_asset_resolver = BossAssetResolver(mirror, self.asset_dir)
        self.character_master = CharacterMasterResolver(self.asset_dir / "character_master.json")
        self._failed: dict[str, float] = {}
        self._prefetch_slots = threading.BoundedSemaphore(self.MAX_PREFETCH_TASKS)
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, _InflightAsset] = {}
        self._spine_wait_lock = threading.Lock()
        self._spine_wait_events: dict[str, list[threading.Event]] = {}
        if isinstance(spine_budget_seconds, bool) or not isinstance(spine_budget_seconds, (int, float)) or spine_budget_seconds <= 0:
            raise ValueError("Spine 预渲染预算必须是正数")
        self.spine_renderer = spine_renderer or SpinePreRenderer(self.cache_dir)
        self.spine_budget_seconds = float(spine_budget_seconds)
        self.nikke_db = NikkeDbProvider(self.cache_dir, self.asset_dir, remote=self.remote)
        self.spine_manifest_path = Path(spine_manifest_path) if spine_manifest_path is not None else None
        self.spine_rendered_dir = Path(spine_rendered_dir) if spine_rendered_dir is not None else None
        self._spine_manifest: dict[str, Any] = {}
        self._spine_manifest_entries: dict[str, dict[str, Any]] = {}
        self._spine_manifest_declared_ids: set[str] = set()
        self._spine_manifest_source: Path | None = None
        self._spine_manifest_schema: int | None = None
        self.refresh_spine_manifest()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="nikke_asset")
        try:
            self.sources = json.loads((self.asset_dir / "sources.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.sources = {}
        if not isinstance(self.sources, dict):
            self.sources = {}
        self.registry = StaticDataRegistry(self.asset_dir)
        self.currency_registry = CurrencyRegistry()
        for error in self.registry.errors:
            logger.warning("静态 registry 校验失败：%s", error)
        self.equipment_map = self.registry.mapping("equipment")
        self.favorite_items_map = self.registry.mapping("favorite_item")
        self.cubes_map = self.registry.mapping("cube")
        self.costumes_map = self.registry.mapping("costume")

        self.skill_resolver = SkillIconResolver(self.asset_dir / "mappings" / "skill_icons.json")
        self.costume_resolver = CostumeAssetResolver(self.asset_dir / "mappings" / "costume_assets.json")
        self.visual_resolver = CharacterVisualAssetResolver(
            self.asset_dir / "mappings" / "costume_visual_assets.json",
            self.asset_dir / "mappings" / "spine_metadata.json",
        )
        self.cube_icons_map: dict[str, dict] = {}
        self.favorite_item_icons_map: dict[str, dict] = {}
        self._load_resource_mappings()

        blabla_assets_dir = self.asset_dir.parent / "data" / "nikke" / "blabla-assets"
        self.blabla_assets_dir = blabla_assets_dir
        self.lineup_resolver = LineupPortraitResolver(base_dir=blabla_assets_dir, asset_dir=self.asset_dir)
        self.boss_resolver = BossAssetResolver(base_dir=blabla_assets_dir, asset_dir=self.asset_dir)
        # 保留两套公开属性名，兼容旧调用方与资源层新调用方。
        self.lineup_portrait_resolver = self.lineup_resolver
        self.boss_asset_resolver = self.boss_resolver
        self._load_resource_mappings()

    def _load_resource_mappings(self) -> None:
        """加载魔方与珍藏品逻辑图标静态映射。"""
        cube_path = self.asset_dir / "mappings" / "cube_icons.json"
        if cube_path.is_file():
            try:
                data = json.loads(cube_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("cubes"), dict):
                    self.cube_icons_map = data["cubes"]
            except Exception as exc:
                logger.warning("Cube icons mapping 加载失败: %s", exc)

        fav_path = self.asset_dir / "mappings" / "favorite_item_icons.json"
        if fav_path.is_file():
            try:
                data = json.loads(fav_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("items"), dict):
                    self.favorite_item_icons_map = data["items"]
            except Exception as exc:
                logger.warning("Favorite item icons mapping 加载失败: %s", exc)

    def refresh_spine_manifest(self) -> None:
        """读取本地 Spine manifest；读取失败时保持空 manifest 并安全降级。"""
        candidates: list[Path] = []
        if self.spine_manifest_path is not None:
            candidates.append(self.spine_manifest_path)
        candidates.extend(
            [
                self.asset_dir / "spine_manifest.json",
                self.cache_dir / "spine-manifest.json",
                self.cache_dir / "spine_manifest.json",
            ]
        )
        self._spine_manifest = {}
        self._spine_manifest_entries = {}
        self._spine_manifest_declared_ids = set()
        self._spine_manifest_source = None
        self._spine_manifest_schema = None
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            schema = payload.get("schema_version")
            entries = payload.get("assets", payload.get("characters")) if schema == 2 else payload.get("characters") if schema == 1 else None
            if not isinstance(entries, dict):
                continue
            declared_ids = {
                str(key).strip().lower()
                for key in entries
                if re.fullmatch(r"c[0-9]+(?:_[0-9]+)?", str(key).strip().lower())
            }
            valid_entries = {
                str(key).strip().lower(): value
                for key, value in entries.items()
                if re.fullmatch(r"c[0-9]+(?:_[0-9]+)?(?:@[a-z0-9][a-z0-9_-]*)?", str(key).strip().lower()) and isinstance(value, dict)
            }
            # 两种既有 v2 容器均保留；Gemini 身份冲突检查在过滤无效键之前执行。
            if schema == 2 and "characters" in payload:
                identities = {}
                for key, entry in entries.items():
                    if not isinstance(entry, dict):
                        continue
                    identity = (str(entry.get("character_resource_id")), str(entry.get("costume_id")))
                    if identity in identities:
                        entry["_conflict"] = identities[identity]["_conflict"] = True
                    identities[identity] = entry
                    if entry.get("spine_asset_id", key) != key:
                        entry["_conflict"] = True
            self._spine_manifest = payload
            self._spine_manifest_entries = valid_entries
            # 即使条目本身不是对象，也必须视为权威声明，避免绕过 manifest 读取旧缓存。
            self._spine_manifest_declared_ids = declared_ids
            self._spine_manifest_source = candidate
            self._spine_manifest_schema = schema if isinstance(schema, int) else None
            return

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _manifest_png_path(self, char_id: str) -> tuple[Path | None, bool]:
        """解析 manifest 声明的 PNG；返回 (路径, 是否存在该 ID 条目)。"""
        if char_id not in self._spine_manifest_declared_ids:
            return None, False
        entry = self._spine_manifest_entries.get(char_id)
        if entry is None:
            return None, True
        if entry.get("_conflict"):
            logger.warning("SPINE_ASSET_CONFLICT_REJECTED: %s", char_id)
            return None, True
        if self._spine_manifest_schema == 2 and "characters" in self._spine_manifest:
            relative = entry.get("local_relpath", f"assets/spine-rendered/{char_id}.png")
            try:
                target = (self.asset_dir.parent / relative).resolve()
                if not target.is_relative_to(self.asset_dir.resolve()):
                    return None, True
                if not target.is_file():
                    logger.warning("SPINE_ASSET_FILE_MISSING: %s", char_id)
                    return None, True
                return target, True
            except (OSError, RuntimeError, ValueError, TypeError):
                return None, True
        relative = entry.get("rendered_png") if self._spine_manifest_schema == 2 else entry.get("png_file")
        if not isinstance(relative, str) or not relative.strip():
            return None, True
        base = self.spine_rendered_dir
        if base is None:
            source_parent = self._spine_manifest_source.parent if self._spine_manifest_source else self.asset_dir
            base = source_parent / "spine-rendered"
        try:
            base_resolved = base.expanduser().resolve()
            target = (base_resolved / relative).resolve()
            if not target.is_relative_to(base_resolved):
                return None, True
            if not target.is_file():
                return None, True
        except (OSError, RuntimeError, ValueError):
            return None, True
        return target, True

    def _load_spine_image(self, path: Path, entry: dict[str, Any] | None = None, *, strict_png: bool = False) -> Image.Image | None:
        try:
            if path.stat().st_size > self.MAX_BYTES:
                return None
            if entry is not None:
                expected = entry.get("sha256")
                if not isinstance(expected, str):
                    logger.warning("SPINE_MANIFEST_MISSING_HASH")
                    return None
                expected = expected.lower()
                if not re.fullmatch(r"[0-9a-f]{64}", expected) or self._sha256_file(path) != expected:
                    logger.warning("SPINE_HASH_MISMATCH")
                    return None
            if strict_png:
                with path.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        logger.warning("SPINE_ASSET_CORRUPT")
                        return None
            with Image.open(path) as image:
                if strict_png and entry is not None and any(entry.get(key) is not None and entry[key] != value for key, value in (("width", image.width), ("height", image.height))):
                    logger.warning("SPINE_ASSET_CORRUPT: dimensions")
                    return None
                if image.width * image.height > self.MAX_PIXELS:
                    return None
                image.load()
                return image.convert("RGBA")
        except (OSError, ValueError, Image.DecompressionBombError):
            return None

    @staticmethod
    def game_resource_url(path: str) -> str:
        """按官网资源路径合同生成CDN地址，与ExiaInvasion适配保持一致。"""
        path = path.lstrip("/")
        buckets = []
        for seed in (224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291)[:path.count("/")]:
            value = seed
            for char in path:
                value = (value * 33 + ord(char)) & 0xFFFFFFFF
            signed = value if value < 0x80000000 else value - 0x100000000
            modulo = signed % seed
            buckets.append(f"{chr(97 + modulo // 26 % 26)}{chr(97 + modulo % 26)}-{modulo % 99:02d}")
        filename = hashlib.md5(path.encode("utf-8")).hexdigest() + Path(path).suffix
        return "https://sg-tools-cdn.blablalink.com/" + "/".join([*buckets, filename])

    @staticmethod
    def _key(value) -> str:
        value = str(value or "").lower()
        return value if re.fullmatch(r"[a-z0-9_-]{1,80}", value) else "missing"

    @classmethod
    def _decode(cls, content: bytes, require_alpha: bool = False) -> Image.Image:
        if not content:
            raise ValueError("素材内容为空")
        if len(content) > cls.MAX_BYTES:
            raise ValueError("素材尺寸过大")
        # 严格验证常见图像魔数 (PNG, WEBP, JPEG)，杜绝 HTML 404 被当作图片解析
        is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
        is_webp = content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP"
        is_jpeg = content.startswith(b"\xff\xd8")
        if not (is_png or is_webp or is_jpeg):
            raise ValueError("非法图像魔数或非图像文件")
        with Image.open(io.BytesIO(content)) as image:
            if image.width <= 0 or image.height <= 0 or image.width * image.height > cls.MAX_PIXELS:
                raise ValueError("素材像素异常或过大")
            image.load()
            converted = image.convert("RGBA")
            if require_alpha and converted.getextrema()[-1][0] == 255:
                # 若显式要求透明背景但全图无透明
                pass
            return converted

    @classmethod
    def validate_image(cls, content_or_path: bytes | str | Path, require_alpha: bool = False) -> Image.Image:
        """下载与缓存校验器：校验字节魔数、文件大小与解码有效性。"""
        if isinstance(content_or_path, (str, Path)):
            content = Path(content_or_path).read_bytes()
        else:
            content = content_or_path
        return cls._decode(content, require_alpha=require_alpha)

    def _load_cached(self, relative: str) -> Image.Image | None:
        bases = [self.cache_dir, self.asset_dir]
        try:
            bases.append(self.asset_dir.parent)
        except Exception:
            pass
        if hasattr(self, "blabla_assets_dir") and self.blabla_assets_dir:
            bases.append(self.blabla_assets_dir)
            try:
                bases.append(self.blabla_assets_dir.parent.parent.parent)
            except Exception:
                pass

        raw_candidates = [relative]
        if relative.startswith("data/nikke/blabla-assets/"):
            raw_candidates.append(relative[len("data/nikke/blabla-assets/"):])
        if relative.startswith("assets/"):
            raw_candidates.append(relative[len("assets/"):])

        candidates = []
        for c in raw_candidates:
            candidates.append(c)
            if c.endswith(".png"):
                candidates.append(c[:-4] + ".webp")
            elif c.endswith(".webp"):
                candidates.append(c[:-5] + ".png")

        for base in bases:
            for cand in candidates:
                try:
                    path = base / cand
                    if path.is_file() and path.stat().st_size <= self.MAX_BYTES:
                        return self._decode(path.read_bytes())
                except (OSError, ValueError, Image.DecompressionBombError):
                    pass
        return None

    def _load_path(
        self,
        relative: str,
        remote_urls: list[str] | str = "",
    ) -> Image.Image | None:
        image = self._load_cached(relative)
        if image is not None:
            return image

        urls: list[str] = [remote_urls] if isinstance(remote_urls, str) else list(remote_urls)
        urls = [u for u in urls if isinstance(u, str) and u.startswith("https://")]
        if not self.remote or not urls:
            return None

        with self._inflight_lock:
            state = self._inflight.get(relative)
            owner = state is None
            if owner:
                state = _InflightAsset()
                self._inflight[relative] = state

        if not owner:
            state.event.wait(timeout=7.0)
            if state.result is not None:
                return state.result
            return self._load_cached(relative)

        slot_acquired = False
        try:
            image = self._load_cached(relative)
            if image is not None:
                return image
            if self._failed.get(relative, 0) > time.monotonic():
                return None

            slot_acquired = self._remote_download_slots.acquire(blocking=False)
            if not slot_acquired:
                logger.warning("远端素材并发已满，使用占位素材: %s", relative)
                return None

            started = time.monotonic()
            for url in urls:
                try:
                    content = bytearray()
                    with httpx.stream("GET", url, timeout=3, follow_redirects=True) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > self.MAX_BYTES or time.monotonic() - started > 6:
                                raise ValueError("素材下载超过限制")
                    image = self._decode(bytes(content))
                    break
                except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
                    continue

            if image is None:
                self._failed[relative] = time.monotonic() + 300
                return None

            try:
                destination = self.cache_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
                try:
                    image.save(temporary, format="PNG")
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return image
        finally:
            with self._inflight_lock:
                current = self._inflight.pop(relative, None)
                if current is not None:
                    if image is not None:
                        current.result = image
                    current.event.set()
            if slot_acquired:
                self._remote_download_slots.release()

    def _load(
        self,
        kind: str,
        key: str,
        remote_url: str = "",
        *,
        allow_source: bool = True,
    ) -> Image.Image | None:
        relative = f"{kind}/{self._key(key)}.png"
        url = self.sources.get(relative, remote_url) if allow_source else remote_url
        return self._load_path(relative, [url] if url else [])

    @classmethod
    def fallback(cls, kind: str) -> Image.Image:
        # 1. 尝试从 assets/fallback 目录读取预置语义兜底素材
        fallback_dir = Path(__file__).resolve().parent / "assets" / "fallback"
        kind_clean = str(kind or "").strip().lower()
        kind_file_map = {
            "s1": "skill_s1.png",
            "skill1": "skill_s1.png",
            "skill_s1": "skill_s1.png",
            "s2": "skill_s2.png",
            "skill2": "skill_s2.png",
            "skill_s2": "skill_s2.png",
            "burst": "skill_burst.png",
            "burst_skill": "skill_burst.png",
            "skill_burst": "skill_burst.png",
            "cube": "cube.png",
            "favorite": "favorite_item.png",
            "favorite_item": "favorite_item.png",
            "portrait": "portrait.png",
        }
        cand_name = kind_file_map.get(kind_clean)
        if cand_name:
            cand_path = fallback_dir / cand_name
            if cand_path.is_file():
                try:
                    with Image.open(cand_path) as fimg:
                        return fimg.convert("RGBA")
                except Exception:
                    pass

        # 2. 内存程序几何绘图兜底（保证零依赖、绝对不崩）
        if kind_clean == "portrait":
            image = Image.new("RGBA", (600, 900))
            draw = ImageDraw.Draw(image)
            color = (164, 178, 205, 75)
            draw.ellipse((213, 66, 385, 244), fill=color)
            draw.polygon([(245, 224), (351, 224), (454, 340), (403, 560),
                          (470, 850), (332, 900), (300, 616), (269, 900),
                          (133, 850), (197, 560), (146, 340)], fill=color)
            return image

        image = Image.new("RGBA", (128, 128))
        draw = ImageDraw.Draw(image)
        color = (180, 199, 220, 220)

        # 技能语义降级绘制
        if kind_clean in {"s1", "skill1", "skill_s1"}:
            draw.rounded_rectangle([(10, 10), (118, 118)], radius=16, outline=color, width=4)
            draw.text((44, 46), "S1", fill=color)
            return image
        if kind_clean in {"s2", "skill2", "skill_s2"}:
            draw.rounded_rectangle([(10, 10), (118, 118)], radius=16, outline=color, width=4)
            draw.text((44, 46), "S2", fill=color)
            return image
        if kind_clean in {"burst", "burst_skill", "skill_burst"}:
            draw.polygon([(64, 16), (112, 64), (64, 112), (16, 64)], outline=color, width=4)
            draw.text((52, 46), "B", fill=color)
            return image

        shapes = {
            "head": [(30, 75), (30, 43), (48, 23), (80, 23), (98, 43), (98, 75), (83, 87), (83, 58), (45, 58), (45, 87)],
            "torso": [(41, 24), (52, 35), (76, 35), (87, 24), (109, 48), (92, 64), (85, 103), (43, 103), (36, 64), (19, 48)],
            "arm": [(31, 28), (53, 25), (63, 67), (80, 53), (98, 65), (78, 99), (44, 101)],
            "leg": [(36, 23), (88, 23), (96, 99), (72, 99), (62, 55), (54, 99), (30, 99)],
            "cube": [(64, 20), (108, 44), (108, 87), (64, 110), (20, 87), (20, 44)],
            "favorite": [(64, 18), (77, 44), (107, 48), (85, 70), (90, 100), (64, 85), (38, 100), (43, 70), (21, 48), (51, 44)],
        }
        draw.polygon(shapes.get(kind_clean, [(64, 18), (107, 64), (64, 110), (21, 64)]), outline=color, width=5)
        if kind_clean == "cube":
            draw.line([(20, 44), (64, 67), (108, 44)], fill=color, width=4)
            draw.line([(64, 67), (64, 110)], fill=color, width=4)
        return image

    def _spine_cache_key(
        self,
        char_id: str,
        costume_id,
        runtime_version,
        animation: str | None = None,
    ) -> str:
        if animation is None:
            animation = IdleAnimationResolver.resolve_for_asset(char_id) or "idle"
        return self.nikke_db.compute_cache_key(
            char_id,
            costume_id,
            source_version=str(runtime_version),
            runtime_version=str(runtime_version),
            renderer_version=self.spine_renderer.RENDERER_VERSION,
            animation=animation,
        )

    def _get_spine_portrait(
        self,
        char_id: str,
        costume_id,
        *,
        wait_seconds: float = 0.0,
    ) -> Image.Image | None:
        """优先命中持久化静态预渲染与本地缓存；热路径绝不启动动态 Worker 渲染或网络下载。"""
        # 1. 优先读取 manifest 声明的持久化 PNG，并校验其哈希。
        manifest_path, manifest_entry_exists = self._manifest_png_path(char_id)
        if manifest_entry_exists:
            entry = self._spine_manifest_entries.get(char_id)
            if manifest_path is None:
                logger.warning("STATIC_SPINE_ASSET_INVALID: %s (costume: %s)", char_id, costume_id)
                return None
            image = self._load_spine_image(
                manifest_path,
                entry,
                strict_png=True,
            )
            if image is not None:
                return image
            logger.warning("STATIC_SPINE_ASSET_INVALID: %s (costume: %s)", char_id, costume_id)
            return None

        # manifest 已存在但没有该 ID 时，不接受未登记的 plugin 资产；保留旧版本化缓存兼容性。
        manifest_loaded = self._spine_manifest_source is not None
        candidate_paths = []
        if not manifest_loaded:
            candidate_paths.append(self.asset_dir / "spine-rendered" / f"{char_id}.png")
        if self.spine_rendered_dir is not None and not manifest_loaded:
            candidate_paths.append(self.spine_rendered_dir / f"{char_id}.png")
        candidate_paths.extend(
            [
                self.cache_dir / "spine-rendered" / f"{char_id}.png",
                self.cache_dir / "portraits" / f"{char_id}.png",
            ]
        )
        seen: set[Path] = set()
        for path in candidate_paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            image = self._load_spine_image(resolved)
            if image is not None:
                return image

        # 2. 兼容旧的版本化本地 PNG，但直接读取文件，不能调用 Worker cache API。
        runtime_version = self.nikke_db.resolve_spine_version(char_id, allow_remote=False)
        if runtime_version is not None and runtime_version != "SPINE_VERSION_UNKNOWN":
            animation = IdleAnimationResolver.resolve_for_asset(char_id)
            if animation:
                cache_key = self._spine_cache_key(char_id, costume_id, runtime_version, animation=animation)
                try:
                    cached_path = self.spine_renderer.prerender_dir / f"{SpineBundleFetcher._safe_key(cache_key)}.png"
                except (AttributeError, OSError, ValueError):
                    cached_path = None
                if cached_path is not None:
                    cached = self._load_spine_image(cached_path)
                    if cached is not None:
                        return cached

        # 3. 用户查询热路径只允许读取静态文件；不触碰 Worker 或网络。
        return None

    def get_character_portrait(self, name_code, resource_id, costume_id: int | str | None = None) -> Image.Image:
        """只从持久化静态预渲染或 canonical Spine identity 读取角色官方立绘。

        未预渲染角色记录明确警告并返回中性程序占位图，严禁在热路径发起网络拉取或启动 Worker。
        """
        char_id = self.nikke_db.resolve_render_id(
            resource_id,
            costume_id,
        ) if resource_id else "missing"
        if char_id != "missing":
            image = self._get_spine_portrait(char_id, costume_id)
            if image is not None:
                return image
            logger.warning("STATIC_SPINE_ASSET_MISSING: %s (costume: %s)", char_id, costume_id)
        return self.fallback("portrait")

    def get_lineup_portrait(
        self,
        tid: int | str | None = None,
        costume_id: int | str | None = None,
        character_id: int | str | None = None,
        avatar_id: int | str | None = None,
    ) -> Image.Image | None:
        """获取 128x128 紧凑阵容小头像（PIL Image）。严格从本地镜像与兜底中读取，绝不发网络请求。"""
        member = tid if hasattr(tid, "tid") else None
        if member is not None:
            canonical = self.character_master.resolve_battle_tid(member.tid)
            if canonical is None or str(canonical.resource_id) != str(member.resource_id):
                return None
            member_costume = getattr(member, "costume_id", None)
            if self.character_master.is_default_costume(canonical.resource_id, member_costume):
                member_costume = None
            result = self.resolve_lineup_portrait(
                character_id=canonical.id,
                costume_id=member_costume,
            )
            if result.is_fallback or str(result.resource_id) != str(canonical.resource_id):
                return None
        else:
            result = self.resolve_lineup_portrait(
                tid=tid,
                costume_id=costume_id,
                character_id=character_id,
                avatar_id=avatar_id,
            )
        try:
            with Image.open(result.local_path) as img:
                return img.convert("RGBA")
        except Exception:
            # 资源解码失败时把缺图状态交给 T2I DTO；不要把损坏文件伪装成
            # 可用头像，也不要影响同一张卡的其他成员。
            return None

    def resolve_lineup_portrait(
        self,
        tid: int | str | None = None,
        costume_id: int | str | None = None,
        character_id: int | str | None = None,
        avatar_id: int | str | None = None,
    ) -> LineupPortraitResolution:
        """向下游暴露完整 LineupPortraitResolution 契约。"""
        return self.lineup_resolver.resolve(
            tid=tid, costume_id=costume_id, character_id=character_id, avatar_id=avatar_id
        )

    def get_boss_image(
        self,
        boss_id: int | str | None = None,
        icon_id: str | None = None,
        monster_model_id: str | None = None,
        boss_name: str | None = None,
    ) -> Image.Image:
        """获取 Boss / Monster 图像（PIL Image）。严格从本地镜像与兜底中读取，绝不发网络请求。"""
        res = self.boss_resolver.resolve(
            boss_id=boss_id, icon_id=icon_id, monster_model_id=monster_model_id, boss_name=boss_name
        )
        try:
            with Image.open(res.local_path) as img:
                return img.convert("RGBA")
        except Exception:
            return self.fallback("portrait")

    def resolve_boss_asset(
        self,
        boss_id: int | str | None = None,
        icon_id: str | None = None,
        monster_model_id: str | None = None,
        boss_name: str | None = None,
    ) -> BossAssetResolution:
        """向下游暴露完整 BossAssetResolution 契约。"""
        return self.boss_resolver.resolve(
            boss_id=boss_id, icon_id=icon_id, monster_model_id=monster_model_id, boss_name=boss_name
        )

    def enqueue_experimental_spine(self, resource_id, costume_id: int | str | None = None) -> bool:
        """兼容旧调用名；正式 backend 仍受 runtime、版本和队列预算约束。"""
        char_id = self.nikke_db.resolve_spine_asset_id(resource_id, costume_id, allow_remote=False)
        if char_id == "missing":
            return False
        runtime_version = self.nikke_db.resolve_spine_version(char_id, allow_remote=False)
        urls = self.nikke_db.resolve_spine_bundle_urls(char_id, action="setup")
        if runtime_version is None or not urls or not self.spine_renderer.is_available(runtime_version):
            return False
        animation = IdleAnimationResolver.resolve_for_asset(char_id)
        if not animation:
            return False
        cache_key = self._spine_cache_key(char_id, costume_id, runtime_version, animation=animation)
        if self.spine_renderer.cached_portrait(cache_key) is not None:
            return False
        return self.spine_renderer.enqueue(
            SpineJob(
                cache_key=cache_key,
                character_id=char_id,
                runtime_version=runtime_version,
                bundle_urls=urls,
                animation=animation,
                budget_seconds=self.spine_budget_seconds,
            )
        )

    def get_equipment_icon(self, slot, equipment_id) -> Image.Image:
        resource = self.registry.resolve("equipment", equipment_id)
        if resource is None:
            image = self._load("slots", slot)
            return image if image is not None else self.fallback(slot)
        url = self.game_resource_url(f"icon/equip/{resource}.webp")
        image = self._load("equipment", str(equipment_id), url, allow_source=False)
        if image is None:
            image = self._load("slots", slot)
        return image if image is not None else self.fallback(slot)

    def _icon(self, kind, key, fallback, url="", *, allow_source=True) -> Image.Image:
        image = self._load(kind, self._key(key), url, allow_source=allow_source)
        return image if image is not None else self.fallback(fallback)

    def get_skill_icon(
        self,
        resource_id: str | int,
        slot: str,
        variant: str = "normal",
    ) -> Image.Image:
        """获取角色技能图标（PIL Image）。
        
        支持 slot: "s1", "s2", "burst"
        支持 variant: "normal", "favorite" (珍藏品技能强化变体预留)
        """
        canonical_slot = self.skill_resolver.normalize_slot(slot) or "s1"
        icon_key = self.skill_resolver.resolve(resource_id, canonical_slot, variant=variant)
        if not icon_key:
            return self.fallback(canonical_slot)

        # 逻辑物理相对路径（通用技能图标全局去重）
        rel_path = self.skill_resolver.get_logical_subpath(icon_key)
        image = self._load_cached(rel_path)
        if image is not None:
            return image

        # 检查平铺候选路径
        image = self._load_cached(f"skills/{icon_key}.png")
        if image is not None:
            return image

        # 远端按优先级拉取 webp / png
        urls = [
            self.game_resource_url(f"icon/skill/char_skill/{icon_key}.webp"),
            self.game_resource_url(f"icon/skill/char_skill/{icon_key}.png"),
        ]
        image = self._load_path(rel_path, urls)
        return image if image is not None else self.fallback(canonical_slot)

    def get_character_asset(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
        kind: str = "fullbody",
    ) -> AssetResult:
        """获取角色特定类型的视觉资产 (icon, portrait, fullbody, spine)。

        遵循严格契约：
        - 显式 exact_match 与 fallback_reason
        - 返回 requested_kind 与 resolved_kind
        - 返回统一 AssetResult，不直接暴露外部 URL
        """
        canonical_kind = str(kind or "").strip().lower()
        if canonical_kind not in ("icon", "portrait", "fullbody", "spine"):
            canonical_kind = "fullbody"

        resolution = self.visual_resolver.resolve(resource_id, costume_id=costume_id, kind=canonical_kind)
        rid_str = str(resource_id) if resource_id is not None else None
        cid_str = str(costume_id) if costume_id is not None and not str(costume_id).lower() in ("0", "default", "none", "默认", "原皮", "") else None

        # 1. 处理 Spine 请求
        if canonical_kind == "spine":
            if resolution.spine_bundle is not None:
                logger.debug(
                    "[asset][spine] resource=%s costume=%s skeleton=ok atlas=ok textures=%d",
                    rid_str,
                    cid_str or "default",
                    len(resolution.spine_bundle.textures),
                )
                return AssetResult(
                    image=None,
                    exact_match=resolution.exact_match,
                    fallback_reason=resolution.fallback_reason,
                    asset_key=resolution.asset_id,
                    resource_id=rid_str,
                    costume_id=cid_str,
                    requested_kind="spine",
                    resolved_kind=resolution.resolved_kind,
                    source="local" if resolution.exact_match else "fallback",
                    logical_key=resolution.logical_key,
                    bundle=resolution.spine_bundle,
                )
            else:
                logger.warning(
                    "[asset][spine] resource=%s costume=%s skeleton=missing atlas=missing textures=0",
                    rid_str,
                    cid_str or "default",
                )
                return AssetResult(
                    image=None,
                    exact_match=False,
                    fallback_reason=resolution.fallback_reason or "spine_missing",
                    asset_key=resolution.asset_id,
                    resource_id=rid_str,
                    costume_id=cid_str,
                    requested_kind="spine",
                    resolved_kind="spine",
                    source="fallback",
                    logical_key=None,
                    bundle=None,
                )

        # 2. 处理图像类型请求 (icon, portrait, fullbody)
        img: Image.Image | None = None
        source: str = "fallback"

        if resolution.logical_key:
            img = self._load_cached(resolution.logical_key)
            if img is not None:
                source = "cache"
            elif self.remote:
                if resolution.logical_key.startswith("FB/"):
                    fb_name = resolution.logical_key.split("/")[-1]
                    url = f"{self.CDN}/FB/{fb_name}"
                    img = self._load_path(resolution.logical_key, [url])
                    if img is not None:
                        source = "remote"
                elif "character/si/" in resolution.logical_key:
                    si_name = resolution.logical_key.split("/")[-1]
                    url = self.game_resource_url(f"character/si/{si_name}")
                    img = self._load_path(f"character/si/{si_name}", [url])
                    if img is not None:
                        source = "remote"

        # 如果主视觉文件未命中或需要降级
        if img is None:
            if canonical_kind == "fullbody":
                img = self.get_character_portrait("", resource_id, costume_id)
                if img is not None:
                    source = "fallback_portrait"
            elif canonical_kind == "portrait":
                img = self.get_character_portrait("", resource_id, costume_id)
                if img is not None:
                    source = "fallback_portrait"
            elif canonical_kind == "icon":
                img = self.get_lineup_portrait(tid=resource_id, costume_id=costume_id)
                if img is not None:
                    source = "fallback_icon"

        if img is None:
            fallback_type = "portrait" if canonical_kind in ("fullbody", "portrait") else "slots"
            img = self.fallback(fallback_type)
            source = "fallback_placeholder"

        if resolution.exact_match and source in ("cache", "local", "remote"):
            logger.debug(
                "[asset][visual] resource=%s costume=%s kind=%s cache=%s",
                rid_str,
                cid_str or "default",
                canonical_kind,
                "hit" if source == "cache" else source,
            )
        else:
            logger.warning(
                "[asset][visual] resource=%s costume=%s kind=%s fallback=%s reason=%s",
                rid_str,
                cid_str or "default",
                canonical_kind,
                resolution.resolved_kind,
                resolution.fallback_reason,
            )

        return AssetResult(
            image=img,
            exact_match=resolution.exact_match and (source in ("cache", "local", "remote")),
            fallback_reason=resolution.fallback_reason,
            asset_key=resolution.asset_id,
            resource_id=rid_str,
            costume_id=cid_str,
            requested_kind=canonical_kind,
            resolved_kind=resolution.resolved_kind,
            source=source,
            logical_key=resolution.logical_key,
            bundle=resolution.spine_bundle,
        )

    def get_character_icon(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> Image.Image:
        """按规范获取角色或皮肤的头像 (icon) PIL 图像。"""
        res = self.get_character_asset(resource_id, costume_id=costume_id, kind="icon")
        return res.image if res.image is not None else self.fallback("slots")

    def get_character_fullbody(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> Image.Image:
        """按规范获取角色或皮肤的站姿大立绘 (fullbody / FB) PIL 图像。"""
        res = self.get_character_asset(resource_id, costume_id=costume_id, kind="fullbody")
        return res.image if res.image is not None else self.fallback("portrait")

    def get_character_spine(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> SpineBundle | None:
        """按规范获取角色或皮肤的 SpineBundle 组合资源契约。"""
        res = self.get_character_asset(resource_id, costume_id=costume_id, kind="spine")
        return res.bundle

    def get_character_placement(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> dict[str, Any] | None:
        """获取角色或皮肤的标准 Placement Metadata (CharacterPlacementMeta)。"""
        if self.visual_resolver:
            return self.visual_resolver.get_character_placement(resource_id, costume_id)
        return None

    def get_costume_portrait(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> AssetResult:
        """获取角色当前皮肤资源及精确匹配状态（AssetResult）。
        
        若指定未知或不属于该角色的 costume_id，返回 exact_match=False 与明确原因。
        """
        resolution = self.costume_resolver.resolve(resource_id, costume_id)
        image = self.get_character_portrait("", resource_id, costume_id)
        return AssetResult(
            image=image,
            exact_match=resolution.exact_match,
            fallback_reason=resolution.fallback_reason,
            asset_key=resolution.spine_asset_id,
            resource_id=str(resource_id) if resource_id is not None else None,
            costume_id=str(costume_id) if costume_id is not None else None,
            requested_kind="portrait",
            resolved_kind="portrait" if resolution.exact_match else "fallback",
        )

    def get_favorite_item_icon(self, tid) -> Image.Image:
        key_str = str(tid) if tid is not None else ""
        resource = None
        if key_str in self.favorite_item_icons_map:
            resource = self.favorite_item_icons_map[key_str].get("icon")
        if resource is None:
            resource = self.registry.resolve("favorite_item", tid)
        if resource is None:
            return self.fallback("favorite")
        url = self.game_resource_url(f"icon/favoriteitem/{resource}.webp")
        return self._icon("favorite", tid, "favorite", url, allow_source=False)

    def get_cube_icon(self, tid) -> Image.Image:
        key_str = str(tid) if tid is not None else ""
        resource = None
        if key_str in self.cube_icons_map:
            resource = self.cube_icons_map[key_str].get("icon")
        if resource is None:
            resource = self.registry.resolve("cube", tid)
        if resource is None:
            return self.fallback("cube")
        url = self.game_resource_url(f"icon/equip/{resource}.webp")
        return self._icon("cube", tid, "cube", url, allow_source=False)

    def get_class_icon(self, class_name: str | None) -> Image.Image:
        """职业图标 (attacker, defender, supporter)。"""
        key = self._key(class_name)
        if key in {"attacker", "defender", "supporter"}:
            local_img = self._load_cached(f"icon/atlas_common_class/icn_class_{key}.webp")
            if local_img is not None:
                return local_img
            url = self.game_resource_url(f"icon/atlas_common_class/icn_class_{key}.webp")
            return self._icon("class", key, "slots", url)
        return self.fallback("slots")

    def get_manufacturer_icon(self, manufacturer: str | None) -> Image.Image:
        """企业 / 制造商标图标统一入口，与 get_corporation_icon 完全等价。"""
        return self.get_corporation_icon(manufacturer)

    def get_rarity_icon(self, rarity: str | None) -> Image.Image:
        """品级图标 (SSR/SR/R)。"""
        r_map = {"ssr": "001", "sr": "002", "r": "003"}
        key = self._key(rarity)
        idx = r_map.get(key)
        if idx:
            local_img = self._load_cached(f"icon/atlas_common_grade/ele_grade_icon_{idx}.webp")
            if local_img is not None:
                return local_img
            url = self.game_resource_url(f"icon/atlas_common_grade/ele_grade_icon_{idx}.webp")
            return self._icon("rarity", key, "slots", url)
        return self.fallback("slots")

    def get_currency_icon(self, currency_type) -> Image.Image | None:
        """只读取有完整来源/hash 证据的本地图标；不触发公共网络下载。"""
        definition = self.currency_registry.resolve(currency_type)
        if definition is None or not definition.icon_key:
            return None
        if (
            not definition.verified_source
            or not isinstance(definition.source_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", definition.source_sha256)
        ):
            logger.warning("ICON_UNVERIFIED: currency type %s", definition.type)
            return None
        key = self._key(definition.icon_key)
        if key == "missing":
            return None
        entry = {"sha256": definition.source_sha256}
        for base in (self.cache_dir, self.asset_dir):
            try:
                base_resolved = base.resolve()
            except OSError:
                continue
            for suffix in (".png", ".webp"):
                try:
                    path = (base / "currency" / f"{key}{suffix}").resolve()
                    if not path.is_relative_to(base_resolved) or not path.is_file():
                        continue
                except (OSError, RuntimeError, ValueError):
                    continue
                image = self._load_spine_image(path, entry)
                if image is not None:
                    return image
        return None

    def get_element_icon(self, element):
        key = self._key(element)
        key = "electronic" if key == "electric" else key
        # 优先读取本地 blabla-assets/icon/element
        local_img = self._load_cached(f"icon/element/icon-code-{key}.png")
        if local_img is not None:
            return local_img
        url = f"https://www.blablalink.com/assets/nikke/version/default/shiftysassets/images/icon-code-{key}.png" if key in {"fire", "water", "wind", "iron", "electronic"} else ""
        return self._icon("element", element, "element", url)

    def get_corporation_icon(self, corporation):
        key = self._key(corporation)
        corp_map = {"elysion": "01", "missilis": "02", "tetra": "03", "pilgrim": "04", "abnormal": "05"}
        idx = corp_map.get(key)
        if idx:
            local_img = self._load_cached(f"icon/atlas_common_corp/icn_corp_{idx}.webp")
            if local_img is not None:
                return local_img
            local_logo = self._load_cached(f"icon/atlas_common_corp/img_logo_{key}.webp")
            if local_logo is not None:
                return local_logo
        slug = "tetraline" if key == "tetra" else key
        url = f"{self.CDN}/manufacturer/icn_corp_{slug}.png" if key in {"tetra", "elysion", "missilis", "pilgrim"} else ""
        return self._icon("corporation", key, "corporation", url)

    def get_weapon_icon(self, weapon):
        key = self._key(weapon)
        w_map = {
            "ar": "assault_rifle",
            "mg": "machine_gun",
            "rl": "rocket_launcher",
            "sg": "shot_gun",
            "smg": "sub_machine_gun",
            "sr": "sniper_rifle",
        }
        full_name = w_map.get(key, key)
        local_img = self._load_cached(f"icon/weapon/icon-weapon-{full_name}.png")
        if local_img is not None:
            return local_img
        url = f"{self.CDN}/gun/icn_weapon_{key}.png" if key in {"ar", "mg", "rl", "sg", "smg", "sr"} else ""
        return self._icon("weapon", key, "weapon", url)

    def get_burst_icon(self, burst):
        key = self._key(burst)
        resource = "icn_burst_all" if key == "allstep" else (f"icn_burst_0{key[-1]}" if key in {"step1", "step2", "step3"} else "")
        if resource:
            local_img = self._load_cached(f"icon/atlas_common_class/{resource}.webp")
            if local_img is not None:
                return local_img
        url = self.game_resource_url(f"icon/atlas_common_class/{resource}.webp") if resource else ""
        return self._icon("burst", key, "burst", url)

    def _submit_prefetch(self, func) -> concurrent.futures.Future | None:
        """有界地提交出卡预取任务，避免超时请求留下无限队列。"""
        if not self._prefetch_slots.acquire(blocking=False):
            return None
        try:
            future = self._executor.submit(func)
        except Exception:
            self._prefetch_slots.release()
            raise
        future.add_done_callback(lambda _: self._prefetch_slots.release())
        return future

    def resolve_character_assets(
        self, data: CharacterCardData, timeout: float = 6.0
    ) -> CharacterCardAssets:
        """并发预取角色卡所需的所有素材，实施 5~8 秒硬预算兜底。
        超时或加载失败单素材立即降级为对应 fallback 占位图，确保 Renderer 绝不阻塞。
        """
        head_item = data.equipment.get("head")
        torso_item = data.equipment.get("torso")
        arm_item = data.equipment.get("arm")
        leg_item = data.equipment.get("leg")

        tasks = {
            "portrait": (
                lambda: self.get_character_portrait(data.name_code, data.resource_id, data.costume_id),
                lambda: self.fallback("portrait"),
            ),
            "head": (
                lambda: self.get_equipment_icon("head", head_item.equipment_id if head_item and head_item.equipped else None),
                lambda: self.fallback("head"),
            ),
            "torso": (
                lambda: self.get_equipment_icon("torso", torso_item.equipment_id if torso_item and torso_item.equipped else None),
                lambda: self.fallback("torso"),
            ),
            "arm": (
                lambda: self.get_equipment_icon("arm", arm_item.equipment_id if arm_item and arm_item.equipped else None),
                lambda: self.fallback("arm"),
            ),
            "leg": (
                lambda: self.get_equipment_icon("leg", leg_item.equipment_id if leg_item and leg_item.equipped else None),
                lambda: self.fallback("leg"),
            ),
            "favorite_item": (
                lambda: self.get_favorite_item_icon(data.favorite_item.tid if data.favorite_item else None),
                lambda: self.fallback("favorite"),
            ),
            "cube": (
                lambda: self.get_cube_icon(data.cube.tid if data.cube else None),
                lambda: self.fallback("cube"),
            ),
            "element": (
                lambda: self.get_element_icon(data.element),
                lambda: self.fallback("element"),
            ),
            "corporation": (
                lambda: self.get_corporation_icon(data.corporation),
                lambda: self.fallback("corporation"),
            ),
            "weapon": (
                lambda: self.get_weapon_icon(data.weapon),
                lambda: self.fallback("weapon"),
            ),
            "burst": (
                lambda: self.get_burst_icon(data.burst),
                lambda: self.fallback("burst"),
            ),
        }

        results: dict[str, Image.Image] = {}
        future_map: dict[concurrent.futures.Future, str] = {}

        for key, (func, _) in tasks.items():
            try:
                fut = self._submit_prefetch(func)
                if fut is None:
                    logger.warning("素材预取队列已满 [%s]，使用降级 fallback", key)
                    results[key] = tasks[key][1]()
                else:
                    future_map[fut] = key
            except Exception as exc:
                logger.warning(
                    "提交素材获取任务失败 [%s]: %s",
                    sanitize_log_text(key, max_length=120),
                    safe_exception_message(exc),
                )
                results[key] = tasks[key][1]()

        if future_map:
            done, not_done = concurrent.futures.wait(future_map.keys(), timeout=timeout)
            for fut in done:
                key = future_map[fut]
                try:
                    res = fut.result()
                    results[key] = res if res is not None else tasks[key][1]()
                except Exception as exc:
                    logger.warning(
                        "素材获取执行异常 [%s]: %s",
                        sanitize_log_text(key, max_length=120),
                        safe_exception_message(exc),
                    )
                    results[key] = tasks[key][1]()

            for fut in not_done:
                key = future_map[fut]
                safe_key = sanitize_log_text(key, max_length=120)
                if fut.cancel():
                    logger.warning("素材获取超时 (硬预算 %.1fs) [%s]，已取消未启动任务并使用 fallback", timeout, safe_key)
                else:
                    logger.warning("素材获取超时 (硬预算 %.1fs) [%s]，任务已运行并使用 fallback", timeout, safe_key)
                results[key] = tasks[key][1]()

        return CharacterCardAssets(
            portrait=results.get("portrait") or tasks["portrait"][1](),
            equipment={
                "head": results.get("head") or tasks["head"][1](),
                "torso": results.get("torso") or tasks["torso"][1](),
                "arm": results.get("arm") or tasks["arm"][1](),
                "leg": results.get("leg") or tasks["leg"][1](),
            },
            favorite_item=results.get("favorite_item") or tasks["favorite_item"][1](),
            cube=results.get("cube") or tasks["cube"][1](),
            element=results.get("element") or tasks["element"][1](),
            corporation=results.get("corporation") or tasks["corporation"][1](),
            weapon=results.get("weapon") or tasks["weapon"][1](),
            burst=results.get("burst") or tasks["burst"][1](),
        )

    def close(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            self.spine_renderer.close(wait=False)
        except Exception:
            pass

