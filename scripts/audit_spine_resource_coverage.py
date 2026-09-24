#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""离线审计 canonical Character、Nikke-db Spine、manifest、PNG 与 framing 元数据。

默认只读仓库内的 upstream 快照。只有显式传入 ``--refresh-upstream`` 才会访问
GitHub API 并更新快照；审计本身不下载或修改任何角色资源。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.assets.spine_manifest import SpineManifestStore
from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider

SOURCE_REPO = "https://github.com/Nikke-db/Nikke-db.github.io"
SOURCE_API = "https://api.github.com/repos/Nikke-db/Nikke-db.github.io"
RENDER_ID_RE = re.compile(r"^c[0-9]+(?:_[0-9]+)?(?:@[a-z0-9][a-z0-9_-]*)?$", re.ASCII)
UPSTREAM_ID_RE = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)
L2D_PATH_RE = re.compile(r"^l2d/(c[0-9]+(?:_[0-9]+)?)/(.*)$", re.ASCII)
FB_PATH_RE = re.compile(r"^(?:images/)?FB/(c[0-9]+(?:_[0-9]+)?)_00\.png$", re.ASCII)
DEFAULT_SNAPSHOT = Path("docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _api_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "nikke-post-refactor-coverage-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_upstream_snapshot() -> dict[str, Any]:
    """显式维护时抓取一次 upstream tree；CI 与普通审计不调用网络。"""
    ref = _api_json(f"{SOURCE_API}/git/ref/heads/main")
    commit_sha = ref["object"]["sha"]
    tree = _api_json(f"{SOURCE_API}/git/trees/{commit_sha}?recursive=1")
    if tree.get("truncated") is True:
        raise ValueError("Nikke-db Git tree 被截断，拒绝生成不完整快照")
    l2d_files = []
    fb_files = []
    for item in tree.get("tree", []):
        path = item.get("path")
        if item.get("type") != "blob" or not isinstance(path, str):
            continue
        if path.startswith("l2d/"):
            l2d_files.append({"path": path, "sha": item.get("sha"), "size": item.get("size")})
        elif FB_PATH_RE.fullmatch(path):
            fb_files.append({"path": path, "sha": item.get("sha"), "size": item.get("size")})
    sort_key = lambda row: row["path"]
    return {
        "schema_version": 2,
        "source_repo": SOURCE_REPO,
        "ref": "main",
        "commit_sha": commit_sha,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "l2d_files": sorted(l2d_files, key=sort_key),
        "fb_files": sorted(fb_files, key=sort_key),
    }


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _consumer_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """经当前 CharacterMaster 与 NikkeDbProvider 得到生产可解析的 render identity。"""
    assets = root / "assets"
    master_path = assets / "data" / "character_master.json"
    if not master_path.is_file():
        master_path = assets / "character_master.json"
    payload = _read_json(master_path)
    rows = payload.get("characters", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("CharacterMaster.characters 必须是数组")

    master = CharacterMasterResolver(master_path)
    # resolve_render_id 不访问网络，也不会写 cache；路径仅作为未使用的缓存命名空间。
    provider = NikkeDbProvider(root / ".audit-cache-unused", assets, remote=False, master_resolver=master)
    defaults: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    identity_mismatches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_id = row.get("resource_id")
        character = master.resolve_resource_id(resource_id) if resource_id is not None else None
        render_id = provider.resolve_render_id(resource_id, None) if resource_id is not None else "missing"
        record = {
            "identity": f"{resource_id}:default",
            "resource_id": str(resource_id) if resource_id is not None else None,
            "character_key": row.get("character_key"),
            "render_id": render_id,
            "kind": "default",
        }
        if render_id == "missing" or character is None:
            unresolved.append({**record, "reason": "production_identity_unresolved"})
            continue
        defaults.append(record)
        declared = str(row.get("spine_asset_id") or "").strip().lower()
        if declared and (declared != render_id or character.spine_asset_id != render_id):
            identity_mismatches.append(
                {
                    **record,
                    "master_render_id": declared,
                    "master_resolver_render_id": character.spine_asset_id,
                    "provider_render_id": render_id,
                }
            )

    costumes: list[dict[str, Any]] = []
    for costume_id, owner in sorted(provider.costume_character_map.items()):
        character = master.resolve_resource_id(owner)
        render_id = provider.resolve_render_id(owner, costume_id)
        resource_id = str(character.resource_id) if character is not None else str(owner)
        record = {
            "identity": f"{resource_id}:costume:{costume_id}",
            "resource_id": resource_id,
            "costume_id": str(costume_id),
            "character_key": character.character_key if character is not None else None,
            "render_id": render_id,
            "kind": "verified_costume",
        }
        if character is None or render_id == "missing":
            unresolved.append({**record, "reason": "verified_costume_identity_unresolved"})
        else:
            costumes.append(record)

    key = lambda row: (int(row["resource_id"]) if str(row["resource_id"]).isdigit() else 0, row["identity"])
    return sorted(defaults, key=key), sorted(costumes, key=key), sorted(unresolved, key=key)


def _upstream_sets(snapshot: dict[str, Any]) -> dict[str, Any]:
    schema = snapshot.get("schema_version")
    l2d_files = snapshot.get("l2d_files", snapshot.get("files", []))
    if schema not in (1, 2) or not isinstance(l2d_files, list):
        raise ValueError("upstream snapshot schema 无效或缺少 L2D 文件列表")

    grouped: dict[str, set[str]] = {}
    for item in l2d_files:
        path = item.get("path") if isinstance(item, dict) else None
        match = L2D_PATH_RE.fullmatch(path) if isinstance(path, str) else None
        if match:
            render_id, relative = match.groups()
            grouped.setdefault(render_id, set())
            if "/" not in relative:
                grouped[render_id].add(Path(relative).suffix.lower())
    complete = {
        render_id
        for render_id, extensions in grouped.items()
        if {".skel", ".atlas", ".png"} <= extensions
    }

    fb_files = snapshot.get("fb_files")
    if schema == 2 and not isinstance(fb_files, list):
        raise ValueError("schema_version=2 upstream snapshot 缺少 fb_files 数组")
    fb_ids: set[str] = set()
    for item in fb_files or []:
        path = item.get("path") if isinstance(item, dict) else None
        match = FB_PATH_RE.fullmatch(path) if isinstance(path, str) else None
        if match:
            fb_ids.add(match.group(1))
    return {
        "render_ids": set(grouped),
        "complete_ids": complete,
        "incomplete_ids": set(grouped) - complete,
        "fb_ids": fb_ids,
        "fb_known": schema == 2,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_state(root: Path) -> dict[str, Any]:
    assets = root / "assets"
    store = SpineManifestStore(assets, root / ".audit-cache-unused")
    entries = store.entries
    statuses: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for render_id, entry in sorted(entries.items()):
        reasons: list[str] = []
        path, declared = store.resolve_png(render_id)
        if not declared:
            reasons.append("render_id_not_declared_by_manifest")
        if path is None or not path.is_file():
            reasons.append("manifest_png_missing_or_path_invalid")
        else:
            paths[render_id] = path
        image = store.load_png(render_id)
        if image is None:
            reasons.append("manifest_png_integrity_rejected")

        raw_sha = None
        dimensions = None
        alpha_bbox = None
        rgba_sha = None
        if path is not None and path.is_file():
            try:
                raw_sha = _file_sha256(path)
                with Image.open(path) as opened:
                    rgba = opened.convert("RGBA")
                    dimensions = list(rgba.size)
                    alpha_bbox = list(rgba.getchannel("A").getbbox()) if rgba.getchannel("A").getbbox() else None
                    rgba_sha = hashlib.sha256(rgba.tobytes()).hexdigest()
            except (OSError, ValueError):
                reasons.append("manifest_png_unreadable")
            if raw_sha is not None and entry.get("sha256") != raw_sha:
                reasons.append("manifest_raw_sha256_mismatch")
            if dimensions is not None and any(
                entry.get(key) is not None and entry.get(key) != value
                for key, value in (("width", dimensions[0]), ("height", dimensions[1]))
            ):
                reasons.append("manifest_dimensions_mismatch")
            if entry.get("file_size") is not None and entry.get("file_size") != path.stat().st_size:
                reasons.append("manifest_file_size_mismatch")
        if str(entry.get("spine_asset_id", render_id)).lower() != render_id:
            reasons.append("manifest_render_identity_mismatch")
        statuses[render_id] = {
            "render_id": render_id,
            "local_relpath": entry.get("local_relpath") or entry.get("png_file") or entry.get("rendered_png"),
            "runtime_version": entry.get("runtime_version"),
            "declared": bool(declared),
            "valid": image is not None and not reasons,
            "reasons": sorted(set(reasons)),
            "sha256": raw_sha,
            "rgba_pixel_sha256": rgba_sha,
            "dimensions": dimensions,
            "alpha_bbox": alpha_bbox,
            "manifest_alpha_bbox": entry.get("alpha_bbox"),
        }
    png_ids = {
        path.stem.lower()
        for path in (assets / "spine-rendered").glob("*.png")
        if RENDER_ID_RE.fullmatch(path.stem.lower())
    } if (assets / "spine-rendered").is_dir() else set()
    return {
        "store": store,
        "entries": entries,
        "statuses": statuses,
        "verified_ids": {rid for rid, status in statuses.items() if status["valid"]},
        "png_ids": png_ids,
        "paths": paths,
    }


def _anchor_state(
    root: Path,
    manifest_state: dict[str, Any],
    consumers: list[dict[str, Any]],
) -> dict[str, Any]:
    assets = root / "assets"
    anchor_path = assets / "data" / "face_anchors.json"
    if not anchor_path.is_file():
        anchor_path = assets / "face_anchors.json"
    payload = _read_json(anchor_path)
    records = payload.get("records", {}) if isinstance(payload, dict) else {}
    if not isinstance(records, dict):
        records = {}
    consumer_keys: dict[str, set[str]] = {}
    for row in consumers:
        if not RENDER_ID_RE.fullmatch(str(row.get("render_id", ""))):
            continue
        rid = str(row["render_id"])
        suffix = str(row.get("costume_id") or "default")
        consumer_keys.setdefault(rid, set()).add(f"{row['resource_id']}:{suffix}")

    bone_semantics = _read_json(assets / "mappings" / "spine_bone_semantics.json").get("entries", {})
    bone_overrides = _read_json(assets / "mappings" / "spine_bone_overrides.json").get("entries", {})
    valid: set[str] = set()
    trusted_core: set[str] = set()
    statuses: dict[str, dict[str, Any]] = {}
    for render_id, row in sorted(records.items()):
        if not isinstance(row, dict):
            statuses[render_id] = {"valid": False, "trusted_semantic_core_axis": False, "reason": "invalid_anchor_record"}
            continue
        path = manifest_state["paths"].get(render_id)
        if path is None:
            path = assets / "spine-rendered" / f"{render_id}.png"
        reasons: list[str] = []
        raw_sha = None
        rgba_sha = None
        dimensions = None
        if path.is_file():
            try:
                raw_sha = _file_sha256(path)
                with Image.open(path) as opened:
                    rgba = opened.convert("RGBA")
                    dimensions = list(rgba.size)
                    rgba_sha = hashlib.sha256(rgba.tobytes()).hexdigest()
            except (OSError, ValueError):
                reasons.append("anchor_png_unreadable")
        else:
            reasons.append("anchor_png_missing")
        if raw_sha is None or row.get("png_sha256") != raw_sha:
            reasons.append("anchor_raw_sha256_mismatch")
        if rgba_sha is None or row.get("pixel_sha256") != rgba_sha:
            reasons.append("anchor_pixel_sha256_mismatch")
        if dimensions is None or row.get("image_size") != dimensions:
            reasons.append("anchor_dimensions_mismatch")
        is_valid = not reasons
        if is_valid:
            valid.add(render_id)

        axis = row.get("core_axis")
        source = axis.get("torso_source") if isinstance(axis, dict) else None
        trusted = False
        if is_valid and isinstance(axis, dict) and isinstance(source, str):
            is_override = source.startswith("override:")
            registry = bone_overrides if is_override else bone_semantics if source.startswith("semantic:") else {}
            for identity in sorted(consumer_keys.get(render_id, set())):
                spec = registry.get(identity, {}).get("upper_torso") if isinstance(registry, dict) else None
                if (
                    isinstance(spec, dict)
                    and spec.get("verified") is True
                    and spec.get("skeleton_sha256") == row.get("skeleton_sha256")
                    and isinstance(axis.get("torso_point"), list)
                    and len(axis["torso_point"]) == 2
                ):
                    trusted = True
                    break
        if trusted:
            trusted_core.add(render_id)
        statuses[render_id] = {
            "valid": is_valid,
            "trusted_semantic_core_axis": trusted,
            "anchor_kind": row.get("anchor_kind"),
            "core_axis_state": "available" if trusted else "unavailable",
            "reasons": sorted(reasons),
        }
    return {
        "records": records,
        "ids": set(records),
        "valid_ids": valid,
        "trusted_core_ids": trusted_core,
        "statuses": statuses,
    }


def audit(root: Path, snapshot: dict[str, Any], generated_from_head: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    defaults, costumes, unresolved = _consumer_rows(root)
    consumers = defaults + costumes
    consumer_ids = {str(row["render_id"]) for row in consumers if row.get("render_id") != "missing"}
    base_consumer_ids = {rid.split("@", 1)[0] for rid in consumer_ids}
    identity_mismatches: list[dict[str, Any]] = []
    # 逐项核对 CharacterMaster 声明的默认 render id 与生产 provider 的结果。
    rows = _read_json(root / "assets" / "data" / "character_master.json").get("characters", [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        resolved = next((x["render_id"] for x in defaults if x["resource_id"] == str(row.get("resource_id"))), "missing")
        declared = str(row.get("spine_asset_id") or "").strip().lower()
        if declared and declared != resolved:
            identity_mismatches.append(
                {"resource_id": str(row.get("resource_id")), "character_key": row.get("character_key"),
                 "master_render_id": declared, "provider_render_id": resolved}
            )

    upstream = _upstream_sets(snapshot)
    manifest_state = _manifest_state(root)
    manifest_ids = set(manifest_state["entries"])
    verified_manifest_ids = manifest_state["verified_ids"]
    anchors = _anchor_state(root, manifest_state, consumers)
    anchor_ids = anchors["ids"]
    trusted_core_ids = anchors["trusted_core_ids"]

    unsupported: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("spine_support_status") == "unsupported" and str(row.get("spine_support_reason", "")).strip():
            rid = str(row.get("spine_asset_id") or "").strip().lower()
            if rid:
                unsupported.add(rid)

    consumers_with_upstream = consumer_ids & upstream["complete_ids"]
    gaps = consumers_with_upstream - verified_manifest_ids - unsupported
    missing_manifest = consumers_with_upstream - manifest_ids
    unrepresented_upstream = upstream["render_ids"] - base_consumer_ids
    manifest_orphans = manifest_ids - consumer_ids
    undeclared_pngs = manifest_state["png_ids"] - manifest_ids
    manifest_no_anchor = manifest_ids - anchor_ids
    invalid_anchors = {rid for rid in anchor_ids if not anchors["statuses"].get(rid, {}).get("valid", False)}
    manifest_anchor_no_core = (manifest_ids & anchors["valid_ids"]) - trusted_core_ids
    no_portrait_or_unsupported = consumer_ids - verified_manifest_ids - unsupported
    consumers_by_render: dict[str, list[str]] = {}
    for consumer in consumers:
        render_id = str(consumer["render_id"])
        consumers_by_render.setdefault(render_id, []).append(str(consumer["identity"]))
    manual_review = [
        {
            "render_id": render_id,
            "consumers": sorted(consumers_by_render.get(render_id, [])),
            "reason": "upstream_bundle_available_but_no_verified_bundled_portrait; visual/source review required",
        }
        for render_id in sorted(gaps)
    ]

    c018_consumer = next((row for row in defaults if row["resource_id"] == "18"), None)
    c018_entry = manifest_state["entries"].get("c018", {})
    c018_anchor = anchors["records"].get("c018", {})
    c018_png_status = manifest_state["statuses"].get("c018", {})
    c018 = {
        "resource_id": 18,
        "character_key": c018_consumer.get("character_key") if c018_consumer else None,
        "render_id": c018_consumer.get("render_id") if c018_consumer else None,
        "upstream_l2d_available": "c018" in upstream["render_ids"],
        "upstream_bundle_complete": "c018" in upstream["complete_ids"],
        "fb_available": "c018" in upstream["fb_ids"] if upstream["fb_known"] else None,
        "runtime_version": c018_entry.get("runtime_version"),
        "skeleton_runtime": c018_anchor.get("runtime"),
        "png_path": c018_png_status.get("local_relpath"),
        "portrait_source": "verified_bundled_manifest" if c018_png_status.get("valid") else "unavailable",
        "manifest_source": (
            manifest_state["store"].source.relative_to(root).as_posix()
            if manifest_state["store"].source is not None
            else None
        ),
        "png_verified": c018_png_status.get("valid", False),
        "png_sha256": c018_png_status.get("sha256"),
        "rgba_pixel_sha256": c018_png_status.get("rgba_pixel_sha256"),
        "dimensions": c018_png_status.get("dimensions"),
        "alpha_bbox": c018_png_status.get("alpha_bbox"),
        "manifest_declared": "c018" in manifest_ids,
        "face_anchor_state": (
            "anchor_available_head_only"
            if anchors["statuses"].get("c018", {}).get("valid")
            and not anchors["statuses"].get("c018", {}).get("trusted_semantic_core_axis")
            else "invalid_or_unavailable"
        ),
        "face_anchor_point": c018_anchor.get("point"),
        "face_anchor_kind": c018_anchor.get("anchor_kind"),
        "face_anchor_crop_transform": c018_anchor.get("png_transform"),
        "framing_source": c018_anchor.get("anchor_kind"),
        "core_axis": "available" if "c018" in trusted_core_ids else "unavailable",
        "core_axis_reason": c018_anchor.get("core_axis_reason"),
    }

    lists = {
        "canonical_default_consumers": defaults,
        "verified_costume_consumers": costumes,
        "unresolved_character_identities": unresolved,
        "character_master_identity_mismatches": sorted(identity_mismatches, key=lambda row: row["resource_id"]),
        "character_default_render_ids_with_upstream_l2d": sorted(
            {row["render_id"] for row in defaults} & upstream["render_ids"]
        ),
        "canonical_render_consumers_with_upstream_l2d": sorted(consumer_ids & upstream["render_ids"]),
        "upstream_l2d_render_ids": sorted(upstream["render_ids"]),
        "upstream_l2d_incomplete_bundle_ids": sorted(upstream["incomplete_ids"]),
        "upstream_fb_render_ids": sorted(upstream["fb_ids"]),
        "upstream_exists_manifest_missing": sorted(missing_manifest),
        "manifest_without_current_character_consumer": sorted(manifest_orphans),
        "manifest_png_missing_or_invalid": [
            manifest_state["statuses"][rid]
            for rid in sorted(manifest_ids)
            if not manifest_state["statuses"].get(rid, {}).get("valid", False)
        ],
        "bundled_png_not_declared_by_manifest": sorted(undeclared_pngs),
        "face_anchor_render_ids": sorted(anchor_ids),
        "face_anchor_identity_invalid": sorted(invalid_anchors),
        "manifest_without_face_anchor": sorted(manifest_no_anchor),
        "manifest_face_anchor_without_trusted_semantic_core_axis": sorted(manifest_anchor_no_core),
        "trusted_semantic_core_axis_render_ids": sorted(trusted_core_ids),
        "character_render_without_verified_portrait_or_unsupported": sorted(no_portrait_or_unsupported),
        "render_asset_gap": sorted(gaps),
        "manual_review_required": manual_review,
        "unsupported": sorted(unsupported),
        "upstream_l2d_not_represented_by_current_character_data": sorted(unrepresented_upstream),
    }
    counts = {
        "character_resources": len({row["resource_id"] for row in defaults}),
        "canonical_render_consumers": len(consumers),
        "canonical_unique_render_ids": len(consumer_ids),
        "upstream_l2d_render_ids": len(upstream["render_ids"]),
        "upstream_l2d_complete_bundles": len(upstream["complete_ids"]),
        "manifest_render_ids": len(manifest_ids),
        "bundled_png_render_ids": len(manifest_state["png_ids"]),
        "verified_manifest_png_render_ids": len(verified_manifest_ids),
        "face_anchor_render_ids": len(anchor_ids),
        "valid_face_anchor_render_ids": len(anchors["valid_ids"]),
        "trusted_semantic_core_axis_render_ids": len(trusted_core_ids),
        "character_default_render_ids_with_upstream_l2d": len(lists["character_default_render_ids_with_upstream_l2d"]),
        "canonical_render_consumers_with_upstream_l2d": len(consumers_with_upstream),
        "upstream_exists_manifest_missing": len(missing_manifest),
        "manifest_without_current_character_consumer": len(manifest_orphans),
        "manifest_png_missing_or_invalid": len(lists["manifest_png_missing_or_invalid"]),
        "bundled_png_not_declared_by_manifest": len(undeclared_pngs),
        "manifest_without_face_anchor": len(manifest_no_anchor),
        "manifest_face_anchor_without_trusted_semantic_core_axis": len(manifest_anchor_no_core),
        "character_render_without_verified_portrait_or_unsupported": len(no_portrait_or_unsupported),
        "render_asset_gap": len(gaps),
        "manual_review_required": len(manual_review),
        "unsupported": len(unsupported),
        "upstream_l2d_not_represented_by_current_character_data": len(unrepresented_upstream),
        "unresolved_character_identities": len(unresolved),
        "character_master_identity_mismatches": len(identity_mismatches),
    }
    definitions = {
        "character_resources": "assets/data/character_master.json 中唯一 resource_id 的角色数。",
        "canonical_render_consumers": "默认角色身份加上由当前 NikkeDbProvider 校验并解析成功的 Costume 身份。",
        "upstream_l2d_render_ids": "固定 upstream snapshot 中出现 l2d/<render_id>/ 文件的唯一目录 ID。",
        "upstream_l2d_complete_bundles": "目录根部至少有一个 .skel、.atlas、.png；不要求纹理 basename 与 skeleton 相同，因为 upstream Costume 可能复用改名纹理。",
        "manifest_orphan": "manifest render_id 不被任何当前默认角色或已验证 Costume 的生产 resolver 消费；Costume/alternate render identity 不会仅因不等于默认 ID 被判 orphan。",
        "missing_manifest": "当前生产 resolver 可解析且 upstream bundle 完整的 render_id 未在 manifest 声明；不包含 upstream 不完整或 identity 未解析的项目。",
        "render_asset_gap": "生产 resolver 可解析、snapshot 存在完整 upstream bundle，但没有完整性通过的 manifest PNG，且没有显式 unsupported 分类的 render_id。",
        "manual_review_required": "每个 Render Asset Gap 的 production identity 消费者与原因，需人工视觉/来源复核；未进行自动图像生成、Face Anchor 推测或 Core Axis 推测。",
        "unsupported": "仅统计 CharacterMaster 明确标记 spine_support_status=unsupported 且提供 spine_support_reason 的默认角色；当前无此类记录。",
        "character_render_without_verified_portrait_or_unsupported": "生产 resolver 可解析但无完整性通过的 manifest PNG，且无显式 unsupported 分类的唯一 render_id。",
        "bundled_png_not_declared_by_manifest": "assets/spine-rendered/ 中的 PNG render_id 不在当前 manifest 声明集合中；这些文件不因此成为生产可信资源。",
        "trusted_semantic_core_axis": "Face Anchor 与 PNG raw/pixel hash、尺寸均相符，并且 semantic/override registry 对该身份标记 verified 且 skeleton SHA 与 anchor 一致。",
        "upstream_l2d_not_represented_by_current_character_data": "upstream L2D render_id 未被当前 canonical 默认 Character identity 表示；Costume render variants 单独统计为消费者，不改变此默认角色覆盖指标。",
    }
    return {
        "schema_version": 2,
        "generated_from_head": generated_from_head or _git_head(root),
        "source": {
            "repository": snapshot.get("source_repo", SOURCE_REPO),
            "ref": snapshot.get("ref", "main"),
            "commit_sha": snapshot.get("commit_sha"),
            "snapshot_schema_version": snapshot.get("schema_version"),
            "fb_inventory_known": upstream["fb_known"],
        },
        "definitions": definitions,
        "summary": counts,
        "sets": lists,
        "manifest_status": manifest_state["statuses"],
        "face_anchor_status": anchors["statuses"],
        "c018": c018,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    c018 = report["c018"]
    lines = [
        "# Post-Refactor Spine Resource Coverage Audit",
        "",
        f"- Generated from HEAD: `{report['generated_from_head']}`",
        f"- Nikke-db snapshot commit: `{report['source']['commit_sha']}`",
        f"- Character resources / render consumers: `{summary['character_resources']}` / `{summary['canonical_render_consumers']}`",
        f"- Upstream L2D IDs / complete root bundles: `{summary['upstream_l2d_render_ids']}` / `{summary['upstream_l2d_complete_bundles']}`",
        f"- Manifest / bundled PNG / valid manifest PNG: `{summary['manifest_render_ids']}` / `{summary['bundled_png_render_ids']}` / `{summary['verified_manifest_png_render_ids']}`",
        f"- Face Anchors / valid identities / trusted semantic Core Axis: `{summary['face_anchor_render_ids']}` / `{summary['valid_face_anchor_render_ids']}` / `{summary['trusted_semantic_core_axis_render_ids']}`",
        f"- Missing manifest / orphan / invalid PNG / undeclared PNG: `{summary['upstream_exists_manifest_missing']}` / `{summary['manifest_without_current_character_consumer']}` / `{summary['manifest_png_missing_or_invalid']}` / `{summary['bundled_png_not_declared_by_manifest']}`",
        f"- Render Asset Gap / unsupported: `{summary['render_asset_gap']}` / `{summary['unsupported']}`",
        f"- Manual visual/source review required: `{summary['manual_review_required']}`",
        "",
        "## Definitions",
        "",
        f"- Missing Manifest: {report['definitions']['missing_manifest']}",
        f"- Orphan Manifest: {report['definitions']['manifest_orphan']}",
        f"- Render Asset Gap: {report['definitions']['render_asset_gap']}",
        f"- Manual Review: {report['definitions']['manual_review_required']}",
        f"- Unsupported: {report['definitions']['unsupported']}",
        "",
        "## c018",
        "",
        f"- `resource_id={c018['resource_id']} → {c018['render_id']}`; upstream L2D `{c018['upstream_l2d_available']}`, FB `{c018['fb_available']}`.",
        f"- Spine runtime `{c018['runtime_version']}` (skeleton evidence `{c018['skeleton_runtime']}`); verified PNG `{c018['png_verified']}` at `{c018['dimensions']}`.",
        f"- Face Anchor `{c018['face_anchor_state']}`; Core Axis `{c018['core_axis']}` (`{c018['core_axis_reason']}`).",
    ]
    return "\n".join(lines) + "\n"


def build_c018_diagnostic(report: dict[str, Any], preview_path: Path) -> dict[str, Any]:
    c018 = report["c018"]
    with Image.open(preview_path) as image:
        image.verify()
    with Image.open(preview_path) as image:
        preview_dimensions = list(image.size)
    return {
        "schema_version": 1,
        "generated_from_head": report["generated_from_head"],
        "resource_id": c018["resource_id"],
        "render_id": c018["render_id"],
        "portrait_source": c018["portrait_source"],
        "manifest_source": c018["manifest_source"],
        "runtime_version": c018["runtime_version"],
        "skeleton_runtime": c018["skeleton_runtime"],
        "portrait_sha256": c018["png_sha256"],
        "portrait_rgba_pixel_sha256": c018["rgba_pixel_sha256"],
        "portrait_dimensions": c018["dimensions"],
        "portrait_alpha_bbox": c018["alpha_bbox"],
        "face_anchor_state": c018["face_anchor_state"],
        "face_anchor_point": c018["face_anchor_point"],
        "face_anchor_crop_transform": c018["face_anchor_crop_transform"],
        "framing_source": c018["framing_source"],
        "core_axis": c018["core_axis"],
        "core_axis_reason": c018["core_axis_reason"],
        "character_card": {
            "template": "templates/t2i/character.html",
            "canvas": [1600, 2400],
            "preview_file": preview_path.name,
            "preview_sha256": _file_sha256(preview_path),
            "preview_dimensions": preview_dimensions,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--upstream-snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, required=True, help="确定性 JSON 输出路径")
    parser.add_argument("--markdown-output", type=Path, help="可选 Markdown 摘要路径")
    parser.add_argument("--character-card-preview", type=Path, help="已由生产 T2I renderer 生成的 c018 白卡 PNG")
    parser.add_argument("--diagnostic-output", type=Path, help="可选 c018 白卡 JSON 诊断路径，需同时提供 preview")
    parser.add_argument("--refresh-upstream", action="store_true", help="显式访问 Nikke-db GitHub API 并刷新本地快照")
    args = parser.parse_args()
    if (args.character_card_preview is None) != (args.diagnostic_output is None):
        parser.error("--character-card-preview 与 --diagnostic-output 必须同时提供")
    repo_root = args.repo_root.resolve()
    snapshot_path = args.upstream_snapshot
    if not snapshot_path.is_absolute():
        snapshot_path = repo_root / snapshot_path
    if args.refresh_upstream:
        snapshot = fetch_upstream_snapshot()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        snapshot = _read_json(snapshot_path)
    report = audit(repo_root, snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    if args.diagnostic_output is not None:
        preview_path = args.character_card_preview.resolve()
        if not preview_path.is_file():
            raise FileNotFoundError(f"c018 白卡 preview 不存在: {preview_path.name}")
        if not report["c018"]["png_verified"]:
            raise ValueError("c018 manifest PNG 未通过完整性验证，拒绝生成卡片 diagnostic")
        if report["c018"]["face_anchor_state"] != "anchor_available_head_only":
            raise ValueError("c018 Face Anchor 不可用或状态不符，拒绝生成卡片 diagnostic")
        diagnostic = build_c018_diagnostic(report, preview_path)
        args.diagnostic_output.parent.mkdir(parents=True, exist_ok=True)
        args.diagnostic_output.write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
