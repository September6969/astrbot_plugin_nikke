#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""原子化提升 178 条已交叉验证 Costume 映射到 schema v3 registry。"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def build_registry(matrix: dict, current: dict, inventory: dict, *, verified_at: str) -> dict:
    items = matrix.get("items")
    if not isinstance(items, list) or len(items) != 178:
        raise ValueError("candidate matrix 必须包含 178 条")
    allowed = {"VERIFIED_EXISTING", "HIGH_CONFIDENCE_CANDIDATE", "MANUAL_VALIDATED_CANDIDATE"}
    if any(row.get("classification") not in allowed for row in items):
        raise ValueError("matrix 仍包含未解决分类")
    source = inventory.get("authoritative_source", {})
    source_url = source.get("costume_table_url")
    source_hash = source.get("costume_table_sha256")
    if not isinstance(source_url, str) or not isinstance(source_hash, str):
        raise ValueError("official inventory 缺少来源")
    existing = {str(row.get("costume_id")): row for row in current.get("entries", []) if isinstance(row, dict)}
    output = []
    render_owners: dict[str, str] = {}
    for row in items:
        costume_id = str(row["costume_id"])
        owner = str(row["character_resource_id"])
        asset_id = row.get("matched_asset_id")
        evidence = row.get("evidence", {})
        if not isinstance(asset_id, str) or not evidence.get("asset_owner_match") or not evidence.get("nikke_db_bundle_identity"):
            raise ValueError(f"映射证据不足: {costume_id}")
        previous_owner = render_owners.get(asset_id)
        if previous_owner is not None:
            raise ValueError(f"independent render collision: {asset_id} -> {previous_owner}, {costume_id}")
        render_owners[asset_id] = costume_id
        old = existing.get(costume_id)
        if old is not None:
            old_spine = old.get("spine", {})
            if str(old.get("character_resource_id")) != owner or old_spine.get("asset_id") != asset_id:
                raise ValueError(f"冻结映射发生回归: {costume_id}")
            item = dict(old)
            item.setdefault("verification_method", "existing_verified")
        else:
            item = {
                "costume_id": costume_id,
                "character_resource_id": owner,
                "costume_name": row["costume_name"],
                "source": source_url,
                "source_sha256": source_hash,
                "verified_at": verified_at,
                "verification_method": row["verification_method"],
                "spine": {"mode": "independent_asset", "asset_id": asset_id, "skin_name": None},
                "asset_evidence": [
                    {
                        "url": evidence.get("identity_source_url"),
                        "sha256": evidence.get("identity_source_sha256"),
                        "matched_public_name": row.get("matched_public_name"),
                        "role": "public page explicitly binds Costume name to standing asset identity",
                    },
                    {
                        "source_repo": "https://github.com/Nikke-db/Nikke-db.github.io.git",
                        "source_commit": evidence.get("nikke_db_source_commit"),
                        "skel_path": evidence.get("skel_path"),
                        "skel_git_blob_sha1": evidence.get("skel_git_blob_sha1"),
                        "atlas_path": evidence.get("atlas_path"),
                        "atlas_git_blob_sha1": evidence.get("atlas_git_blob_sha1"),
                        "role": "fixed-commit independent Spine bundle identity",
                    },
                    {
                        "contact_sheet": evidence.get("manual_contact_sheet"),
                        "contact_sheet_sha256": evidence.get("manual_contact_sheet_sha256"),
                        "poster_png_sha256": evidence.get("poster_png_sha256"),
                        "render_png_sha256": evidence.get("render_png_sha256"),
                        "role": "manual owner-group poster versus Spine idle@t=0 identity review",
                    },
                ],
            }
        output.append(item)
    if set(existing) - {str(row["costume_id"]) for row in items}:
        raise ValueError("现有 verified registry 含 official universe 外条目")
    return {"schema_version": 3, "entries": output}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成全量 official Costume schema v3 registry")
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verified-at", required=True)
    args = parser.parse_args(argv)
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result = build_registry(load(args.matrix), load(args.registry), load(args.inventory), verified_at=args.verified_at)
    _atomic_write(args.output, result)
    print(json.dumps({"schema_version": 3, "entries": len(result["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
