#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""离线审计 canonical Character、Nikke-db Spine、manifest、PNG 与 framing 元数据。

默认只读仓库内的 upstream 快照。只有显式传入 ``--refresh-upstream`` 才会访问
GitHub API 并更新快照；审计本身不下载或修改任何角色资源。
"""

from __future__ import annotations

import argparse
import ast
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
SOURCE_VERIFICATION = Path("docs/evidence/spine_resource_coverage_phase2/render-source-verification.json")
CENTERING_EVIDENCE_SCRIPT = Path("scripts/generate_centering_evidence.py")
CENTERING_EVIDENCE_DOC = Path("docs/face_guided_body_centering.md")

UNDECLARED_PNG_CATEGORIES = (
    "VERIFIED_MANIFEST_CANDIDATE",
    "VALID_VARIANT_NEEDS_REVIEW",
    "HISTORICAL_OR_TEST_ONLY",
    "STALE_OR_ORPHAN_FILE",
    "INVALID_ASSET",
)


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


def _centering_sample_specs(root: Path) -> dict[str, dict[str, Any]]:
    """从离线研究脚本读取真实立绘样本身份，不导入其渲染依赖。"""
    script = root / CENTERING_EVIDENCE_SCRIPT
    if not script.is_file():
        return {}
    module = ast.parse(script.read_text(encoding="utf-8"), filename=str(CENTERING_EVIDENCE_SCRIPT))
    for node in module.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None or not any(isinstance(target, ast.Name) and target.id == "SAMPLE_SPECS" for target in targets):
            continue
        try:
            specs = ast.literal_eval(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("SAMPLE_SPECS 必须保持为可静态解析的离线数据") from exc
        if not isinstance(specs, list):
            raise ValueError("SAMPLE_SPECS 必须是数组")
        result: dict[str, dict[str, Any]] = {}
        for spec in specs:
            if not isinstance(spec, dict) or not isinstance(spec.get("render_id"), str):
                raise ValueError("SAMPLE_SPECS 含无效 render_id")
            render_id = spec["render_id"]
            if render_id in result:
                raise ValueError(f"SAMPLE_SPECS render_id 重复: {render_id}")
            result[render_id] = spec
        return result
    return {}


def _centering_evidence_is_nonproduction(root: Path) -> bool:
    """只有文档仍声明 opt-in/default-off 时才按研究样本归档。"""
    document = root / CENTERING_EVIDENCE_DOC
    if not document.is_file():
        return False
    content = document.read_text(encoding="utf-8")
    return "Opt-in Preview" in content and "严格 OFF" in content


def _generation_record_valid(
    render_id: str,
    anchor: dict[str, Any],
    image_sha: str | None,
    pixel_sha: str | None,
    dimensions: list[int] | None,
) -> bool:
    """校验 Face Anchor 中同次生成记录绑定的输入、输出及渲染参数。"""
    transform = anchor.get("png_transform")
    runtime = anchor.get("runtime")
    if not isinstance(transform, dict):
        return False
    render_size = transform.get("render_size")
    crop_box = transform.get("alpha_bbox")
    crop_padding = transform.get("crop_padding")
    return all(
        (
            anchor.get("render_id") == render_id,
            isinstance(anchor.get("skeleton_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", anchor["skeleton_sha256"]) is not None,
            isinstance(anchor.get("atlas_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", anchor["atlas_sha256"]) is not None,
            runtime in {"4.0.47", "4.1.20"},
            anchor.get("animation") == "idle",
            anchor.get("time") == 0,
            isinstance(anchor.get("png_sha256"), str) and anchor.get("png_sha256") == image_sha,
            isinstance(anchor.get("pixel_sha256"), str) and anchor.get("pixel_sha256") == pixel_sha,
            isinstance(anchor.get("image_size"), list) and anchor.get("image_size") == dimensions,
            isinstance(render_size, list)
            and len(render_size) == 2
            and all(isinstance(value, int) and value > 0 for value in render_size),
            isinstance(crop_box, list)
            and len(crop_box) == 4
            and all(isinstance(value, int) for value in crop_box)
            and crop_box[0] < crop_box[2]
            and crop_box[1] < crop_box[3],
            isinstance(crop_padding, int) and crop_padding >= 0,
        )
    )


def _pinned_source_matches_generation(
    source_verification: dict[str, Any],
    snapshot: dict[str, Any],
    render_id: str,
    anchor: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """确认生成输入 SHA-256 与固定 upstream tree 的字节证据一致。"""
    record = source_verification.get("records", {}).get(render_id)
    if not isinstance(record, dict):
        return False, {}
    commit_matches = (
        source_verification.get("upstream_commit_sha") == snapshot.get("commit_sha")
        and record.get("pinned_bundle_complete") is True
    )
    skeleton = record.get("skeleton") if isinstance(record.get("skeleton"), dict) else {}
    atlas = record.get("atlas") if isinstance(record.get("atlas"), dict) else {}
    matches = all(
        (
            commit_matches,
            record.get("generation_inputs_match_pinned_snapshot") is True,
            skeleton.get("matches_snapshot") is True,
            atlas.get("matches_snapshot") is True,
            skeleton.get("matches_generation_record") is True,
            atlas.get("matches_generation_record") is True,
            skeleton.get("sha256") == anchor.get("skeleton_sha256"),
            atlas.get("sha256") == anchor.get("atlas_sha256"),
            all(page.get("present_in_snapshot") is True for page in atlas.get("pages", [])),
        )
    )
    return matches, record


def classify_undeclared_png(
    *,
    image_valid: bool,
    anchor_present: bool,
    anchor_valid: bool,
    consumers: list[dict[str, Any]],
    upstream_bundle_complete: bool,
    centering_sample: bool,
    generation_record_valid: bool = False,
    pinned_source_matches: bool = False,
) -> tuple[str, str]:
    """按互斥优先级分类；候选状态不等同于 manifest 批准。"""
    if not image_valid or (anchor_present and not anchor_valid):
        return "INVALID_ASSET", "PNG 无法解码/没有可见 alpha，或已有 Face Anchor 与当前 PNG 身份不匹配。"
    if not consumers or not upstream_bundle_complete:
        return "STALE_OR_ORPHAN_FILE", "缺少当前 canonical Character/Costume consumer，或固定 upstream snapshot 中没有完整 L2D bundle。"
    if not any(row.get("kind") == "default" for row in consumers):
        return "VALID_VARIANT_NEEDS_REVIEW", "资源只由已验证的 Costume/alternate consumer 使用；需人工确认 variant 身份与视觉对应关系。"
    if generation_record_valid and not pinned_source_matches:
        return "INVALID_ASSET", "Face Anchor 所记录的生成输入与固定 upstream skeleton/atlas 字节不一致；拒绝提升到 manifest。"
    if generation_record_valid and pinned_source_matches:
        return (
            "VERIFIED_MANIFEST_CANDIDATE",
            "canonical identity、固定 upstream bundle、生成输入/输出 SHA-256、运行时与渲染参数均核验通过；仍需按 manifest 流程显式登记，不自动提升。",
        )
    if centering_sample:
        return (
            "HISTORICAL_OR_TEST_ONLY",
            "该 PNG 仅有离线 face-guided centering 研究用途，缺少可核验的同次生成记录；不进入生产 manifest。",
        )
    return "INVALID_ASSET", "缺少可核验的同次生成输入/输出记录，PNG 来源 provenance 不足以进入 manifest。"


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
            statuses[render_id] = {
                "valid": False,
                "trusted_semantic_core_axis": False,
                "image_decoded": False,
                "reason": "invalid_anchor_record",
            }
            continue
        path = manifest_state["paths"].get(render_id)
        if path is None:
            path = assets / "spine-rendered" / f"{render_id}.png"
        reasons: list[str] = []
        raw_sha = None
        rgba_sha = None
        dimensions = None
        alpha_bbox = None
        if path.is_file():
            try:
                raw_sha = _file_sha256(path)
                with Image.open(path) as opened:
                    rgba = opened.convert("RGBA")
                    dimensions = list(rgba.size)
                    rgba_sha = hashlib.sha256(rgba.tobytes()).hexdigest()
                    bbox = rgba.getchannel("A").getbbox()
                    alpha_bbox = list(bbox) if bbox else None
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
            "image_decoded": dimensions is not None and alpha_bbox is not None,
            "png_sha256": raw_sha,
            "rgba_pixel_sha256": rgba_sha,
            "image_size": dimensions,
            "alpha_bbox": alpha_bbox,
            "anchor_kind": row.get("anchor_kind"),
            "point": row.get("point"),
            "runtime": row.get("runtime"),
            "skeleton_sha256": row.get("skeleton_sha256"),
            "core_axis_reason": row.get("core_axis_reason"),
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


def _build_undeclared_png_audit(
    root: Path,
    snapshot: dict[str, Any],
    upstream: dict[str, Any],
    defaults: list[dict[str, Any]],
    costumes: list[dict[str, Any]],
    manifest_state: dict[str, Any],
    anchors: dict[str, Any],
    generated_from_head: str,
) -> dict[str, Any]:
    """为现存未声明 PNG 生成可重复、fail-closed 的逐项审计。"""
    sample_specs = _centering_sample_specs(root)
    centering_is_nonproduction = _centering_evidence_is_nonproduction(root)
    source_verification_path = root / SOURCE_VERIFICATION
    source_verification = (
        _read_json(source_verification_path) if source_verification_path.is_file() else {}
    )
    consumers_by_render: dict[str, list[dict[str, Any]]] = {}
    for consumer in defaults + costumes:
        consumers_by_render.setdefault(str(consumer["render_id"]), []).append(consumer)

    source_files_by_render: dict[str, list[dict[str, Any]]] = {}
    l2d_files = snapshot.get("l2d_files", snapshot.get("files", []))
    for item in l2d_files if isinstance(l2d_files, list) else []:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str):
            continue
        match = L2D_PATH_RE.fullmatch(path)
        if match is None:
            continue
        render_id, relative = match.groups()
        if "/" in relative:
            continue
        source_files_by_render.setdefault(render_id, []).append(
            {"path": path, "git_blob_sha1": item.get("sha"), "size": item.get("size")}
        )
    for source_files in source_files_by_render.values():
        source_files.sort(key=lambda row: row["path"])

    records: list[dict[str, Any]] = []
    category_ids = {category: [] for category in UNDECLARED_PNG_CATEGORIES}
    assets = root / "assets"
    for render_id in sorted(manifest_state["png_ids"] - set(manifest_state["entries"])):
        image_path = assets / "spine-rendered" / f"{render_id}.png"
        anchor_record = anchors["records"].get(render_id)
        anchor_status = anchors["statuses"].get(render_id, {})
        anchor_present = isinstance(anchor_record, dict)
        image_sha = anchor_status.get("png_sha256")
        pixel_sha = anchor_status.get("rgba_pixel_sha256")
        dimensions = anchor_status.get("image_size")
        alpha_bbox = anchor_status.get("alpha_bbox")
        image_decoded = bool(anchor_status.get("image_decoded", False))

        # 没有 anchor 的图片仍要独立做 PNG 完整性检查，不能因此跳过审计。
        if not anchor_present:
            try:
                image_sha = _file_sha256(image_path)
                with Image.open(image_path) as opened:
                    opened.load()
                    rgba = opened.convert("RGBA")
                    dimensions = list(rgba.size)
                    pixel_sha = hashlib.sha256(rgba.tobytes()).hexdigest()
                    bbox = rgba.getchannel("A").getbbox()
                    alpha_bbox = list(bbox) if bbox else None
                image_decoded = dimensions is not None and alpha_bbox is not None
            except (OSError, ValueError):
                image_decoded = False

        consumers = sorted(
            consumers_by_render.get(render_id, []),
            key=lambda row: (row.get("identity", ""), row.get("kind", "")),
        )
        anchor_valid = bool(anchor_status.get("valid", False)) if anchor_present else False
        png_valid = bool(image_decoded and image_sha and pixel_sha and dimensions and alpha_bbox)
        anchor = anchor_record if anchor_present else {}
        generation_record_valid = _generation_record_valid(
            render_id,
            anchor,
            image_sha,
            pixel_sha,
            dimensions,
        ) if anchor_present else False
        pinned_source_matches, pinned_source_record = _pinned_source_matches_generation(
            source_verification,
            snapshot,
            render_id,
            anchor,
        ) if anchor_present else (False, {})
        category, reason = classify_undeclared_png(
            image_valid=png_valid,
            anchor_present=anchor_present,
            anchor_valid=anchor_valid,
            consumers=consumers,
            upstream_bundle_complete=render_id in upstream["complete_ids"],
            centering_sample=render_id in sample_specs and centering_is_nonproduction,
            generation_record_valid=generation_record_valid,
            pinned_source_matches=pinned_source_matches,
        )
        category_ids[category].append(render_id)

        sample = sample_specs.get(render_id)
        source_files = source_files_by_render.get(render_id, [])
        trusted_core = bool(anchor_status.get("trusted_semantic_core_axis", False))
        upstream_bundle_complete = render_id in upstream["complete_ids"]
        records.append(
            {
                "render_id": render_id,
                "classification": category,
                "classification_reason": reason,
                "identity_chain": {
                    "consumers": consumers,
                    "canonical_resource_ids": sorted({str(row["resource_id"]) for row in consumers}),
                    "character_keys": sorted({str(row["character_key"]) for row in consumers if row.get("character_key")}),
                    "default_character_consumer": any(row.get("kind") == "default" for row in consumers),
                    "costume_consumer": any(row.get("kind") == "verified_costume" for row in consumers),
                },
                "upstream": {
                    "repository": snapshot.get("source_repo", SOURCE_REPO),
                    "ref": snapshot.get("ref", "main"),
                    "snapshot_commit_sha": snapshot.get("commit_sha"),
                    "l2d_directory_present": render_id in upstream["render_ids"],
                    "complete_root_bundle": upstream_bundle_complete,
                    "root_files": source_files,
                },
                "bundled_png": {
                    "path": f"assets/spine-rendered/{render_id}.png",
                    "manifest_declared": False,
                    "manifest_trusted": False,
                    "decode_valid": png_valid,
                    "sha256": image_sha,
                    "rgba_pixel_sha256": pixel_sha,
                    "dimensions": dimensions,
                    "alpha_bbox": alpha_bbox,
                    "file_size": image_path.stat().st_size if image_path.is_file() else None,
                },
                "source_provenance": {
                    "state": (
                        "verified_against_pinned_bundle"
                        if generation_record_valid and pinned_source_matches
                        else "generation_source_mismatch"
                        if generation_record_valid and pinned_source_record
                        else "generation_record_incomplete"
                    ),
                    "generation_record_valid": generation_record_valid,
                    "generation_record_source": (
                        f"assets/data/face_anchors.json#records.{render_id}" if anchor_present else None
                    ),
                    "generation_script": (
                        "scripts/batch_prepare_samples.py" if generation_record_valid else None
                    ),
                    "skeleton_runtime_metadata": anchor.get("runtime") if anchor_present else None,
                    "runtime_metadata_source": (
                        f"assets/data/face_anchors.json#records.{render_id}.runtime" if anchor_present else None
                    ),
                    "skeleton_sha256_metadata": anchor.get("skeleton_sha256") if anchor_present else None,
                    "atlas_sha256_metadata": anchor.get("atlas_sha256") if anchor_present else None,
                    "pinned_upstream_commit": snapshot.get("commit_sha"),
                    "pinned_source_verification_file": (
                        SOURCE_VERIFICATION.as_posix() if pinned_source_record else None
                    ),
                    "pinned_source_bundle_complete": pinned_source_record.get("pinned_bundle_complete", False),
                    "generation_inputs_match_pinned_bundle": pinned_source_matches,
                    "source_bundle_sha256_bound_to_render": generation_record_valid and pinned_source_matches,
                    "renderer_build_digest_recorded": False,
                    "animation": anchor.get("animation") if anchor_present else None,
                    "time": anchor.get("time") if anchor_present else None,
                    "render_transform": anchor.get("png_transform") if anchor_present else None,
                    "limitation": "生成记录包含 skeleton/atlas 与输出 SHA-256、精确 runtime patch、animation/time 和裁切变换；没有单独记录 renderer 二进制 digest。候选判断不自动改变 manifest 信任边界。",
                },
                "face_anchor": {
                    "present": anchor_present,
                    "identity_valid": anchor_valid,
                    "anchor_kind": anchor.get("anchor_kind") if anchor_present else None,
                    "point": anchor.get("point") if anchor_present else None,
                    "png_sha256_matches": bool(anchor_present and anchor.get("png_sha256") == image_sha),
                    "rgba_pixel_sha256_matches": bool(anchor_present and anchor.get("pixel_sha256") == pixel_sha),
                    "dimensions_match": bool(anchor_present and anchor.get("image_size") == dimensions),
                    "trusted_semantic_core_axis": trusted_core,
                    "core_axis_state": "available" if trusted_core else "unavailable",
                    "core_axis_reason": (
                        anchor.get("core_axis_reason")
                        or (None if trusted_core else "no_verified_semantic_or_override_binding_for_consumer")
                    ),
                },
                "evidence_usage": {
                    "centering_sample": sample is not None and centering_is_nonproduction,
                    "sample_spec_present": sample is not None,
                    "sample_category_code": sample.get("category_code") if sample else None,
                    "sample_category": sample.get("category") if sample else None,
                    "script": str(CENTERING_EVIDENCE_SCRIPT.as_posix()) if sample else None,
                    "scope_document": str(CENTERING_EVIDENCE_DOC.as_posix()) if sample else None,
                    "scope_status": "Opt-in Preview / Default OFF" if sample and centering_is_nonproduction else None,
                },
                "production_eligibility": {
                    "accepted_by_manifest_trust_boundary": False,
                    "automatic_manifest_promotion": False,
                    "unsupported_classification": False,
                },
            }
        )

    all_ids = sorted(manifest_state["png_ids"] - set(manifest_state["entries"]))
    classified_ids = [render_id for values in category_ids.values() for render_id in values]
    if sorted(classified_ids) != all_ids or len(classified_ids) != len(set(classified_ids)):
        raise ValueError("未声明 PNG 分类必须互斥且完整覆盖当前文件集合")

    return {
        "schema_version": 1,
        "generated_from_head": generated_from_head,
        "definitions": {
            "VERIFIED_MANIFEST_CANDIDATE": "机械 identity/upstream/image 检查满足候选条件；必须另行人工确认 source-to-render provenance、视觉与 framing，且本分类不会自动加入 manifest。",
            "VALID_VARIANT_NEEDS_REVIEW": "仅被当前 canonical Costume/alternate consumer 使用的有效 PNG；仍需人工确认角色与 variant 对应关系。",
            "HISTORICAL_OR_TEST_ONLY": "仅用于已文档化的研究、preview 或测试样本，不作为生产 bundled portrait。",
            "STALE_OR_ORPHAN_FILE": "缺少当前 canonical consumer 或固定 upstream snapshot 中没有完整 L2D bundle。",
            "INVALID_ASSET": "PNG 不可解码/没有可见 alpha，或已有 Face Anchor 与 PNG raw hash、RGBA hash、尺寸不匹配。",
        },
        "scope": {
            "classification_is_production_authorization": False,
            "manifest_trust_boundary_changed": False,
            "automatic_asset_download_or_promotion": False,
        },
        "source": {
            "repository": snapshot.get("source_repo", SOURCE_REPO),
            "ref": snapshot.get("ref", "main"),
            "commit_sha": snapshot.get("commit_sha"),
            "snapshot_schema_version": snapshot.get("schema_version"),
        },
        "summary": {
            "undeclared_png_count": len(all_ids),
            "classification_counts": {category: len(category_ids[category]) for category in UNDECLARED_PNG_CATEGORIES},
        },
        "classification_sets": {category: sorted(category_ids[category]) for category in UNDECLARED_PNG_CATEGORIES},
        "records": records,
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
    audit_head = generated_from_head or _git_head(root)
    undeclared_png_audit = _build_undeclared_png_audit(
        root,
        snapshot,
        upstream,
        defaults,
        costumes,
        manifest_state,
        anchors,
        audit_head,
    )
    return {
        "schema_version": 2,
        "generated_from_head": audit_head,
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
        "undeclared_png_audit": undeclared_png_audit,
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
        f"- Undeclared PNG review categories: `{report['undeclared_png_audit']['summary']['classification_counts']}`",
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
    parser.add_argument("--undeclared-png-output", type=Path, help="可选的逐 PNG 分类审计 JSON 路径")
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
    if args.undeclared_png_output is not None:
        args.undeclared_png_output.parent.mkdir(parents=True, exist_ok=True)
        args.undeclared_png_output.write_text(
            json.dumps(report["undeclared_png_audit"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
