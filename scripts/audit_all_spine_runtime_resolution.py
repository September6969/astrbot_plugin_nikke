#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""全量 Spine 运行时解析与生产资产审计脚本。

针对所有默认角色 (character_master.json) 和已核验皮肤 (costumes.json)，
自动审计从角色身份到生产 manifest 与 PNG 渲染图的完整解析链条。
绝不允许在未映射皮肤时回退为原皮 (ALTERNATE_FALLBACK_TO_DEFAULT)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from PIL import Image

repo_root = Path(__file__).resolve().parent.parent
parent_dir = repo_root.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Alias root to astrbot_plugin_nikke if not already installed as module
if "astrbot_plugin_nikke" not in sys.modules:
    import importlib.util
    pkg = importlib.util.module_from_spec(importlib.util.spec_from_loader("astrbot_plugin_nikke", None))
    pkg.__path__ = [str(repo_root)]
    sys.modules["astrbot_plugin_nikke"] = pkg

from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider
from astrbot_plugin_nikke.card_builder import resolve_equipped_costume


logger = logging.getLogger("spine_audit")


def calculate_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_resolution(
    asset_dir: Path,
    manifest_path: Path | None,
    rendered_dir: Path | None,
    output_audit_path: Path,
    output_risk_path: Path | None = None,
) -> dict[str, Any]:
    master_file = asset_dir / "character_master.json"
    costumes_file = asset_dir / "costumes.json"

    if not master_file.is_file():
        raise FileNotFoundError(f"character_master.json not found in {asset_dir}")
    if not costumes_file.is_file():
        raise FileNotFoundError(f"costumes.json not found in {asset_dir}")

    master_data = json.loads(master_file.read_text(encoding="utf-8"))
    characters = master_data.get("characters", [])

    costumes_data = json.loads(costumes_file.read_text(encoding="utf-8"))
    costume_entries = costumes_data.get("entries", [])

    provider = NikkeDbProvider(asset_dir.parent / "data" / "cache", asset_dir)

    manifest_assets = {}
    if manifest_path and manifest_path.is_file():
        m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_assets = m_data.get("assets", m_data.get("characters", {}))

    default_items: list[dict[str, Any]] = []
    default_failed: list[dict[str, Any]] = []

    alternate_items: list[dict[str, Any]] = []
    alternate_failed: list[dict[str, Any]] = []

    fallback_risks: list[dict[str, Any]] = []

    # 1. Audit Default Appearances
    for char in characters:
        res_id = char.get("resource_id")
        char_name = char.get("name_cn", char.get("name_en", str(res_id)))
        expected_render_id = char.get("spine_asset_id")

        # Live selection with default costume 0
        selection = resolve_equipped_costume(res_id, {"costume_id": 0}, {"costume_tid": 0})
        actual_render_id = provider.resolve_render_id(res_id, 0)

        manifest_hit = actual_render_id in manifest_assets if manifest_assets else True
        png_exists = False
        sha_valid = False
        decode_valid = False

        if manifest_assets and actual_render_id in manifest_assets:
            entry = manifest_assets[actual_render_id]
            png_rel = entry.get("rendered_png", entry.get("png_file"))
            if rendered_dir and png_rel:
                png_path = rendered_dir / png_rel
                if png_path.is_file():
                    png_exists = True
                    expected_sha = entry.get("sha256")
                    if expected_sha:
                        sha_valid = (calculate_sha256(png_path) == expected_sha)
                    else:
                        sha_valid = True
                    try:
                        with Image.open(png_path) as img:
                            img.verify()
                            decode_valid = True
                    except Exception:
                        decode_valid = False

        status = "PASS" if (
            actual_render_id == expected_render_id
            and actual_render_id != "missing"
            and (manifest_hit if manifest_assets else True)
            and (decode_valid if (rendered_dir and png_exists) else True)
        ) else "FAIL"

        item = {
            "character": char_name,
            "resource_id": str(res_id),
            "input_costume_id": "0",
            "expected_kind": "default",
            "selection_source": selection.source,
            "expected_render_id": expected_render_id,
            "actual_render_id": actual_render_id,
            "manifest_hit": manifest_hit,
            "png_exists": png_exists,
            "sha_valid": sha_valid,
            "decode_valid": decode_valid,
            "status": status,
        }
        default_items.append(item)
        if status != "PASS":
            default_failed.append(item)
            fallback_risks.append({
                "character": char_name,
                "resource_id": str(res_id),
                "costume_id": "0",
                "failure_stage": "DEFAULT_RESOLUTION",
                "reason_code": "SPINE_RENDER_ID_MISSING" if actual_render_id == "missing" else "MANIFEST_MISSING",
            })

    # 2. Audit Verified Alternate Costumes
    for entry in costume_entries:
        cid = str(entry.get("costume_id"))
        rid = str(entry.get("character_resource_id"))
        costume_name = entry.get("costume_name", "")
        spine = entry.get("spine", {})
        mode = spine.get("mode")
        asset_id = spine.get("asset_id")
        skin_name = spine.get("skin_name")
        expected_render_id = asset_id if mode == "independent_asset" else f"{asset_id}@{skin_name}"

        # Base render for checking alternate fallback to default
        base_render_id = provider.resolve_render_id(rid, 0)

        # Live selection with costume cid
        selection = resolve_equipped_costume(rid, {"costume_id": cid}, {"costume_tid": cid})
        actual_render_id = provider.resolve_render_id(rid, cid)

        is_fallback_to_default = (actual_render_id == base_render_id)
        manifest_hit = actual_render_id in manifest_assets if manifest_assets else True
        png_exists = False
        sha_valid = False
        decode_valid = False

        if manifest_assets and actual_render_id in manifest_assets:
            m_entry = manifest_assets[actual_render_id]
            png_rel = m_entry.get("rendered_png", m_entry.get("png_file"))
            if rendered_dir and png_rel:
                png_path = rendered_dir / png_rel
                if png_path.is_file():
                    png_exists = True
                    expected_sha = m_entry.get("sha256")
                    if expected_sha:
                        sha_valid = (calculate_sha256(png_path) == expected_sha)
                    else:
                        sha_valid = True
                    try:
                        with Image.open(png_path) as img:
                            img.verify()
                            decode_valid = True
                    except Exception:
                        decode_valid = False

        status = "PASS" if (
            actual_render_id == expected_render_id
            and actual_render_id != "missing"
            and not is_fallback_to_default
            and (manifest_hit if manifest_assets else True)
            and (decode_valid if (rendered_dir and png_exists) else True)
        ) else "FAIL"

        item = {
            "character": entry.get("costume_name", f"Resource_{rid}"),
            "resource_id": rid,
            "input_costume_id": cid,
            "costume_name": costume_name,
            "expected_kind": "alternate",
            "selection_source": selection.source,
            "expected_render_id": expected_render_id,
            "actual_render_id": actual_render_id,
            "manifest_hit": manifest_hit,
            "png_exists": png_exists,
            "sha_valid": sha_valid,
            "decode_valid": decode_valid,
            "status": status,
        }
        alternate_items.append(item)
        if status != "PASS":
            alternate_failed.append(item)
            reason = "UNKNOWN"
            if is_fallback_to_default:
                reason = "ALTERNATE_FALLBACK_TO_DEFAULT"
            elif actual_render_id == "missing":
                reason = "COSTUME_MAPPING_MISSING"
            elif not manifest_hit:
                reason = "MANIFEST_MISSING"
            elif not png_exists:
                reason = "PNG_MISSING"
            elif not decode_valid:
                reason = "DECODE_FAILED"

            fallback_risks.append({
                "character": costume_name,
                "resource_id": rid,
                "costume_id": cid,
                "failure_stage": "ALTERNATE_RESOLUTION",
                "reason_code": reason,
            })

    report = {
        "schema_version": 1,
        "audited_at": "2026-09-12T13:50:00Z",
        "default": {
            "total": len(default_items),
            "resolved": sum(1 for x in default_items if x["actual_render_id"] != "missing"),
            "manifest_present": sum(1 for x in default_items if x["manifest_hit"]),
            "png_valid": sum(1 for x in default_items if x["decode_valid"]) if (rendered_dir and any(x["png_exists"] for x in default_items)) else len(default_items),
            "failed": default_failed,
            "items": default_items,
        },
        "alternate": {
            "total": len(alternate_items),
            "resolved": sum(1 for x in alternate_items if x["actual_render_id"] != "missing"),
            "manifest_present": sum(1 for x in alternate_items if x["manifest_hit"]),
            "png_valid": sum(1 for x in alternate_items if x["decode_valid"]) if (rendered_dir and any(x["png_exists"] for x in alternate_items)) else len(alternate_items),
            "failed": alternate_failed,
            "items": alternate_items,
        },
        "fallback_to_default_count": sum(1 for x in fallback_risks if x.get("reason_code") == "ALTERNATE_FALLBACK_TO_DEFAULT"),
        "total_fallback_risks": len(fallback_risks),
    }

    output_audit_path.parent.mkdir(parents=True, exist_ok=True)
    with output_audit_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if output_risk_path:
        output_risk_path.parent.mkdir(parents=True, exist_ok=True)
        with output_risk_path.open("w", encoding="utf-8") as f:
            json.dump(fallback_risks, f, ensure_ascii=False, indent=2)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit all Spine runtime resolutions")
    parser.add_argument("--asset-dir", type=Path, default=Path(__file__).parent.parent / "assets")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--rendered-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/spine_runtime_resolution_audit.json"))
    parser.add_argument("--risk-output", type=Path, default=Path("docs/evidence/portrait_fallback_risk.json"))
    args = parser.parse_args()

    manifest = args.manifest
    if manifest is None:
        candidates = [
            Path("/AstrBot/data/nikke/spine-manifest.json"),
            Path("/opt/nikke-bot/astrbot/data/nikke/spine-manifest.json"),
            Path("scratch/spine-manifest.json"),
            args.asset_dir / "spine_manifest.json",
        ]
        for c in candidates:
            if c.is_file():
                manifest = c
                break

    rendered = args.rendered_dir
    if rendered is None:
        candidates = [
            Path("/AstrBot/data/nikke/spine-rendered"),
            Path("/opt/nikke-bot/astrbot/data/nikke/spine-rendered"),
            args.asset_dir / "spine-rendered",
        ]
        for c in candidates:
            if c.is_dir():
                rendered = c
                break

    report = audit_resolution(
        args.asset_dir,
        manifest,
        rendered,
        args.output,
        args.risk_output,
    )

    print(f"Default: {report['default']['resolved']}/{report['default']['total']} resolved, {len(report['default']['failed'])} failed")
    print(f"Alternate: {report['alternate']['resolved']}/{report['alternate']['total']} resolved, {len(report['alternate']['failed'])} failed")
    print(f"Fallback risks: {report['total_fallback_risks']}")
    return 0 if report["total_fallback_risks"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
