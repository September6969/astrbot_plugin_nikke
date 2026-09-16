# SPDX-License-Identifier: GPL-3.0-or-later
"""生成角色骨骼与锚点调试标注图，用于人工质检与验证。

调试图输出到 reports/debug_placement/，绝不进入 assets/。
标注内容：
- head / chest / pelvis / feet_center / body_anchor / visual_anchor
- body_axis 轴线
- alpha_bbox 边界框
- body_bbox 区域框
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("debug_spine_placement")


def render_debug_overlay(
    image: Image.Image,
    placement_data: dict,
    output_path: Path,
    title: str = "Placement Debug",
) -> None:
    w, h = image.size
    canvas = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # 1. 绘制 alpha_bbox
    abox = placement_data.get("alpha_bbox")
    if abox:
        l, t, r, b = int(abox[0] * w), int(abox[1] * h), int(abox[2] * w), int(abox[3] * h)
        draw.rectangle((l, t, r, b), outline=(100, 200, 255, 200), width=2)
        draw.text((l + 4, t + 4), "alpha_bbox", fill=(100, 200, 255, 255))

    # 2. 绘制 body_bbox
    bbox = placement_data.get("body_bbox")
    if bbox:
        l, t, r, b = int(bbox[0] * w), int(bbox[1] * h), int(bbox[2] * w), int(bbox[3] * h)
        draw.rectangle((l, t, r, b), outline=(255, 200, 100, 180), width=2)
        draw.text((l + 4, t + 4), "body_bbox", fill=(255, 200, 100, 255))

    # 3. 绘制 body_axis
    b_axis = placement_data.get("body_axis")
    if b_axis and len(b_axis) == 2:
        p1 = (int(b_axis[0][0] * w), int(b_axis[0][1] * h))
        p2 = (int(b_axis[1][0] * w), int(b_axis[1][1] * h))
        draw.line([p1, p2], fill=(255, 80, 80, 255), width=3)

    # 4. 绘制锚点圆圈与标签
    def draw_anchor(pt_norm, color, label):
        if not pt_norm:
            return
        px, py = int(pt_norm[0] * w), int(pt_norm[1] * h)
        rad = 6
        draw.ellipse((px - rad, py - rad, px + rad, py + rad), fill=color, outline=(255, 255, 255, 255), width=2)
        draw.text((px + 8, py - 6), label, fill=color)

    draw_anchor(placement_data.get("head"), (255, 100, 100, 255), "Head")
    draw_anchor(placement_data.get("chest"), (255, 180, 50, 255), "Chest")
    draw_anchor(placement_data.get("pelvis"), (50, 220, 100, 255), "Pelvis")
    draw_anchor(placement_data.get("feet_center"), (80, 150, 255, 255), "FeetCenter")
    draw_anchor(placement_data.get("body_anchor"), (200, 100, 255, 255), "BodyAnchor")
    draw_anchor(placement_data.get("visual_anchor"), (255, 255, 50, 255), "VisualAnchor")

    # 标题头
    info_str = f"{title} | facing={placement_data.get('facing')} | src={placement_data.get('source')} | conf={placement_data.get('confidence')}"
    draw.rectangle((0, 0, w, 28), fill=(0, 0, 0, 180))
    draw.text((10, 6), info_str, fill=(255, 255, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    logger.info("Saved debug overlay: %s", output_path)


def generate_debug_overlays(base_dir: Path | str) -> list[Path]:
    base = Path(base_dir).resolve()
    mappings_dir = base / "assets" / "mappings"
    debug_dir = base / "reports" / "debug_placement"
    debug_dir.mkdir(parents=True, exist_ok=True)

    placement_file = mappings_dir / "character_placement_meta.json"
    if not placement_file.is_file():
        raise FileNotFoundError(f"Missing {placement_file}")

    placements = json.loads(placement_file.read_text(encoding="utf-8")).get("entries", {})
    output_files = []

    # 1. 真实素材 Red Hood (c470)
    c470_bundle_png = base.parent / "scratch" / "c470_bundle" / "c470_00.png"
    if c470_bundle_png.is_file() and "470:default" in placements:
        with Image.open(c470_bundle_png) as img:
            out_p = debug_dir / "c470_redhood_placement_debug.png"
            render_debug_overlay(img, placements["470:default"], out_p, "Red Hood (c470)")
            output_files.append(out_p)

    # 2. 抽样生成代表性角色调试图（拉毗 c010、艾可希雅 c102、多萝西 c017）
    samples = [
        ("10:default", "c010_rapi_debug.png", "Rapi (c010)"),
        ("102:default", "c102_exia_debug.png", "Exia (c102)"),
        ("17:default", "c017_dorothy_debug.png", "Dorothy (c017)"),
        ("10:10005", "c010_03_costume_debug.png", "Rapi Classic Vacation"),
    ]

    for key, fname, desc in samples:
        p_data = placements.get(key)
        if p_data:
            # 建立合成画板测试
            canvas = Image.new("RGBA", (1024, 1024), (30, 32, 40, 255))
            draw = ImageDraw.Draw(canvas)
            draw.ellipse((250, 180, 774, 940), fill=(60, 70, 90, 200))
            out_p = debug_dir / fname
            render_debug_overlay(canvas, p_data, out_p, desc)
            output_files.append(out_p)

    return output_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate placement debug overlays")
    parser.add_argument("--base-dir", default=str(REPO_ROOT))
    args = parser.parse_args()
    generate_debug_overlays(args.base_dir)
