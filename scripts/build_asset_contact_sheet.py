# SPDX-License-Identifier: GPL-3.0-or-later
"""独立调试工具：拼装技能、魔方与珍藏品图标 Contact Sheet，严禁借此修改练度卡卡面。"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw

base_dir = Path(__file__).resolve().parent.parent
if str(base_dir.parent) not in sys.path:
    sys.path.insert(0, str(base_dir.parent))
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from astrbot_plugin_nikke.core.asset_manager import AssetManager

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("contact_sheet")


def create_contact_sheet(
    images: list[tuple[str, Image.Image]],
    cols: int = 10,
    cell_size: int = 128,
    padding: int = 12,
    label_height: int = 24,
) -> Image.Image:
    if not images:
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))

    total = len(images)
    rows = math.ceil(total / cols)
    sheet_w = cols * cell_size + (cols + 1) * padding
    sheet_h = rows * (cell_size + label_height) + (rows + 1) * padding

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (25, 28, 36, 255))
    draw = ImageDraw.Draw(sheet)

    for idx, (label, img) in enumerate(images):
        c = idx % cols
        r = idx // cols
        x = padding + c * (cell_size + padding)
        y = padding + r * (cell_size + label_height + padding)

        # 缩放至单元格尺寸
        resized = img.resize((cell_size, cell_size), Image.Resampling.LANCZOS)
        sheet.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)

        # 绘制文本标签
        short_label = label if len(label) <= 16 else label[:14] + ".."
        draw.text((x + 4, y + cell_size + 4), short_label, fill=(180, 195, 220, 255))

    return sheet


def generate_all_contact_sheets(output_dir: Path | str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    assets_dir = base_dir / "assets"
    cache_dir = base_dir / "data" / "nikke" / "cache"
    manager = AssetManager(cache_dir, assets_dir, remote=False)

    # 1. Cubes
    cube_images = []
    for cid in manager.cube_icons_map.keys():
        img = manager.get_cube_icon(cid)
        name = manager.cube_icons_map[cid].get("name_en", cid)
        cube_images.append((name, img))
    cube_sheet = create_contact_sheet(cube_images, cols=7)
    cube_sheet.save(out / "cubes_contact_sheet.png", format="PNG")
    logger.info("Saved cubes contact sheet to %s", out / "cubes_contact_sheet.png")

    # 2. Favorite items
    fav_images = []
    for fid in manager.favorite_item_icons_map.keys():
        img = manager.get_favorite_item_icon(fid)
        icon_key = manager.favorite_item_icons_map[fid].get("icon", fid)
        fav_images.append((icon_key, img))
    fav_sheet = create_contact_sheet(fav_images, cols=8)
    fav_sheet.save(out / "favorite_items_contact_sheet.png", format="PNG")
    logger.info("Saved favorite items contact sheet to %s", out / "favorite_items_contact_sheet.png")

    # 3. Sample skill icons (first 30 characters)
    skill_images = []
    sample_rids = list(manager.skill_resolver._characters.keys())[:20]
    for rid in sample_rids:
        for slot in ("s1", "s2", "burst"):
            img = manager.get_skill_icon(rid, slot)
            key = manager.skill_resolver.resolve(rid, slot) or f"c{rid}_{slot}"
            skill_images.append((f"{rid}_{slot}", img))
    skill_sheet = create_contact_sheet(skill_images, cols=10)
    skill_sheet.save(out / "skills_contact_sheet_sample.png", format="PNG")
    logger.info("Saved skills sample contact sheet to %s", out / "skills_contact_sheet_sample.png")

    manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成资源 Contact Sheet")
    parser.add_argument("--output-dir", type=str, default=str(base_dir / "reports" / "contact_sheets"))
    args = parser.parse_args()
    generate_all_contact_sheets(args.output_dir)
