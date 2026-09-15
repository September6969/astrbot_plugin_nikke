# SPDX-License-Identifier: GPL-3.0-or-later
"""生成角色视觉资源接触图 (Contact Sheet)，用于人工视觉比对与审计。

输出：
- reports/contact_sheets/default_fullbody_sheet.png
- reports/contact_sheets/costume_fullbody_sheet.png
- reports/contact_sheets/portrait_sheet.png
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

# 兼容根路径模块导入
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir.parent) not in sys.path:
    sys.path.insert(0, str(base_dir.parent))
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from astrbot_plugin_nikke.character_visual_resolver import CharacterVisualAssetResolver

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_contact_sheet")


def create_sheet(
    items: list[tuple[str, str, Path | None]],  # (label, sublabel, image_path)
    output_path: Path,
    cols: int = 10,
    cell_w: int = 120,
    cell_h: int = 180,
    title: str = "Contact Sheet",
) -> Path:
    count = len(items)
    if count == 0:
        logger.warning("No items to render for %s", title)
        return output_path

    rows = math.ceil(count / cols)
    margin = 20
    header_h = 50
    footer_h = 20

    sheet_w = cols * cell_w + margin * 2
    sheet_h = rows * cell_h + header_h + footer_h + margin * 2

    canvas = Image.new("RGBA", (sheet_w, sheet_h), (24, 28, 36, 255))
    draw = ImageDraw.Draw(canvas)

    # 标题栏
    draw.text((margin, margin + 10), f"{title} (Total: {count})", fill=(220, 230, 245, 255))

    font_label_size = 11

    for idx, (label, sublabel, img_path) in enumerate(items):
        r = idx // cols
        c = idx % cols
        x = margin + c * cell_w
        y = margin + header_h + r * cell_h

        # 单元格边框
        draw.rectangle([(x + 2, y + 2), (x + cell_w - 2, y + cell_h - 2)], outline=(45, 52, 65, 255), width=1)

        # 图像区域
        thumb_area_h = cell_h - 40
        thumb_box = (x + 6, y + 6, x + cell_w - 6, y + thumb_area_h)

        loaded_img = None
        if img_path and img_path.is_file():
            try:
                with Image.open(img_path) as im:
                    loaded_img = im.convert("RGBA")
            except Exception:
                loaded_img = None

        if loaded_img is not None:
            # 保持比例缩放并居中放置
            loaded_img.thumbnail((cell_w - 12, thumb_area_h - 12), Image.Resampling.LANCZOS)
            offset_x = x + 6 + (cell_w - 12 - loaded_img.width) // 2
            offset_y = y + 6 + (thumb_area_h - 12 - loaded_img.height) // 2
            canvas.paste(loaded_img, (offset_x, offset_y), loaded_img)
        else:
            # 缺失占位框
            draw.rectangle(
                [(thumb_box[0], thumb_box[1]), (thumb_box[2], thumb_box[3])],
                fill=(38, 42, 54, 255),
                outline=(90, 40, 40, 255),
                width=1,
            )
            draw.text((x + cell_w // 2 - 24, y + thumb_area_h // 2 - 8), "MISSING", fill=(180, 80, 80, 255))

        # 底部标签
        draw.text((x + 6, y + cell_h - 32), label[:14], fill=(200, 210, 225, 255))
        draw.text((x + 6, y + cell_h - 18), sublabel[:14], fill=(130, 145, 165, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    logger.info("Saved contact sheet: %s (%dx%d)", output_path, sheet_w, sheet_h)
    return output_path


def build_all_contact_sheets(base_dir: Path | str) -> list[Path]:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    mappings_dir = assets_dir / "mappings"
    blabla_dir = base / "data" / "nikke" / "blabla-assets"
    out_dir = base / "reports" / "contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)

    visual_catalog_file = mappings_dir / "costume_visual_assets.json"
    if not visual_catalog_file.is_file():
        raise FileNotFoundError(f"Missing {visual_catalog_file}")

    catalog = json.loads(visual_catalog_file.read_text(encoding="utf-8"))
    characters = catalog.get("characters", {})

    default_fullbody_items: list[tuple[str, str, Path | None]] = []
    costume_fullbody_items: list[tuple[str, str, Path | None]] = []
    portrait_items: list[tuple[str, str, Path | None]] = []

    for rid, cdata in characters.items():
        name = cdata.get("name_cn") or cdata.get("name_en") or f"NIKKE_{rid}"
        def_info = cdata.get("default", {})

        # 1. Default Fullbody
        fb_key = def_info.get("fullbody")
        fb_path = None
        if fb_key:
            cand = base / fb_key if not fb_key.startswith("assets/") else base / fb_key
            if not cand.is_file():
                cand = assets_dir / fb_key
            if not cand.is_file():
                cand = base / "data" / "nikke" / "cache" / fb_key
            if cand.is_file():
                fb_path = cand
        default_fullbody_items.append((f"#{rid} {name}", fb_key or "NO_FB", fb_path))

        # 2. Portrait
        p_key = def_info.get("portrait")
        p_path = None
        if p_key:
            cand = base / p_key
            if cand.is_file():
                p_path = cand
        portrait_items.append((f"#{rid} {name}", p_key or "NO_PORTRAIT", p_path))

        # 3. Costume Fullbody
        for cid, cinfo in cdata.get("costumes", {}).items():
            c_name = cinfo.get("costume_name") or f"Costume_{cid}"
            cfb_key = cinfo.get("fullbody")
            cfb_path = None
            if cfb_key:
                cand = base / cfb_key
                if cand.is_file():
                    cfb_path = cand
            costume_fullbody_items.append((f"#{rid} {c_name}", f"ID:{cid}", cfb_path))

    outputs = []
    outputs.append(
        create_sheet(
            default_fullbody_items,
            out_dir / "default_fullbody_sheet.png",
            cols=10,
            title="Default Fullbody Catalog",
        )
    )
    outputs.append(
        create_sheet(
            costume_fullbody_items,
            out_dir / "costume_fullbody_sheet.png",
            cols=10,
            title="Costume Fullbody Catalog",
        )
    )
    outputs.append(
        create_sheet(
            portrait_items,
            out_dir / "portrait_sheet.png",
            cols=10,
            title="Default Portrait Catalog",
        )
    )
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build visual contact sheets")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    build_all_contact_sheets(args.base_dir)
