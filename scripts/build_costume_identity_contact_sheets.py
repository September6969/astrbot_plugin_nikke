#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""按 owner 对齐实名 Costume poster 与真实 Spine 渲染，供人工身份核验。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _feature(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    pixels = np.asarray(image, dtype=np.uint8).reshape(-1, 4)
    visible = pixels[pixels[:, 3] >= 32, :3]
    if not len(visible):
        return np.zeros(512, dtype=np.float32)
    # 颜色直方图只用于候选排序；身份结论仍来自人工对照。
    bins = np.clip(visible // 32, 0, 7)
    index = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
    hist = np.bincount(index, minlength=512).astype(np.float32)
    return hist / max(float(np.linalg.norm(hist)), 1.0)


def _thumb(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    canvas = Image.new("RGBA", size, (26, 29, 38, 255))
    fitted = ImageOps.contain(image, (size[0] - 16, size[1] - 42))
    canvas.alpha_composite(fitted, ((size[0] - fitted.width) // 2, 34))
    return canvas


def build(
    matrix: dict[str, Any], posters: dict[str, Any], poster_dir: Path, render_dir: Path, output: Path
) -> dict[str, Any]:
    poster_rows = posters["items"]
    by_owner_posters: dict[str, list[dict[str, Any]]] = {}
    for row in poster_rows:
        if row.get("file"):
            by_owner_posters.setdefault(str(row["owner"]), []).append(row)

    by_owner_items: dict[str, list[dict[str, Any]]] = {}
    verified_assets: dict[str, set[str]] = {}
    for row in matrix["items"]:
        owner = str(row["character_resource_id"])
        by_owner_items.setdefault(owner, []).append(row)
        if row["classification"] == "VERIFIED_EXISTING" and row.get("matched_asset_id"):
            verified_assets.setdefault(owner, set()).add(str(row["matched_asset_id"]))

    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    owner_panels = []
    audit_rows = []
    for owner, items in sorted(by_owner_items.items(), key=lambda value: int(value[0])):
        unresolved = [row for row in items if row["classification"] != "VERIFIED_EXISTING"]
        if not unresolved:
            continue
        candidates = sorted(set(unresolved[0]["candidate_assets"]) - verified_assets.get(owner, set()))
        unresolved_posters = {str(row.get("public_poster_asset_id")) for row in unresolved}
        references = [
            row for row in by_owner_posters.get(owner, [])
            if str(row.get("poster_asset_id")) in unresolved_posters
        ]
        render_paths = {asset: render_dir / f"{asset}.png" for asset in candidates}
        scores = []
        for reference in references:
            poster_path = poster_dir / reference["file"]
            poster_feature = _feature(poster_path)
            ranking = []
            for asset, render_path in render_paths.items():
                if render_path.is_file():
                    ranking.append({"asset_id": asset, "color_similarity": round(float(poster_feature @ _feature(render_path)), 6)})
            ranking.sort(key=lambda value: value["color_similarity"], reverse=True)
            scores.append({"costume_name": reference["costume_name"], "poster_asset_id": reference["poster_asset_id"], "ranking": ranking})

        suggested = []
        available = [asset for asset in candidates if render_paths[asset].is_file()]
        if references and len(available) >= len(references) and len(available) <= 7:
            feature_by_asset = {asset: _feature(render_paths[asset]) for asset in available}
            best_total = -1.0
            for chosen in itertools.permutations(available, len(references)):
                total = sum(
                    float(_feature(poster_dir / reference["file"]) @ feature_by_asset[asset])
                    for reference, asset in zip(references, chosen)
                )
                if total > best_total:
                    best_total = total
                    suggested = [
                        {"costume_name": reference["costume_name"], "asset_id": asset}
                        for reference, asset in zip(references, chosen)
                    ]

        columns = max(len(references), len(candidates), 1)
        panel = Image.new("RGB", (max(1600, columns * 290 + 40), 820), (15, 17, 24))
        draw = ImageDraw.Draw(panel)
        slug = next((row.get("character_name") for row in items if row.get("character_name")), None) or owner
        anchors = ", ".join(sorted(verified_assets.get(owner, set()))) or "none"
        draw.text((20, 12), f"owner {owner} · {slug} · frozen anchors: {anchors}", font=font, fill=(245, 203, 92))
        draw.text((20, 42), "实名 poster（身份参考）", font=small, fill=(180, 190, 210))
        for index, reference in enumerate(references):
            x = 20 + index * 290
            panel.paste(_thumb(poster_dir / reference["file"], (270, 330)).convert("RGB"), (x, 70))
            draw.text((x, 405), str(reference["costume_name"])[:34], font=small, fill="white")
            draw.text((x, 426), f"poster {reference['poster_asset_id']}", font=small, fill=(140, 150, 170))
        draw.text((20, 466), "Spine idle@t=0 候选（需人工配对）", font=small, fill=(180, 190, 210))
        for index, asset in enumerate(candidates):
            x = 20 + index * 290
            path = render_paths[asset]
            if path.is_file():
                panel.paste(_thumb(path, (270, 300)).convert("RGB"), (x, 492))
            else:
                draw.rectangle((x, 492, x + 270, 792), outline=(190, 60, 70), width=3)
                draw.text((x + 20, 620), "RENDER MISSING", font=small, fill=(240, 90, 100))
            draw.text((x, 796), asset, font=small, fill="white")
        owner_panels.append((owner, panel))
        audit_rows.append({"owner": owner, "costumes": [row["costume_name"] for row in references], "candidate_assets": candidates, "color_similarity_suggestion_only": suggested, "similarity_rankings": scores})

    sheets = []
    for page, start in enumerate(range(0, len(owner_panels), 2), 1):
        panels = owner_panels[start : start + 2]
        width = max(panel.width for _, panel in panels)
        sheet = Image.new("RGB", (width, 820 * len(panels)), (10, 12, 18))
        for index, (_, panel) in enumerate(panels):
            sheet.paste(panel, (0, index * 820))
        path = output / f"costume-identity-{page:02d}.jpg"
        sheet.save(path, "JPEG", quality=91, optimize=True)
        sheets.append({"file": path.name, "owners": [owner for owner, _ in panels], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema_version": 1, "owner_count": len(owner_panels), "sheets": sheets, "owners": audit_rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--posters", type=Path, required=True)
    parser.add_argument("--poster-dir", type=Path, required=True)
    parser.add_argument("--render-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    args = parser.parse_args()
    result = build(_load(args.matrix), _load(args.posters), args.poster_dir, args.render_dir, args.output)
    args.index.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"owner_count": result["owner_count"], "sheet_count": len(result["sheets"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
