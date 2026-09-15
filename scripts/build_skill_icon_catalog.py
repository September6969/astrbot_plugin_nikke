# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建角色技能图标静态映射 assets/mappings/skill_icons.json。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_skill_catalog")


def build_skill_catalog(
    skill_map_path: Path | str,
    master_path: Path | str,
    output_path: Path | str,
) -> dict:
    skill_map_file = Path(skill_map_path)
    master_file = Path(master_path)
    output_file = Path(output_path)

    if not skill_map_file.is_file():
        raise FileNotFoundError(f"Skill map file not found: {skill_map_file}")

    raw_skills = json.loads(skill_map_file.read_text(encoding="utf-8"))
    if not isinstance(raw_skills, list):
        raise ValueError(f"Skill map format invalid, expected list, got {type(raw_skills)}")

    known_chars = {}
    if master_file.is_file():
        master_data = json.loads(master_file.read_text(encoding="utf-8"))
        for c in master_data.get("characters", []):
            rid = str(c.get("resource_id", ""))
            if rid:
                known_chars[rid] = c

    characters_catalog: dict[str, dict] = {}
    for entry in raw_skills:
        if not isinstance(entry, dict):
            continue
        rid_raw = entry.get("resource_id")
        if rid_raw is None:
            continue
        rid = str(rid_raw).strip()
        if not rid:
            continue

        s1 = str(entry.get("skill1_icon") or "").strip() or None
        s2 = str(entry.get("skill2_icon") or "").strip() or None
        burst = str(entry.get("ulti_skill_icon") or "").strip() or None

        characters_catalog[rid] = {
            "normal": {
                "s1": s1,
                "s2": s2,
                "burst": burst,
            },
            "favorite": {},
        }

    # 按整数排序键
    sorted_chars = dict(
        sorted(characters_catalog.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999999)
    )

    catalog = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "data/nikke/blabla-manifests/character_character_skill_map.json",
        "total_characters": len(sorted_chars),
        "characters": sorted_chars,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Skill catalog written to %s (%d characters)", output_file, len(sorted_chars))
    return catalog


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    skill_map = base_dir / "data" / "nikke" / "blabla-manifests" / "character_character_skill_map.json"
    master = base_dir / "assets" / "character_master.json"
    output = base_dir / "assets" / "mappings" / "skill_icons.json"

    build_skill_catalog(skill_map, master, output)
