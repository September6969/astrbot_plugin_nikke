#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""把官方 178 Costume 与明示名称资产、Nikke-db index、verified registry 交叉。"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path


def _normalize_name(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value).casefold() if char.isalnum())


def build_matrix(
    inventory: dict,
    identity: dict,
    l2d: object,
    registry: dict,
    tree: dict,
    *,
    source_commit: str,
    manual_validation: dict | None = None,
) -> dict:
    official = inventory.get("costumes")
    if not isinstance(official, list) or len(official) != 178:
        raise ValueError("official inventory 必须包含 178 条")
    if identity.get("alternate_asset_total") != 178:
        raise ValueError("identity snapshot 必须包含 178 个 alternate asset")
    owner_assets = {
        str(row["character_resource_id"]): row
        for row in identity.get("owners", []) if isinstance(row, dict)
    }
    l2d_rows = [row for row in (l2d if isinstance(l2d, list) else []) if isinstance(row, dict)]
    l2d_by_id = {str(row.get("id")): row for row in l2d_rows}
    tree_rows = tree.get("tree") if isinstance(tree, dict) else None
    if not isinstance(tree_rows, list) or tree.get("truncated") is not False:
        raise ValueError("Nikke-db Git tree 必须完整且未截断")
    tree_entries = {str(row.get("path")): row for row in tree_rows if isinstance(row, dict)}
    tree_paths = set(tree_entries)
    owner_tree_assets: dict[str, list[str]] = {}
    for path in tree_paths:
        parts = path.split("/")
        if len(parts) != 3 or not path.endswith("_00.skel"):
            continue
        asset_id = parts[1]
        if not asset_id.startswith("c") or "_" not in asset_id:
            continue
        owner_token = asset_id[1:].split("_", 1)[0]
        if owner_token.isdigit():
            owner_tree_assets.setdefault(str(int(owner_token)), []).append(asset_id)
    for values in owner_tree_assets.values():
        values.sort()
    registered = {
        str(row.get("costume_id")): row
        for row in registry.get("entries", []) if isinstance(row, dict)
    }
    reviewed = {
        str(row.get("costume_id")): row
        for row in ((manual_validation or {}).get("entries", []))
        if isinstance(row, dict) and row.get("identity_status") == "PASS"
    }
    rows = []
    classifications: dict[str, int] = {}
    for costume in official:
        owner = str(costume["character_resource_id"])
        name = str(costume["costume_name"])
        source_row = owner_assets.get(owner, {})
        candidates = source_row.get("alternate_assets", []) if isinstance(source_row, dict) else []
        exact = [row for row in candidates if str(row.get("costume_name", "")).casefold() == name.casefold()]
        normalized = [row for row in candidates if _normalize_name(str(row.get("costume_name", ""))) == _normalize_name(name)]
        public_match = exact if len(exact) == 1 else normalized if len(normalized) == 1 else []
        public_method = "public_poster_exact_name" if exact else "public_poster_normalized_name" if public_match else ""
        # 已人工查看 White Rabbit 站立图，并确认公开目录的 Whtie 是转置拼写错误。
        if not public_match and str(costume["costume_id"]) == "30021":
            public_match = [row for row in candidates if row.get("asset_id") == "c270_01"]
            public_method = "manual_poster_typo_review"
        existing = registered.get(str(costume["costume_id"]))
        existing_spine = existing.get("spine", {}) if isinstance(existing, dict) else {}
        existing_asset_id = str(existing_spine.get("asset_id")) if existing_spine.get("asset_id") else None
        tree_candidates = owner_tree_assets.get(owner, [])
        reviewed_row = reviewed.get(str(costume["costume_id"]))
        reviewed_asset_id = str(reviewed_row.get("spine_asset_id")) if reviewed_row else None
        if reviewed_asset_id and reviewed_asset_id not in tree_candidates:
            raise ValueError(f"人工核验资产不属于 owner candidate set: {costume['costume_id']}")
        metadata_matches = [
            asset_id for asset_id in tree_candidates
            if asset_id in l2d_by_id
            and _normalize_name(str(l2d_by_id[asset_id].get("name", ""))).endswith(_normalize_name(name))
        ]
        metadata_asset_id = metadata_matches[0] if len(metadata_matches) == 1 else None
        asset_id = existing_asset_id or reviewed_asset_id or metadata_asset_id
        method = (
            "existing_verified" if existing_asset_id
            else "manual_contact_sheet" if reviewed_asset_id
            else "nikke_db_l2d_name_exact" if metadata_asset_id
            else ""
        )
        in_l2d = asset_id in l2d_by_id if asset_id else False
        skel_path = f"l2d/{asset_id}/{asset_id}_00.skel" if asset_id else None
        atlas_path = f"l2d/{asset_id}/{asset_id}_00.atlas" if asset_id else None
        bundle_identity = bool(skel_path in tree_paths and atlas_path in tree_paths)
        if existing_asset_id and bundle_identity:
            classification = "VERIFIED_EXISTING"
        elif reviewed_asset_id and bundle_identity:
            classification = "MANUAL_VALIDATED_CANDIDATE"
        elif metadata_asset_id and bundle_identity:
            classification = "HIGH_CONFIDENCE_CANDIDATE"
        else:
            classification = "MANUAL_VALIDATION_REQUIRED"
        classifications[classification] = classifications.get(classification, 0) + 1
        rows.append({
            "costume_id": str(costume["costume_id"]),
            "costume_name": name,
            "character_resource_id": owner,
            "character_name": costume.get("character_name"),
            "costume_index": costume.get("costume_index"),
            "existing_registry": bool(existing),
            "candidate_assets": tree_candidates,
            "candidate_count": len(tree_candidates),
            "matched_asset_id": asset_id,
            "matched_public_name": public_match[0].get("costume_name") if len(public_match) == 1 else None,
            "public_poster_asset_id": str(public_match[0].get("asset_id")) if len(public_match) == 1 else None,
            "public_poster_url": public_match[0].get("standing_asset_url") if len(public_match) == 1 else None,
            "verification_method": method or None,
            "evidence": {
                "official_owner": True,
                "asset_owner_match": bool(asset_id and asset_id.startswith(f"c{int(owner):03d}_")),
                "source_metadata_match": bool(metadata_asset_id or existing_asset_id),
                "nikke_db_l2d_name": l2d_by_id.get(asset_id, {}).get("name") if asset_id else None,
                "nikke_db_index_match": in_l2d,
                "nikke_db_bundle_identity": bundle_identity,
                "nikke_db_source_commit": source_commit,
                "skel_path": skel_path,
                "atlas_path": atlas_path,
                "skel_git_blob_sha1": tree_entries.get(skel_path, {}).get("sha") if skel_path else None,
                "atlas_git_blob_sha1": tree_entries.get(atlas_path, {}).get("sha") if atlas_path else None,
                "identity_source_url": source_row.get("source_url") if isinstance(source_row, dict) else None,
                "identity_source_sha256": source_row.get("source_sha256") if isinstance(source_row, dict) else None,
                "public_poster_match_method": public_method or None,
                "public_poster_is_not_spine_identity": True,
                "manual_contact_sheet": reviewed_row.get("contact_sheet") if reviewed_row else None,
                "manual_contact_sheet_sha256": reviewed_row.get("contact_sheet_sha256") if reviewed_row else None,
                "render_png_sha256": reviewed_row.get("render_png_sha256") if reviewed_row else None,
                "poster_png_sha256": reviewed_row.get("poster_png_sha256") if reviewed_row else None,
            },
            "classification": classification,
        })
    return {
        "schema_version": 1,
        "official_total": len(rows),
        "nikke_db_source_commit": source_commit,
        "classification_counts": classifications,
        "items": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Costume Spine candidate matrix")
    for name in ("inventory", "identity", "l2d", "registry", "tree", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--manual-validation", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    load = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    result = build_matrix(
        load(args.inventory), load(args.identity), load(args.l2d), load(args.registry), load(args.tree),
        source_commit=args.source_commit,
        manual_validation=load(args.manual_validation) if args.manual_validation else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"official_total": result["official_total"], "classification_counts": result["classification_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
