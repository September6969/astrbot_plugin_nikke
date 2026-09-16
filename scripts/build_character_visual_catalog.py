# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建角色与皮肤全量视觉资源 Catalog (costume_visual_assets.json)。

严格区分：
- icon / avatar (正方形小尺寸头像)
- portrait / bust (半身像 / 预渲染头像)
- fullbody / FB (站姿大立绘)
- spine (skeleton + atlas + textures 组合型资源)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

from PIL import Image

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_character_visual_catalog")


def build_catalog(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    mappings_dir = assets_dir / "mappings"
    blabla_si_dir = base / "data" / "nikke" / "blabla-assets" / "character" / "si"
    spine_rendered_dir = assets_dir / "spine-rendered"

    # 1. 加载 200 可玩角色主数据
    master_file = assets_dir / "character_master.json"
    if not master_file.is_file():
        raise FileNotFoundError(f"character_master.json not found: {master_file}")
    master_data = json.loads(master_file.read_text(encoding="utf-8"))
    characters = master_data.get("characters", [])

    # 2. 加载服装与映射元数据
    costumes_file = assets_dir / "costumes.json"
    costumes_data = json.loads(costumes_file.read_text(encoding="utf-8")) if costumes_file.is_file() else {"entries": []}
    costume_entries = costumes_data.get("entries", [])
    costumes_by_char: dict[str, list[dict]] = {}
    for c in costume_entries:
        rid = str(c.get("character_resource_id"))
        costumes_by_char.setdefault(rid, []).append(c)

    costume_assets_file = mappings_dir / "costume_assets.json"
    costume_assets_map: dict[str, dict] = {}
    if costume_assets_file.is_file():
        ca_raw = json.loads(costume_assets_file.read_text(encoding="utf-8"))
        costume_assets_map = ca_raw.get("characters", {})

    # 3. 加载 Nikke-db FB 清单 (97 files) 与 L2D 索引 (267 entries)
    fb_inventory_file = mappings_dir / "nikke_db_fb_inventory.json"
    fb_files: set[str] = set()
    if fb_inventory_file.is_file():
        fb_files = set(json.loads(fb_inventory_file.read_text(encoding="utf-8")))

    l2d_inventory_file = mappings_dir / "nikke_db_l2d_inventory.json"
    l2d_entries: dict[str, dict] = {}
    if l2d_inventory_file.is_file():
        l2d_raw = json.loads(l2d_inventory_file.read_text(encoding="utf-8"))
        if isinstance(l2d_raw, list):
            l2d_entries = {item["id"]: item for item in l2d_raw if isinstance(item, dict) and "id" in item}
        elif isinstance(l2d_raw, dict):
            l2d_entries = l2d_raw

    # 4. 辅助图片质检
    def inspect_image(path: Path) -> dict:
        info = {
            "exists": path.is_file(),
            "width": None,
            "height": None,
            "aspect_ratio": None,
            "has_alpha": None,
            "suspicious_resolution": False,
            "possibly_not_fullbody": False,
        }
        if not path.is_file():
            return info
        try:
            with Image.open(path) as img:
                w, h = img.size
                info["width"] = w
                info["height"] = h
                info["aspect_ratio"] = round(w / h, 3) if h > 0 else None
                info["has_alpha"] = img.mode in ("RGBA", "LA") or ("transparency" in img.info)
                # 质检：若作为大立绘但尺寸极其微小，或长宽比反常
                if w < 200 or h < 300:
                    info["suspicious_resolution"] = True
                    info["possibly_not_fullbody"] = True
        except Exception:
            info["suspicious_resolution"] = True
        return info

    catalog_characters: dict[str, dict] = {}
    total_costumes_count = 0

    for char in characters:
        rid = str(char.get("resource_id", "")).strip()
        cid = str(char.get("id", ""))
        name_cn = char.get("name_cn", "")
        name_en = char.get("name_en", "")

        rid_int = int(rid) if rid.isdigit() else 0
        SPINE_ALIAS_OVERRIDES = {"113": "c940"}
        default_spine_id = SPINE_ALIAS_OVERRIDES.get(rid) or f"c{rid_int:03d}"
        default_si_name = f"si_c{rid_int:03d}_00_s.webp"

        # --- Default Assets ---
        # 1. Icon
        default_icon_file = blabla_si_dir / default_si_name
        default_icon_rel = f"data/nikke/blabla-assets/character/si/{default_si_name}" if default_icon_file.is_file() else None

        # 2. Portrait
        rendered_png = spine_rendered_dir / f"{default_spine_id}.png"
        default_portrait_rel = f"assets/spine-rendered/{default_spine_id}.png" if rendered_png.is_file() else None

        # 3. Fullbody
        # Nikke-db FB or rendered spine PNG
        fb_filename = f"{default_spine_id}_00.png"
        default_fb_rel: str | None = None
        if fb_filename in fb_files:
            default_fb_rel = f"FB/{fb_filename}"
        elif rendered_png.is_file():
            default_fb_rel = f"assets/spine-rendered/{default_spine_id}.png"

        # 4. Spine
        default_spine: dict | None = None
        if default_spine_id in l2d_entries:
            default_spine = {
                "skeleton": f"spine/{default_spine_id}/{default_spine_id}_00.skel",
                "atlas": f"spine/{default_spine_id}/{default_spine_id}_00.atlas",
                "textures": [f"spine/{default_spine_id}/{default_spine_id}_00.png"],
            }

        # --- Costumes Assets ---
        char_costumes: dict[str, dict] = {}
        ca_costumes = costume_assets_map.get(rid, {}).get("costumes", {})

        for costume_id, ca_entry in ca_costumes.items():
            spine_aid = ca_entry.get("spine_asset_id") or ""
            c_name = ca_entry.get("costume_name") or ""
            total_costumes_count += 1

            # Icon
            si_key = ca_entry.get("si_asset_key")
            c_icon_rel: str | None = None
            if si_key:
                si_file = blabla_si_dir / f"{si_key}.webp"
                if si_file.is_file():
                    c_icon_rel = f"data/nikke/blabla-assets/character/si/{si_key}.webp"

            # Portrait & Fullbody
            c_rendered = spine_rendered_dir / f"{spine_aid}.png" if spine_aid else None
            c_portrait_rel = f"assets/spine-rendered/{spine_aid}.png" if (c_rendered and c_rendered.is_file()) else None
            c_fb_rel = f"assets/spine-rendered/{spine_aid}.png" if (c_rendered and c_rendered.is_file()) else None

            # Spine
            c_spine: dict | None = None
            if spine_aid and spine_aid in l2d_entries:
                png_name = f"{spine_aid}_00.png"
                if spine_aid == "c010_02":
                    png_name = "c010_01.png"
                elif spine_aid == "c010_03":
                    png_name = "c010_02.png"
                c_spine = {
                    "skeleton": f"spine/{spine_aid}/{spine_aid}_00.skel",
                    "atlas": f"spine/{spine_aid}/{spine_aid}_00.atlas",
                    "textures": [f"spine/{spine_aid}/{png_name}"],
                }

            char_costumes[str(costume_id)] = {
                "costume_id": str(costume_id),
                "costume_name": c_name,
                "spine_asset_id": spine_aid,
                "icon": c_icon_rel,
                "portrait": c_portrait_rel,
                "fullbody": c_fb_rel,
                "spine": c_spine,
            }

        catalog_characters[rid] = {
            "character_id": cid,
            "resource_id": rid,
            "name_cn": name_cn,
            "name_en": name_en,
            "default": {
                "spine_asset_id": default_spine_id,
                "icon": default_icon_rel,
                "portrait": default_portrait_rel,
                "fullbody": default_fb_rel,
                "spine": default_spine,
            },
            "costumes": char_costumes,
        }

    output_payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_characters": len(catalog_characters),
        "total_costumes": total_costumes_count,
        "characters": catalog_characters,
    }

    out_file = mappings_dir / "costume_visual_assets.json"
    out_file.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Generated %s: %d characters, %d costumes", out_file.name, len(catalog_characters), total_costumes_count)
    return output_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build costume_visual_assets.json catalog")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    build_catalog(args.base_dir)
