#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""以固定 178 official inventory 生成最终 Costume 支持状态机。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FINAL_STATUSES = {"SUPPORTED", "NO_SPINE_ASSET", "BUNDLE_MISSING", "RUNTIME_UNSUPPORTED", "RENDER_FAILED"}


def build_report(inventory: dict, registry: dict, runtime_audit: dict) -> dict:
    official = inventory.get("costumes", [])
    entries = {str(row["costume_id"]): row for row in registry.get("entries", [])}
    audited = {str(row["input_costume_id"]): row for row in runtime_audit.get("alternate", {}).get("items", [])}
    if len(official) != 178:
        raise ValueError("official inventory 必须包含 178 条")
    rows = []
    for costume in official:
        costume_id = str(costume["costume_id"])
        mapped = entries.get(costume_id)
        live = audited.get(costume_id)
        if mapped is None:
            status, note = "MAPPING_MISSING", "official Costume 尚无 registry 映射"
            render_id = None
        elif live is None:
            status, note = "UNRESOLVED", "registry 映射尚无 runtime audit 结果"
            render_id = mapped["spine"]["asset_id"]
        elif live.get("status") == "PASS" and live.get("manifest_hit") and live.get("png_exists") and live.get("sha_valid") and live.get("decode_valid"):
            status, note = "SUPPORTED", "owner、resolver、manifest、SHA-256 与 PNG decode 全部通过"
            render_id = live.get("actual_render_id")
        else:
            status, note = "RENDER_FAILED", "runtime audit 未通过；详见对应 runtime evidence"
            render_id = live.get("actual_render_id")
        rows.append({
            "costume_id": costume_id,
            "character_resource_id": str(costume["character_resource_id"]),
            "character_name": costume.get("character_name", ""),
            "costume_name": costume["costume_name"],
            "costume_index": costume.get("costume_index"),
            "support_status": status,
            "safety_status": "PASS" if live and live.get("status") == "PASS" else "FAIL",
            "render_id": render_id,
            "runtime_version": live.get("runtime_version") if live else None,
            "notes": note,
        })
    counts = {status: sum(row["support_status"] == status for row in rows) for status in sorted(FINAL_STATUSES)}
    counts.update({
        "MAPPING_MISSING": sum(row["support_status"] == "MAPPING_MISSING" for row in rows),
        "UNRESOLVED": sum(row["support_status"] == "UNRESOLVED" for row in rows),
    })
    return {
        "schema_version": 2,
        "title": "Official Costume Support & Risk Audit",
        "official_source": inventory.get("authoritative_source"),
        "total_official_costumes": len(rows),
        "classification_coverage_percent": round(sum(counts[x] for x in FINAL_STATUSES) * 100 / len(rows), 2),
        "support_coverage_percent": round(counts["SUPPORTED"] * 100 / len(rows), 2),
        "breakdown": counts,
        "costumes": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--runtime-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    report = build_report(load(args.inventory), load(args.registry), load(args.runtime_audit))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": report["total_official_costumes"], "breakdown": report["breakdown"]}, ensure_ascii=False))
    return 0 if report["breakdown"]["MAPPING_MISSING"] == report["breakdown"]["UNRESOLVED"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
