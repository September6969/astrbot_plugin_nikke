# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建魔方与珍藏品/收藏品映射 assets/mappings/cube_icons.json 和 favorite_item_icons.json。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_item_catalogs")

CUBE_NAMES = {
    "1000301": ("Assault Cube", "强袭魔方"),
    "1000302": ("Onslaught Cube", "战术突击魔方"),
    "1000303": ("Resilience Cube", "强韧魔方"),
    "1000304": ("Bastion Cube", "战术魔方"),
    "1000305": ("Adjutant Cube", "副官魔方"),
    "1000306": ("Wingman Cube", "僚机魔方"),
    "1000307": ("Quantum Cube", "量子魔方"),
    "1000308": ("Vigor Cube", "活力魔方"),
    "1000309": ("Endurance Cube", "耐力魔方"),
    "1000310": ("Healing Cube", "治疗魔方"),
    "1000311": ("Tempering Cube", "淬炼魔方"),
    "1000312": ("Relic Assist Cube", "遗迹辅助魔方"),
    "1000313": ("Destruction Cube", "毁灭魔方"),
    "1000314": ("Piercing Cube", "穿透魔方"),
}


def build_cube_catalog(cubes_map_path: Path | str, output_path: Path | str) -> dict:
    cubes_file = Path(cubes_map_path)
    output_file = Path(output_path)

    raw = json.loads(cubes_file.read_text(encoding="utf-8")) if cubes_file.is_file() else {}
    cubes_catalog: dict[str, dict] = {}
    for cid_raw, res_raw in raw.items():
        cid = str(cid_raw).strip()
        res = str(res_raw).strip()
        names = CUBE_NAMES.get(cid, (f"Cube {cid}", f"魔方 {cid}"))
        cubes_catalog[cid] = {
            "cube_id": cid,
            "name_en": names[0],
            "name_cn": names[1],
            "icon": res,
            "relative_path": f"icon/equip/{res}.webp",
        }

    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "assets/cubes.json",
        "total_cubes": len(cubes_catalog),
        "cubes": cubes_catalog,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Cube catalog written to %s (%d cubes)", output_file, len(cubes_catalog))
    return catalog


def build_favorite_item_catalog(fav_map_path: Path | str, output_path: Path | str) -> dict:
    fav_file = Path(fav_map_path)
    output_file = Path(output_path)

    raw = json.loads(fav_file.read_text(encoding="utf-8")) if fav_file.is_file() else {}
    items_catalog: dict[str, dict] = {}
    for tid_raw, res_raw in raw.items():
        tid = str(tid_raw).strip()
        res = str(res_raw).strip()

        # 区分通用武器收藏品 (10xxxx) 与角色专属珍藏品 (20xxxx)
        if tid.startswith("10"):
            item_type = "collection_item"
            # 例如 si_favoriteitem_ar_00
            parts = res.split("_")
            weapon = parts[2] if len(parts) >= 3 else None
            char_rid = None
        else:
            item_type = "favorite_item"
            weapon = None
            # 例如 si_favoriteitem_c072_00
            parts = res.split("_")
            char_tag = parts[2] if len(parts) >= 3 else ""
            char_rid = str(int(char_tag[1:])) if char_tag.startswith("c") and char_tag[1:].isdigit() else None

        items_catalog[tid] = {
            "item_id": tid,
            "item_type": item_type,
            "character_resource_id": char_rid,
            "weapon": weapon,
            "icon": res,
            "relative_path": f"icon/favoriteitem/{res}.webp",
        }

    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "assets/favorite_items.json",
        "total_items": len(items_catalog),
        "items": items_catalog,
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Favorite item catalog written to %s (%d items)", output_file, len(items_catalog))
    return catalog


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    cubes_in = base_dir / "assets" / "cubes.json"
    cubes_out = base_dir / "assets" / "mappings" / "cube_icons.json"
    fav_in = base_dir / "assets" / "favorite_items.json"
    fav_out = base_dir / "assets" / "mappings" / "favorite_item_icons.json"

    build_cube_catalog(cubes_in, cubes_out)
    build_favorite_item_catalog(fav_in, fav_out)
