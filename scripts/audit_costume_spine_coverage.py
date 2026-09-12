#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""审计官方 Costume 清单与本地已验证 Spine 预渲染覆盖。

这是维护期离线工具。它只读取指定的官方角色资料、verified registry 和
本地 manifest/PNG；不请求网络、不启动 worker，也不会把 costume_index 推导为
Spine asset ID。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_rows(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") not in {2, 3}:
        raise ValueError("costumes.json 必须是 schema_version 2 或 3")
    rows = payload.get("entries")
    if not isinstance(rows, list):
        raise ValueError("costumes.json 缺少 entries")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("costume_id"), (str, int)):
            result[str(row["costume_id"])] = row
    return result


def _spine(row: dict[str, Any]) -> tuple[str, str | None, str | None]:
    spine = row.get("spine")
    if isinstance(spine, dict):
        mode = spine.get("mode")
        asset_id = spine.get("asset_id")
        skin_name = spine.get("skin_name")
    else:  # 仅为读取旧 registry 的兼容层，绝不由此生成映射。
        mode, asset_id, skin_name = "independent_asset", row.get("spine_asset_id"), None
    if mode not in {"independent_asset", "shared_skin"} or not isinstance(asset_id, str):
        return "unresolved", None, None
    if skin_name is not None and not isinstance(skin_name, str):
        return "unresolved", None, None
    return mode, asset_id, skin_name


def _render_id(mode: str, asset_id: str, skin_name: str | None) -> str:
    return asset_id if mode == "independent_asset" else f"{asset_id}@{skin_name}"


def build_report(
    official: Any,
    registry: Any,
    manifest: Any,
    rendered_dir: Path,
    *,
    source: str,
    source_sha256: str,
) -> dict[str, Any]:
    """构造完整分母报告；官方资料未给名称时保留 null，绝不补猜。"""
    characters = official.get("characters") if isinstance(official, dict) else official
    if not isinstance(characters, list):
        raise ValueError("官方资料必须是角色数组或包含 characters 的对象")
    entries = _registry_rows(registry)
    assets = manifest.get("assets", {}) if isinstance(manifest, dict) else {}
    if not isinstance(assets, dict):
        assets = {}

    rows: list[dict[str, Any]] = []
    for character in characters:
        if not isinstance(character, dict):
            continue
        resource_id = character.get("resource_id")
        character_name = character.get("name")
        costumes = character.get("costumes")
        if not isinstance(resource_id, (str, int)) or not isinstance(costumes, list):
            continue
        for official_costume in costumes:
            if not isinstance(official_costume, dict) or not isinstance(official_costume.get("id"), (str, int)):
                continue
            costume_id = str(official_costume["id"])
            verified = entries.get(costume_id)
            item: dict[str, Any] = {
                "costume_id": costume_id,
                "costume_name": None,
                "character_resource_id": str(resource_id),
                "character_name": character_name if isinstance(character_name, str) else None,
                "official_costume_index": official_costume.get("costume_index"),
                "spine_mode": "unresolved",
                "spine_asset_id": None,
                "skin_name": None,
                "runtime_version": None,
                "bundle_status": "UNRESOLVED",
                "render_status": "MAPPING_MISSING",
                "manifest_status": "MAPPING_MISSING",
                "source": source,
                "source_sha256": source_sha256,
                "notes": "官方资料仅确认角色所有者与 costume_id；未登记 verified Spine 表示。",
            }
            if verified is None:
                rows.append(item)
                continue
            mode, asset_id, skin_name = _spine(verified)
            item["costume_name"] = verified.get("costume_name") if isinstance(verified.get("costume_name"), str) else None
            item["spine_mode"], item["spine_asset_id"], item["skin_name"] = mode, asset_id, skin_name
            if str(verified.get("character_resource_id")) != str(resource_id):
                item.update({"render_status": "MAPPING_MISSING", "manifest_status": "OWNER_MISMATCH", "notes": "registry 所有者与官方角色不一致。"})
                rows.append(item)
                continue
            if asset_id is None:
                rows.append(item)
                continue
            render_id = _render_id(mode, asset_id, skin_name)
            manifest_entry = assets.get(render_id)
            if not isinstance(manifest_entry, dict):
                item.update({"bundle_status": "UNKNOWN", "render_status": "MANIFEST_MISSING", "manifest_status": "MANIFEST_MISSING", "notes": "verified mapping 未在本地 manifest 找到。"})
                rows.append(item)
                continue
            item["runtime_version"] = manifest_entry.get("runtime_version")
            item["bundle_status"] = "FOUND"
            png_rel = manifest_entry.get("rendered_png")
            png_path = rendered_dir / str(png_rel) if isinstance(png_rel, str) else None
            expected_hash = manifest_entry.get("sha256")
            if png_path is None or not png_path.is_file() or not isinstance(expected_hash, str):
                item.update({"render_status": "MANIFEST_MISSING", "manifest_status": "PNG_MISSING", "notes": "manifest 条目没有有效 PNG。"})
            elif _sha256(png_path) != expected_hash:
                item.update({"render_status": "MANIFEST_MISSING", "manifest_status": "SHA256_MISMATCH", "notes": "manifest PNG hash 不匹配。"})
            else:
                item.update({"render_status": "SUPPORTED_SHARED_SKIN" if mode == "shared_skin" else "SUPPORTED_RENDERED", "manifest_status": "VALID", "notes": "仅为结构性 render/manifest 覆盖；未声称人工视觉验收。"})
            rows.append(item)

    statuses = [row["render_status"] for row in rows]
    def count(status: str) -> int:
        return statuses.count(status)
    official_total = len(rows)
    verified_total = sum(row["costume_id"] in entries for row in rows)
    supported_total = count("SUPPORTED_RENDERED") + count("SUPPORTED_SHARED_SKIN")
    return {
        "schema_version": 1,
        "official_source": source,
        "official_source_sha256": source_sha256,
        "official_costume_total": official_total,
        "verified_costume_total": verified_total,
        "verified_subset_coverage_percent": round(supported_total * 100 / verified_total, 2) if verified_total else None,
        "official_costume_coverage_percent": round(supported_total * 100 / official_total, 2) if official_total else None,
        "spine_independent_total": count("SUPPORTED_RENDERED"),
        "spine_shared_skin_total": count("SUPPORTED_SHARED_SKIN"),
        "mapping_missing": count("MAPPING_MISSING"),
        "bundle_missing": count("BUNDLE_MISSING"),
        "render_failed": count("RENDER_FAILED"),
        "manifest_missing": count("MANIFEST_MISSING"),
        "items": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计完整官方 Costume 与本地 Spine 覆盖")
    parser.add_argument("--official-source", required=True, type=Path)
    parser.add_argument("--official-source-url", required=True)
    parser.add_argument("--costumes", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--rendered-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    report = build_report(
        _read_json(args.official_source), _read_json(args.costumes), _read_json(args.manifest), args.rendered_dir,
        source=args.official_source_url, source_sha256=_sha256(args.official_source),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "items"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
