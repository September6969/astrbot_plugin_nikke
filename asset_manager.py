# SPDX-License-Identifier: GPL-3.0-or-later
"""独立的图片资源缓存；任何缺图或网络错误均返回可渲染的占位素材。"""

from __future__ import annotations

import concurrent.futures
import io
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from .card_models import CharacterCardAssets, CharacterCardData
from .log_privacy import safe_exception_message, sanitize_log_text
from .nikke_db_provider import NikkeDbProvider
from .static_registry import StaticDataRegistry

logger = logging.getLogger("nikke.asset_manager")


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

    def __init__(self, cache_dir: str | Path, asset_dir: str | Path, *, remote: bool = False):
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.remote = remote
        self._failed: dict[str, float] = {}
        self._prefetch_slots = threading.BoundedSemaphore(self.MAX_PREFETCH_TASKS)
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, _InflightAsset] = {}
        self._experimental_spine = None
        self.nikke_db = NikkeDbProvider(self.cache_dir, self.asset_dir, remote=self.remote)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="nikke_asset")
        try:
            self.sources = json.loads((self.asset_dir / "sources.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.sources = {}
        if not isinstance(self.sources, dict):
            self.sources = {}
        self.registry = StaticDataRegistry(self.asset_dir)
        for error in self.registry.errors:
            logger.warning("静态 registry 校验失败：%s", error)
        self.equipment_map = self.registry.mapping("equipment")
        self.favorite_items_map = self.registry.mapping("favorite_item")
        self.cubes_map = self.registry.mapping("cube")

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
    def _decode(cls, content: bytes) -> Image.Image:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > cls.MAX_PIXELS:
                raise ValueError("素材像素过大")
            image.load()
            return image.convert("RGBA")

    def _load_cached(self, relative: str) -> Image.Image | None:
        for base in (self.cache_dir, self.asset_dir):
            try:
                path = base / relative
                if path.stat().st_size <= self.MAX_BYTES:
                    return self._decode(path.read_bytes())
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
        return None

    def _load(
        self,
        kind: str,
        key: str,
        remote_url: str = "",
        *,
        allow_source: bool = True,
    ) -> Image.Image | None:
        relative = f"{kind}/{self._key(key)}.png"
        image = self._load_cached(relative)
        if image is not None:
            return image

        # 静态 registry 素材必须只使用已确认映射生成的 URL，不能被通用来源清单绕过。
        url = self.sources.get(relative, remote_url) if allow_source else remote_url
        if not self.remote or not isinstance(url, str) or not url.startswith("https://"):
            return None
        with self._inflight_lock:
            state = self._inflight.get(relative)
            owner = state is None
            if owner:
                state = _InflightAsset()
                self._inflight[relative] = state

        if not owner:
            # 同一素材已有下载者；不重复发请求，优先复用其内存结果，再读取缓存。
            state.event.wait(timeout=7.0)
            if state.result is not None:
                return state.result
            return self._load_cached(relative)
        slot_acquired = False
        try:
            # 注册 single-flight 后再次检查，覆盖刚刚由其它路径写入缓存的竞态。
            image = self._load_cached(relative)
            if image is not None:
                return image
            if self._failed.get(relative, 0) > time.monotonic():
                return None
            # 不同键的远端请求共用全局限额；满额立即降级，不能阻塞在线程队列中。
            slot_acquired = self._remote_download_slots.acquire(blocking=False)
            if not slot_acquired:
                logger.warning("远端素材并发已满，使用占位素材: %s", relative)
                return None
            # 公共素材请求不携带账号Cookie；限制总下载时长和响应大小。
            started = time.monotonic()
            content = bytearray()
            with httpx.stream("GET", url, timeout=3, follow_redirects=True) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self.MAX_BYTES or time.monotonic() - started > 6:
                        raise ValueError("素材下载超过限制")
            image = self._decode(bytes(content))
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
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
            self._failed[relative] = time.monotonic() + 300
            return None
        finally:
            with self._inflight_lock:
                current = self._inflight.pop(relative, None)
                if current is not None:
                    if image is not None:
                        current.result = image
                    current.event.set()
            if slot_acquired:
                self._remote_download_slots.release()

    @staticmethod
    def fallback(kind: str) -> Image.Image:
        if kind == "portrait":
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
        shapes = {
            "head": [(30, 75), (30, 43), (48, 23), (80, 23), (98, 43), (98, 75), (83, 87), (83, 58), (45, 58), (45, 87)],
            "torso": [(41, 24), (52, 35), (76, 35), (87, 24), (109, 48), (92, 64), (85, 103), (43, 103), (36, 64), (19, 48)],
            "arm": [(31, 28), (53, 25), (63, 67), (80, 53), (98, 65), (78, 99), (44, 101)],
            "leg": [(36, 23), (88, 23), (96, 99), (72, 99), (62, 55), (54, 99), (30, 99)],
            "cube": [(64, 20), (108, 44), (108, 87), (64, 110), (20, 87), (20, 44)],
            "favorite": [(64, 18), (77, 44), (107, 48), (85, 70), (90, 100), (64, 85), (38, 100), (43, 70), (21, 48), (51, 44)],
        }
        draw.polygon(shapes.get(kind, [(64, 18), (107, 64), (64, 110), (21, 64)]), outline=color, width=5)
        if kind == "cube":
            draw.line([(20, 44), (64, 67), (108, 44)], fill=color, width=4)
            draw.line([(64, 67), (64, 110)], fill=color, width=4)
        return image

    def get_character_portrait(self, name_code, resource_id, costume_id: int | str | None = None) -> Image.Image:
        costume_state, _ = self.nikke_db.costume_cache_token(costume_id)
        # 默认服装可以使用历史本地 override；非默认服装禁止命中无皮肤维度的旧缓存。
        image = None
        if costume_state == "default":
            image = self._load("portraits", str(name_code))
            if image is None and resource_id:
                image = self._load("portraits", self._key(resource_id))

        # 2. 版本化预渲染缓存 / Nikke-DB 规范名缓存 (cXXX / cXXX_01)
        char_id = self.nikke_db.resolve_character_id(resource_id, costume_id) if resource_id else ""
        if image is None and char_id and char_id != "missing":
            image = self._load("portraits", char_id)

        # 3. 远端 Nikke-DB 静态 Full Body CDN
        if image is None and char_id and char_id != "missing":
            url = self.nikke_db.get_full_body_url(resource_id, costume_id)
            if costume_state == "default":
                key = self._key(resource_id) if str(resource_id).isdigit() else char_id
                image = self._load("portraits", key, url)
            else:
                # 远端与 single-flight 也必须包含皮肤身份，不能复用 resource_id 通用键。
                cache_contract = self.nikke_db.compute_cache_key(char_id, costume_id)
                scoped_key = "costume-" + hashlib.sha256(cache_contract.encode("utf-8")).hexdigest()[:24]
                image = self._load("portraits", scoped_key, url, allow_source=False)

        return image if image is not None else self.fallback("portrait")

    def enqueue_experimental_spine(self, resource_id, costume_id: int | str | None = None) -> bool:
        """显式实验入口；普通角色卡不会导入、构造或探测 Spine。"""
        from .experimental.spine_prerenderer import SpineJob, SpinePreRenderer

        char_id = self.nikke_db.resolve_character_id(resource_id, costume_id)
        if char_id == "missing":
            return False
        spine = SpinePreRenderer(self.cache_dir)
        self._experimental_spine = spine
        if not spine.is_available():
            spine.queue.stop(wait=False)
            return False
        cache_key = self.nikke_db.compute_cache_key(char_id, costume_id)
        prerender_path = spine.prerender_dir / f"{cache_key}.png"
        if prerender_path.is_file():
            spine.queue.stop(wait=False)
            return False
        version = self.nikke_db.resolve_spine_version(char_id)
        spine.queue.enqueue(SpineJob(cache_key=cache_key, character_id=char_id, runtime_version=version))
        return True

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

    def get_favorite_item_icon(self, tid) -> Image.Image:
        resource = self.registry.resolve("favorite_item", tid)
        if resource is None:
            return self.fallback("favorite")
        url = self.game_resource_url(f"icon/favorite/{resource}.webp")
        return self._icon("favorite", tid, "favorite", url, allow_source=False)

    def get_cube_icon(self, tid) -> Image.Image:
        resource = self.registry.resolve("cube", tid)
        if resource is None:
            return self.fallback("cube")
        url = self.game_resource_url(f"icon/cube/{resource}.webp")
        return self._icon("cube", tid, "cube", url, allow_source=False)

    def get_element_icon(self, element):
        key = self._key(element)
        key = "electronic" if key == "electric" else key
        url = f"https://www.blablalink.com/assets/nikke/version/default/shiftysassets/images/icon-code-{key}.png" if key in {"fire", "water", "wind", "iron", "electronic"} else ""
        return self._icon("element", element, "element", url)

    def get_corporation_icon(self, corporation):
        key = self._key(corporation)
        slug = "tetraline" if key == "tetra" else key
        url = f"{self.CDN}/manufacturer/icn_corp_{slug}.png" if key in {"tetra", "elysion", "missilis", "pilgrim"} else ""
        return self._icon("corporation", key, "corporation", url)

    def get_weapon_icon(self, weapon):
        key = self._key(weapon)
        url = f"{self.CDN}/gun/icn_weapon_{key}.png" if key in {"ar", "mg", "rl", "sg", "smg", "sr"} else ""
        return self._icon("weapon", key, "weapon", url)

    def get_burst_icon(self, burst):
        key = self._key(burst)
        resource = "icn_burst_all" if key == "allstep" else (f"icn_burst_0{key[-1]}" if key in {"step1", "step2", "step3"} else "")
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
        spine = self._experimental_spine
        if spine is not None:
            try:
                spine.queue.stop(wait=False)
            except Exception:
                pass

