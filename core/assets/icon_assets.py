# SPDX-License-Identifier: GPL-3.0-or-later
"""目录驱动的技能、装备、货币与通用游戏图标解析。"""

from __future__ import annotations

import logging
import json
import re
from pathlib import Path

from PIL import Image

from ...core.privacy import safe_exception_message, sanitize_log_text
from .environment import AssetEnvironment
from .image_codec import AssetImageCodec
from .resource_url import game_resource_url

logger = logging.getLogger("nikke.asset_manager")


def load_static_icon_mappings(asset_dir: str | Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """一次装载可选魔方与珍藏品清单；非法清单安全地退化为空目录。"""
    root = Path(asset_dir) / "mappings"
    results = []
    for filename, key in (("cube_icons.json", "cubes"), ("favorite_item_icons.json", "items")):
        try:
            payload = json.loads((root / filename).read_text(encoding="utf-8"))
            value = payload.get(key) if isinstance(payload, dict) else None
            results.append(value if isinstance(value, dict) else {})
        except (OSError, ValueError):
            results.append({})
    return results[0], results[1]


class IconAssetService:
    def __init__(self, environment: AssetEnvironment) -> None:
        self.env = environment

    def get_equipment_icon(self, slot, equipment_id) -> Image.Image:
        resource = self.env.registry.resolve("equipment", equipment_id)
        if resource is None:
            image = self.env.load("slots", slot)
            return image if image is not None else self.env.fallback(slot)
        url = game_resource_url(f"icon/equip/{resource}.webp")
        image = self.env.load("equipment", str(equipment_id), url, allow_source=False)
        if image is None:
            image = self.env.load("slots", slot)
        return image if image is not None else self.env.fallback(slot)

    def icon(self, kind, key, fallback, url="", *, allow_source=True) -> Image.Image:
        image = self.env.load(kind, self.env.key(key), url, allow_source=allow_source)
        return image if image is not None else self.env.fallback(fallback)

    def get_skill_icon(self, resource_id: str | int, slot: str, variant: str = "normal") -> Image.Image:
        canonical_slot = self.env.skill_resolver.normalize_slot(slot) or "s1"
        icon_key = self.env.skill_resolver.resolve(resource_id, canonical_slot, variant=variant)
        if not icon_key:
            return self.env.fallback(canonical_slot)
        relative = self.env.skill_resolver.get_logical_subpath(icon_key)
        image = self.env.load_cached(relative)
        if image is None:
            image = self.env.load_cached(f"skills/{icon_key}.png")
        if image is None:
            urls = [
                game_resource_url(f"icon/skill/char_skill/{icon_key}.webp"),
                game_resource_url(f"icon/skill/char_skill/{icon_key}.png"),
            ]
            image = self.env.load_path(relative, urls)
        return image if image is not None else self.env.fallback(canonical_slot)

    def get_favorite_item_icon(self, tid) -> Image.Image:
        key = str(tid) if tid is not None else ""
        entry = self.env.favorite_item_icons_map.get(key, {})
        resource = entry.get("icon") or self.env.registry.resolve("favorite_item", tid)
        if resource is None:
            return self.env.fallback("favorite")
        url = game_resource_url(f"icon/favoriteitem/{resource}.webp")
        return self.icon("favorite", tid, "favorite", url, allow_source=False)

    def get_cube_icon(self, tid) -> Image.Image:
        key = str(tid) if tid is not None else ""
        entry = self.env.cube_icons_map.get(key, {})
        resource = entry.get("icon") or self.env.registry.resolve("cube", tid)
        if resource is None:
            return self.env.fallback("cube")
        url = game_resource_url(f"icon/equip/{resource}.webp")
        return self.icon("cube", tid, "cube", url, allow_source=False)

    def get_class_icon(self, class_name: str | None) -> Image.Image:
        key = self.env.key(class_name)
        if key not in {"attacker", "defender", "supporter"}:
            return self.env.fallback("slots")
        relative = f"icon/atlas_common_class/icn_class_{key}.webp"
        return self.env.load_cached(relative) or self.icon(
            "class", key, "slots", game_resource_url(relative)
        )

    def get_manufacturer_icon(self, manufacturer: str | None) -> Image.Image:
        return self.get_corporation_icon(manufacturer)

    def get_rarity_icon(self, rarity: str | None) -> Image.Image:
        idx = {"ssr": "001", "sr": "002", "r": "003"}.get(self.env.key(rarity))
        if not idx:
            return self.env.fallback("slots")
        relative = f"icon/atlas_common_grade/ele_grade_icon_{idx}.webp"
        return self.env.load_cached(relative) or self.icon(
            "rarity", rarity, "slots", game_resource_url(relative)
        )

    def get_currency_icon(self, currency_type) -> Image.Image | None:
        definition = self.env.currency_registry.resolve(currency_type)
        if definition is None or not definition.icon_key:
            return None
        if (
            not definition.verified_source
            or not isinstance(definition.source_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", definition.source_sha256)
        ):
            logger.warning("ICON_UNVERIFIED: currency type %s", definition.type)
            return None
        key = self.env.key(definition.icon_key)
        if key == "missing":
            return None
        entry = {"sha256": definition.source_sha256}
        for base in (self.env.cache_dir, self.env.asset_dir):
            try:
                base_resolved = base.resolve()
            except OSError:
                continue
            for prefix_dir in ("icons/currency", "currency"):
                for suffix in (".png", ".webp"):
                    try:
                        path = (base / prefix_dir / f"{key}{suffix}").resolve()
                        if not path.is_relative_to(base_resolved) or not path.is_file():
                            continue
                    except (OSError, RuntimeError, ValueError):
                        continue
                    image = AssetImageCodec.load_file(path, entry)
                    if image is not None:
                        return image
        return None

    def get_element_icon(self, element):
        key = self.env.key(element)
        key = "electronic" if key == "electric" else key
        relative = f"icon/element/icon-code-{key}.png"
        image = self.env.load_cached(relative)
        if image is not None:
            return image
        url = (
            f"https://www.blablalink.com/assets/nikke/version/default/shiftysassets/images/icon-code-{key}.png"
            if key in {"fire", "water", "wind", "iron", "electronic"}
            else ""
        )
        return self.icon("element", element, "element", url)

    def get_corporation_icon(self, corporation):
        key = self.env.key(corporation)
        indices = {"elysion": "01", "missilis": "02", "tetra": "03", "pilgrim": "04", "abnormal": "05"}
        idx = indices.get(key)
        if idx:
            for relative in (
                f"icon/atlas_common_corp/icn_corp_{idx}.webp",
                f"icon/atlas_common_corp/img_logo_{key}.webp",
            ):
                image = self.env.load_cached(relative)
                if image is not None:
                    return image
        slug = "tetraline" if key == "tetra" else key
        url = f"{AssetIconCatalog.CDN}/manufacturer/icn_corp_{slug}.png" if key in {"tetra", "elysion", "missilis", "pilgrim"} else ""
        return self.icon("corporation", key, "corporation", url)

    def get_weapon_icon(self, weapon):
        key = self.env.key(weapon)
        names = {"ar": "assault_rifle", "mg": "machine_gun", "rl": "rocket_launcher", "sg": "shot_gun", "smg": "sub_machine_gun", "sr": "sniper_rifle"}
        relative = f"icon/weapon/icon-weapon-{names.get(key, key)}.png"
        image = self.env.load_cached(relative)
        if image is not None:
            return image
        url = f"{AssetIconCatalog.CDN}/gun/icn_weapon_{key}.png" if key in {"ar", "mg", "rl", "sg", "smg", "sr"} else ""
        return self.icon("weapon", key, "weapon", url)

    def get_burst_icon(self, burst):
        key = self.env.key(burst)
        resource = "icn_burst_all" if key == "allstep" else f"icn_burst_0{key[-1]}" if key in {"step1", "step2", "step3"} else ""
        if resource:
            relative = f"icon/atlas_common_class/{resource}.webp"
            image = self.env.load_cached(relative)
            if image is not None:
                return image
        else:
            relative = ""
        url = game_resource_url(relative) if relative else ""
        return self.icon("burst", key, "burst", url)


class AssetIconCatalog:
    CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"
