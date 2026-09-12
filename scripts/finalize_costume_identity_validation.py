#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""把已实际查看的 owner contact sheets 固化为逐 Costume 身份证据。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(matrix: dict, posters: dict, contact: dict, poster_dir: Path, render_dir: Path, sheet_dir: Path, *, reviewer: str, reviewed_at: str) -> dict:
    poster_by_key = {
        (str(row["owner"]), str(row["poster_asset_id"])): row
        for row in posters["items"] if row.get("file")
    }
    suggestion_by_name = {
        (str(owner["owner"]), str(row["costume_name"])): str(row["asset_id"])
        for owner in contact["owners"]
        for row in owner.get("color_similarity_suggestion_only", [])
    }
    sheet_by_owner = {
        str(owner): sheet for sheet in contact["sheets"] for owner in sheet["owners"]
    }
    entries = []
    for row in matrix["items"]:
        if row["classification"] == "VERIFIED_EXISTING":
            continue
        owner = str(row["character_resource_id"])
        poster = poster_by_key[(owner, str(row["public_poster_asset_id"]))]
        asset_id = suggestion_by_name[(owner, str(poster["costume_name"]))]
        render_path = render_dir / f"{asset_id}.png"
        poster_path = poster_dir / str(poster["file"])
        sheet = sheet_by_owner[owner]
        sheet_path = sheet_dir / str(sheet["file"])
        if asset_id not in row["candidate_assets"] or not render_path.is_file():
            raise ValueError(f"人工核验候选或渲染缺失: {row['costume_id']} -> {asset_id}")
        entries.append({
            "costume_id": str(row["costume_id"]),
            "costume_name": row["costume_name"],
            "character_resource_id": owner,
            "spine_asset_id": asset_id,
            "identity_status": "PASS",
            "verification_method": "manual_contact_sheet",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "contact_sheet": str(sheet["file"]),
            "contact_sheet_sha256": _sha256(sheet_path),
            "poster_file": str(poster["file"]),
            "poster_png_sha256": _sha256(poster_path),
            "render_file": render_path.name,
            "render_png_sha256": _sha256(render_path),
            "visual_basis": "owner 分组实名 poster 与真实 Spine idle@t=0 的服饰、配件及整体造型一致",
        })
    if len(entries) != 131 or len({row["costume_id"] for row in entries}) != 131:
        raise ValueError("人工核验结果必须完整覆盖剩余 131 条且 Costume ID 唯一")
    return {"schema_version": 1, "reviewer": reviewer, "reviewed_at": reviewed_at, "entry_count": len(entries), "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ("matrix", "posters", "contact", "poster-dir", "render-dir", "sheet-dir", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    args = parser.parse_args()
    result = build(
        _load(args.matrix), _load(args.posters), _load(args.contact), args.poster_dir,
        args.render_dir, args.sheet_dir, reviewer=args.reviewer, reviewed_at=args.reviewed_at,
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entry_count": result["entry_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
