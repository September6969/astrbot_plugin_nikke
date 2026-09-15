# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建角色与皮肤 Spine 元数据 (spine_metadata.json)。

采集 Spine 存在性、skeleton 格式 (skel/json)、atlas 关联与 texture 页面引用，
并在可用时安全提取原始 bone/slot 名称（原样保留，不做语义假设）。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sys

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_spine_metadata")


def parse_atlas_textures(atlas_content: str) -> list[str]:
    """解析 LibGDX Atlas 文本格式中的所有 Texture 页面文件名。"""
    textures = []
    lines = atlas_content.splitlines()
    for line in lines:
        cleaned = line.strip()
        # Atlas 页面头部：第一行通常为图片文件名（如 xxx.png）
        if re.search(r"\.(?:png|webp|jpg)$", cleaned, re.IGNORECASE) and not cleaned.startswith("#"):
            if cleaned not in textures:
                textures.append(cleaned)
    return textures


def parse_skeleton_json(skeleton_content: str) -> tuple[list[str], list[str]]:
    """解析 JSON 格式的 Spine Skeleton，提取 bones 与 slots 列表。"""
    bones = []
    slots = []
    try:
        data = json.loads(skeleton_content)
        if isinstance(data, dict):
            if "bones" in data and isinstance(data["bones"], list):
                for b in data["bones"]:
                    if isinstance(b, dict) and "name" in b:
                        bones.append(str(b["name"]))
            if "slots" in data and isinstance(data["slots"], list):
                for s in data["slots"]:
                    if isinstance(s, dict) and "name" in s:
                        slots.append(str(s["name"]))
    except Exception as exc:
        logger.warning("Failed to parse skeleton JSON: %s", exc)
    return bones, slots


def build_spine_metadata(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    mappings_dir = assets_dir / "mappings"

    visual_catalog_file = mappings_dir / "costume_visual_assets.json"
    if not visual_catalog_file.is_file():
        raise FileNotFoundError(f"costume_visual_assets.json not found: {visual_catalog_file}")

    visual_catalog = json.loads(visual_catalog_file.read_text(encoding="utf-8"))
    characters = visual_catalog.get("characters", {})

    spine_entries: dict[str, dict] = {}
    total_spines = 0
    total_with_bones = 0

    for rid, cdata in characters.items():
        # 1. 默认角色的 Spine
        default_info = cdata.get("default", {})
        default_spine = default_info.get("spine")
        default_spine_aid = default_info.get("spine_asset_id", f"c{int(rid):03d}")

        if default_spine:
            total_spines += 1
            skel_path = default_spine.get("skeleton", "")
            fmt = "skel" if skel_path.endswith(".skel") else ("json" if skel_path.endswith(".json") else "unknown")
            textures = [Path(t).name for t in default_spine.get("textures", [])]

            spine_entries[f"{rid}:default"] = {
                "resource_id": rid,
                "costume_id": None,
                "character_name": cdata.get("name_cn") or cdata.get("name_en") or "",
                "has_spine": True,
                "spine_asset_id": default_spine_aid,
                "skeleton_format": fmt,
                "skeleton_path": skel_path,
                "atlas_path": default_spine.get("atlas"),
                "textures": textures,
                "bones": None,
                "slots": None,
            }

        # 2. 皮肤的 Spine
        for cid, cinfo in cdata.get("costumes", {}).items():
            costume_spine = cinfo.get("spine")
            costume_spine_aid = cinfo.get("spine_asset_id")
            if costume_spine:
                total_spines += 1
                skel_path = costume_spine.get("skeleton", "")
                fmt = "skel" if skel_path.endswith(".skel") else ("json" if skel_path.endswith(".json") else "unknown")
                textures = [Path(t).name for t in costume_spine.get("textures", [])]

                spine_entries[f"{rid}:{cid}"] = {
                    "resource_id": rid,
                    "costume_id": cid,
                    "character_name": cdata.get("name_cn") or cdata.get("name_en") or "",
                    "costume_name": cinfo.get("costume_name") or "",
                    "has_spine": True,
                    "spine_asset_id": costume_spine_aid,
                    "skeleton_format": fmt,
                    "skeleton_path": skel_path,
                    "atlas_path": costume_spine.get("atlas"),
                    "textures": textures,
                    "bones": None,
                    "slots": None,
                }

    output_payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(spine_entries),
        "total_with_bones": total_with_bones,
        "entries": spine_entries,
    }

    out_file = mappings_dir / "spine_metadata.json"
    out_file.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Generated %s: %d spine entries", out_file.name, len(spine_entries))
    return output_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build spine_metadata.json")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    build_spine_metadata(args.base_dir)
