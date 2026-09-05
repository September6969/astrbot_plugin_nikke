# SPDX-License-Identifier: GPL-3.0-or-later
"""独立的图片资源缓存；任何缺图或网络错误均返回可渲染的占位素材。"""

from __future__ import annotations

import concurrent.futures
import io
import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from .card_models import CharacterCardAssets, CharacterCardData
from .nikke_db_provider import NikkeDbProvider
from .spine_prerenderer import SpineJob, SpinePreRenderer

logger = logging.getLogger("nikke.asset_manager")


class AssetManager:
    MAX_BYTES = 12 * 1024 * 1024
    MAX_PIXELS = 20_000_000
    CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"

    def __init__(self, cache_dir: str | Path, asset_dir: str | Path, *, remote: bool = False):
        self.cache_dir = Path(cache_dir)
        self.asset_dir = Path(asset_dir)
        self.remote = remote
        self._failed: dict[str, float] = {}
        self.nikke_db = NikkeDbProvider(self.cache_dir, self.asset_dir, remote=self.remote)
        self.spine = SpinePreRenderer(self.cache_dir)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="nikke_asset")
        try:
            self.sources = json.loads((self.asset_dir / "sources.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.sources = {}
        if not isinstance(self.sources, dict):
            self.sources = {}
        try:
            self.equipment_map = json.loads((self.asset_dir / "equipment.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.equipment_map = {}
        if not isinstance(self.equipment_map, dict):
            self.equipment_map = {}
        try:
            self.favorite_items_map = json.loads((self.asset_dir / "favorite_items.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.favorite_items_map = {}
        if not isinstance(self.favorite_items_map, dict):
            self.favorite_items_map = {}
        try:
            self.cubes_map = json.loads((self.asset_dir / "cubes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cubes_map = {}
        if not isinstance(self.cubes_map, dict):
            self.cubes_map = {}

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

    def _load(self, kind: str, key: str, remote_url: str = "") -> Image.Image | None:
        relative = f"{kind}/{self._key(key)}.png"
        for base in (self.cache_dir, self.asset_dir):
            try:
                path = base / relative
                if path.stat().st_size <= self.MAX_BYTES:
                    return self._decode(path.read_bytes())
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
        url = self.sources.get(relative, remote_url)
        if not self.remote or not isinstance(url, str) or not url.startswith("https://"):
            return None
        if self._failed.get(relative, 0) > time.monotonic():
            return None
        try:
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

    def get_character_portrait(self, name_code, resource_id, costume_id: int | str | None = None, allow_spine_enqueue: bool = False) -> Image.Image:
        # 1. 项目本地 override：优先检查 name_code，其次 resource_id
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
            key = self._key(resource_id) if str(resource_id).isdigit() else char_id
            image = self._load("portraits", key, url)

        # 4. Spine 处于实验阶段，生产出卡路径默认不投递后台预渲染任务
        if allow_spine_enqueue and char_id and char_id != "missing" and self.spine.is_available():
            cache_key = self.nikke_db.compute_cache_key(char_id, costume_id)
            prerender_path = self.spine.prerender_dir / f"{cache_key}.png"
            if not prerender_path.is_file():
                version = self.nikke_db.resolve_spine_version(char_id)
                self.spine.queue.enqueue(
                    SpineJob(cache_key=cache_key, character_id=char_id, runtime_version=version)
                )

        return image if image is not None else self.fallback("portrait")

    def get_equipment_icon(self, slot, equipment_id) -> Image.Image:
        resource = self.equipment_map.get(str(equipment_id), "")
        url = self.game_resource_url(f"icon/equip/{resource}.webp") if resource and self._key(resource) != "missing" else ""
        image = self._load("equipment", str(equipment_id), url) if equipment_id else None
        if image is None:
            image = self._load("slots", slot)
        return image if image is not None else self.fallback(slot)

    def _icon(self, kind, key, fallback, url="") -> Image.Image:
        image = self._load(kind, self._key(key), url)
        return image if image is not None else self.fallback(fallback)

    def get_favorite_item_icon(self, tid) -> Image.Image:
        if not tid:
            return self.fallback("favorite")
        resource = self.favorite_items_map.get(str(tid), "")
        url = ""
        if resource:
            if resource.startswith("http://") or resource.startswith("https://"):
                url = resource
            elif "/" in resource:
                url = self.game_resource_url(resource)
            else:
                url = self.game_resource_url(f"icon/favorite/{resource}.webp")
        return self._icon("favorite", tid, "favorite", url)

    def get_cube_icon(self, tid) -> Image.Image:
        if not tid:
            return self.fallback("cube")
        resource = self.cubes_map.get(str(tid), "")
        url = ""
        if resource:
            if resource.startswith("http://") or resource.startswith("https://"):
                url = resource
            elif "/" in resource:
                url = self.game_resource_url(resource)
            else:
                url = self.game_resource_url(f"icon/cube/{resource}.webp")
        return self._icon("cube", tid, "cube", url)

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
                lambda: self.get_character_portrait(data.name_code, data.resource_id),
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
                fut = self._executor.submit(func)
                future_map[fut] = key
            except Exception as exc:
                logger.warning("提交素材获取任务失败 [%s]: %s", key, exc)
                results[key] = tasks[key][1]()

        if future_map:
            done, not_done = concurrent.futures.wait(future_map.keys(), timeout=timeout)
            for fut in done:
                key = future_map[fut]
                try:
                    res = fut.result()
                    results[key] = res if res is not None else tasks[key][1]()
                except Exception as exc:
                    logger.warning("素材获取执行异常 [%s]: %s", key, exc)
                    results[key] = tasks[key][1]()

            for fut in not_done:
                key = future_map[fut]
                logger.warning("素材获取超时 (硬预算 %.1fs) [%s]，使用降级 fallback", timeout, key)
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
            self.spine.queue.stop(wait=False)
        except Exception:
            pass

