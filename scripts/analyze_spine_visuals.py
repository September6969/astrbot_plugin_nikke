#!/usr/bin/env python3
"""审计已渲染 Spine PNG 的可见结构并生成全量 contact sheet。

本工具只对本地 manifest/PNG 做离线分析；自动指标只能标记 suspect，
绝不把 render_success 或 alpha 非空升级为人工视觉通过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_names(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        characters = json.loads(path.read_text(encoding="utf-8")).get("characters", [])
    except (OSError, UnicodeError, ValueError):
        return {}
    return {
        str(row.get("spine_asset_id", "")): str(row.get("name_cn") or row.get("name_en") or "")
        for row in characters if isinstance(row, dict)
    }


def largest_alpha_component_ratio(alpha: Image.Image) -> float:
    """返回降采样 alpha 掩码中最大连通区域占可见像素的比例。

    这是结构性告警指标，避免把零散粒子或断裂 mesh 当作完整人物主体。
    降采样上限使 240 张批处理可预测，且不改变原始 PNG。
    """
    width, height = alpha.size
    scale = min(1.0, 128 / max(width, height)) if max(width, height) else 1.0
    target = (max(1, round(width * scale)), max(1, round(height * scale)))
    mask = alpha.resize(target, Image.Resampling.NEAREST) if target != alpha.size else alpha
    visible = {index for index, value in enumerate(mask.get_flattened_data()) if value > 8}
    total_visible = len(visible)
    if not total_visible:
        return 0.0
    largest = 0
    mask_width = mask.width
    while visible:
        pending = [visible.pop()]
        component = 0
        while pending:
            index = pending.pop()
            component += 1
            x, y = index % mask_width, index // mask_width
            for neighbour_x, neighbour_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= neighbour_x < mask.width and 0 <= neighbour_y < mask.height:
                    neighbour = neighbour_y * mask_width + neighbour_x
                    if neighbour in visible:
                        visible.remove(neighbour)
                        pending.append(neighbour)
        largest = max(largest, component)
    return round(largest / total_visible, 6)


def alpha_metrics(image: Image.Image) -> dict[str, Any]:
    alpha = image.getchannel("A")
    width, height = image.size
    bbox = alpha.getbbox()
    if bbox is None:
        return {"empty": True, "bbox": None, "canvas": [width, height]}
    left, top, right, bottom = bbox
    bbox_width, bbox_height = right - left, bottom - top
    canvas_area = width * height
    bbox_area = bbox_width * bbox_height
    visible = sum(value > 8 for value in alpha.get_flattened_data())
    return {
        "empty": False,
        "bbox": [left, top, right, bottom],
        "canvas": [width, height],
        "bbox_area_ratio": round(bbox_area / canvas_area, 6) if canvas_area else 0.0,
        "alpha_ratio": round(visible / canvas_area, 6) if canvas_area else 0.0,
        "largest_alpha_component_ratio": largest_alpha_component_ratio(alpha),
        "bbox_aspect": round(bbox_width / bbox_height, 6) if bbox_height else None,
        "subject_center": [round((left + right) / (2 * width), 6), round((top + bottom) / (2 * height), 6)],
        "margins": {"left": left, "top": top, "right": width - right, "bottom": height - bottom},
    }


def suspect_reasons(metrics: dict[str, Any]) -> list[str]:
    if metrics["empty"]:
        return ["VISUAL_EMPTY"]
    reasons: list[str] = []
    if metrics["bbox_area_ratio"] < 0.015:
        reasons.append("VISUAL_BOUNDS_TINY")
    if metrics["bbox_area_ratio"] > 0.985:
        reasons.append("VISUAL_BOUNDS_OVERSIZED")
    if metrics["alpha_ratio"] < 0.002:
        reasons.append("VISUAL_ALPHA_SPARSE")
    if metrics["largest_alpha_component_ratio"] < 0.5:
        reasons.append("VISUAL_ALPHA_FRAGMENTED")
    aspect = metrics["bbox_aspect"]
    if aspect is not None and (aspect < 0.08 or aspect > 12):
        reasons.append("VISUAL_ASPECT_EXTREME")
    if any(value <= 0 for value in metrics["margins"].values()):
        reasons.append("VISUAL_EDGE_CLIPPING")
    return reasons


def draw_sheet(items: list[dict[str, Any]], output: Path, page: int) -> str:
    columns, rows = 6, 4
    cell_width, cell_height = 300, 360
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "#11151d")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, item in enumerate(items):
        x, y = (index % columns) * cell_width, (index // columns) * cell_height
        with Image.open(item["path"]) as raw:
            portrait = raw.convert("RGBA")
        portrait.thumbnail((cell_width - 30, cell_height - 84), Image.Resampling.LANCZOS)
        canvas.paste(portrait, (x + (cell_width - portrait.width) // 2, y + 34), portrait)
        suffix = "costume" if "_" in item["asset_id"] else "default"
        draw.text((x + 8, y + 8), f"{item['asset_id']} · {item['runtime']} · {suffix}", font=font, fill="#e5e7eb")
        if item["name"]:
            draw.text((x + 8, y + cell_height - 33), item["name"][:28], font=font, fill="#a5b4fc")
        if item["suspects"]:
            draw.text((x + 8, y + cell_height - 18), ",".join(item["suspects"]), font=font, fill="#fca5a5")
    target = output / f"spine-contact-sheet-{page:02d}.png"
    canvas.save(target, "PNG", optimize=True)
    return sha256(target)


def analyze(manifest_path: Path, rendered_dir: Path, output_dir: Path, names: dict[str, str]) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("manifest assets 必须是对象")
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for asset_id, entry in sorted(assets.items()):
        if not isinstance(entry, dict):
            continue
        image_path = rendered_dir / str(entry.get("rendered_png", ""))
        result = {
            "asset_id": asset_id,
            "name": names.get(asset_id, ""),
            "runtime": str(entry.get("runtime_version", "unknown")),
            "kind": "costume" if "_" in asset_id else "default",
            "path": str(image_path),
            "png_sha256": sha256(image_path) if image_path.is_file() else None,
        }
        if not image_path.is_file():
            result.update({"metrics": {"empty": True, "bbox": None}, "suspects": ["VISUAL_FILE_MISSING"]})
        else:
            try:
                with Image.open(image_path) as image:
                    metrics = alpha_metrics(image.convert("RGBA"))
                result.update({"metrics": metrics, "suspects": suspect_reasons(metrics)})
            except (OSError, ValueError):
                result.update({"metrics": {"empty": True, "bbox": None}, "suspects": ["VISUAL_DECODE_FAILED"]})
        results.append(result)

    sheets: list[dict[str, Any]] = []
    for start in range(0, len(results), 24):
        page_items = [item for item in results[start:start + 24] if item["png_sha256"]]
        if page_items:
            page = start // 24 + 1
            sheets.append({"name": f"spine-contact-sheet-{page:02d}.png", "sha256": draw_sheet(page_items, output_dir, page)})
    suspects = [item for item in results if item["suspects"]]
    breakdown = {}
    for kind in ("default", "costume"):
        subset = [item for item in results if item["kind"] == kind]
        breakdown[kind] = {
            "total": len(subset),
            "auto_clear": sum(not item["suspects"] for item in subset),
            "suspect": sum(bool(item["suspects"]) for item in subset),
            "visual_validated": False,
        }
    report = {
        "schema_version": 1,
        "render_success_is_visual_pass": False,
        "visual_validated": False,
        "automatic_check": "Structural heuristics only; human QQ/card validation remains required.",
        "total": len(results),
        "breakdown": breakdown,
        "suspect_count": len(suspects),
        "suspects": suspects,
        "contact_sheets": sheets,
        "assets": results,
    }
    (output_dir / "spine_visual_suspects.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rendered-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--character-master", type=Path)
    args = parser.parse_args()
    report = analyze(args.manifest, args.rendered_dir, args.output_dir, load_names(args.character_master))
    print(json.dumps({
        "total": report["total"], "breakdown": report["breakdown"],
        "suspect_count": report["suspect_count"], "visual_validated": report["visual_validated"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
