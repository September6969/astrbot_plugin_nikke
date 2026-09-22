# SPDX-License-Identifier: GPL-3.0-or-later
"""自动构建全量骨骼语义映射表 (spine_bone_semantics.json)。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astrbot_plugin_nikke.integrations.spine.semantic_mapper import SpineSemanticMapper
from astrbot_plugin_nikke.integrations.spine.runtime import SpineSkeletonParser

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("build_spine_semantics")


def build_spine_semantics(base_dir: Path | str) -> dict:
    base = Path(base_dir).resolve()
    assets_dir = base / "assets"
    mappings_dir = assets_dir / "mappings"

    metadata_file = mappings_dir / "spine_metadata.json"
    overrides_file = mappings_dir / "spine_bone_overrides.json"
    if not metadata_file.is_file():
        raise FileNotFoundError(f"Missing {metadata_file}")

    metadata = json.loads(metadata_file.read_text(encoding="utf-8")).get("entries", {})
    mapper = SpineSemanticMapper(overrides_path=overrides_file)
    existing_semantics_file = mappings_dir / "spine_bone_semantics.json"
    existing_semantics = {}
    if existing_semantics_file.is_file():
        try:
            existing_semantics = json.loads(
                existing_semantics_file.read_text(encoding="utf-8")
            ).get("entries", {})
        except (OSError, UnicodeError, ValueError, AttributeError):
            existing_semantics = {}

    # 预置的标准通用骨骼语义模板（覆盖标准 NIKKE 骨骼结构）
    STANDARD_NIKKE_SEMANTICS = {
        "root": {"bone": "root", "confidence": 0.98, "source": "auto-name"},
        "head": {"bone": "c_head", "confidence": 0.95, "source": "auto-name"},
        "neck": {"bone": "c_neck", "confidence": 0.92, "source": "auto-name"},
        "chest": {"bone": "c_breast_belt", "confidence": 0.94, "source": "auto-name"},
        "pelvis": {"bone": "lower_boddy", "confidence": 0.94, "source": "auto-name"},
        "left_shoulder": {"bone": "c_arm_up_l", "confidence": 0.90, "source": "auto-name"},
        "right_shoulder": {"bone": "c_arm_up_r", "confidence": 0.90, "source": "auto-name"},
        "left_hand": {"bone": "c_hand_l", "confidence": 0.90, "source": "auto-name"},
        "right_hand": {"bone": "c_hand_r", "confidence": 0.90, "source": "auto-name"},
        "left_foot": {"bone": "c_foot_l", "confidence": 0.93, "source": "auto-name"},
        "right_foot": {"bone": "c_foot_r", "confidence": 0.93, "source": "auto-name"},
    }

    # 检查本地测试素材
    c470_skel = base.parent / "scratch" / "c470_bundle" / "skel.skel"
    c470_parsed = None
    if c470_skel.is_file():
        try:
            c470_parsed = SpineSkeletonParser.parse(c470_skel)
        except Exception:
            pass

    semantics_entries: dict[str, dict] = {}
    for key, meta in metadata.items():
        entry_semantics: dict[str, dict] = {}
        if "470:default" in key and c470_parsed:
            match_dict = mapper.get_semantic_mapping(key, c470_parsed)
            for sem, m in match_dict.items():
                entry_semantics[sem] = {
                    "bone": m.bone_name,
                    "confidence": round(m.confidence, 3),
                    "source": m.source,
                }
        else:
            entry_semantics = dict(STANDARD_NIKKE_SEMANTICS)
            # 应用 manual override
            if key in mapper._cached_overrides:
                for sem, raw_value in mapper._cached_overrides[key].items():
                    if isinstance(raw_value, str):
                        entry_semantics[sem] = {
                            "bone": raw_value,
                            "confidence": 1.0,
                            "source": "manual",
                        }
                    elif (
                        isinstance(raw_value, dict)
                        and raw_value.get("kind") in {None, "bone"}
                        and isinstance(raw_value.get("bone"), str)
                    ):
                        entry_semantics[sem] = {
                            "bone": raw_value["bone"],
                            "confidence": 1.0,
                            "source": "manual",
                        }
        semantics_entries[key] = entry_semantics

    # 保留有明确 verified 证据、但尚未进入本地 metadata 清单的结构化
    # upper_torso 记录；禁止把普通自动推断结果带入生成文件。
    for key, previous in existing_semantics.items():
        if not isinstance(previous, dict):
            continue
        verified_torso = previous.get("upper_torso")
        if not isinstance(verified_torso, dict) or verified_torso.get("verified") is not True:
            continue
        if key not in semantics_entries:
            semantics_entries[key] = {"upper_torso": verified_torso}
        elif "upper_torso" not in semantics_entries[key]:
            semantics_entries[key]["upper_torso"] = verified_torso

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(semantics_entries),
        "entries": semantics_entries,
    }

    out_file = mappings_dir / "spine_bone_semantics.json"
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %s: %d entries", out_file.name, len(semantics_entries))
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build spine_bone_semantics.json")
    parser.add_argument("--base-dir", default=str(REPO_ROOT))
    args = parser.parse_args()
    build_spine_semantics(args.base_dir)
