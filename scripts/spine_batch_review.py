#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""校验 Spine 候选批次、生成待人工复核清单与新版白卡 contact sheet。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFile, ImageFont
from scripts.phase3_output_guard import require_new_external_path

from scripts.spine_batch_validation import (
    BatchValidationError,
    VISUAL_METRICS,
    analyze_png,
    score_visual_metrics,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_ID_RE = re.compile(r"^c[0-9]+$", re.ASCII)
if str(REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT.parent))
from astrbot_plugin_nikke.integrations.spine.local_resolver import (
    LocalSpineBundleResolver,
    LocalSpineResolveError,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _inside(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError(f"{label} 路径缺失")
    base = root.resolve(strict=True)
    target = (base / relative).resolve(strict=True)
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError(f"{label} 路径越界或不存在")
    return target


def validate_candidate_render(
    candidate: dict[str, Any],
    fetch_provenance: dict[str, Any],
    render_manifest: dict[str, Any],
    *,
    bundle_root: Path,
    render_root: Path,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """重新核验固定输入 bundle、生产渲染清单和输出 PNG，再计算校准异常分。"""
    render_id = candidate.get("render_id") if isinstance(candidate, dict) else None
    failures: list[str] = []
    metrics: dict[str, Any] | None = None
    visual: dict[str, Any] | None = None
    png_sha: str | None = None
    dimensions: list[int] | None = None
    relative_png: str | None = None
    runtime_version: str | None = None
    fetch_bundle: dict[str, Any] = {}
    render_entry: dict[str, Any] = {}

    if not isinstance(render_id, str) or not RENDER_ID_RE.fullmatch(render_id):
        failures.append("invalid_default_render_id")
        render_id = str(render_id)
    if candidate.get("consumer_type") != "default_character" or candidate.get("costume_id") is not None:
        failures.append("non_default_candidate_rejected")
    if not isinstance(candidate.get("resource_id"), str) or not str(candidate.get("resource_id", "")).isdigit():
        failures.append("canonical_resource_identity_missing")
    elif RENDER_ID_RE.fullmatch(render_id) and int(render_id[1:]) != int(candidate["resource_id"]):
        failures.append("canonical_resource_identity_mismatch")

    fetch_ids = fetch_provenance.get("render_ids") if isinstance(fetch_provenance, dict) else None
    if not isinstance(fetch_ids, list) or render_id not in fetch_ids:
        failures.append("candidate_missing_from_fetch_provenance")
    source_commit = fetch_provenance.get("source_commit") if isinstance(fetch_provenance, dict) else None
    if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        failures.append("invalid_upstream_commit")
    if fetch_provenance.get("upstream_snapshot_sha") != source_commit:
        failures.append("upstream_snapshot_commit_mismatch")

    bundles = fetch_provenance.get("bundles", [])
    fetch_bundle = next(
        (row for row in bundles if isinstance(row, dict) and row.get("render_id") == render_id), {}
    ) if isinstance(bundles, list) else {}
    file_rows = fetch_provenance.get("files", [])
    source_files = {
        row.get("path"): row
        for row in file_rows
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    } if isinstance(file_rows, list) else {}
    textures = fetch_bundle.get("texture_paths", [])
    if not isinstance(textures, list):
        textures = []
        failures.append("fetch_texture_paths_invalid")
    expected_source_paths = [
        fetch_bundle.get("skeleton_path"),
        fetch_bundle.get("atlas_path"),
        *textures,
    ]
    if not fetch_bundle or not expected_source_paths or any(not isinstance(path, str) for path in expected_source_paths):
        failures.append("fetch_bundle_provenance_missing")
    else:
        for relative in expected_source_paths:
            row = source_files.get(relative)
            if not isinstance(row, dict):
                failures.append("source_file_missing_from_provenance")
                continue
            try:
                path = _inside(bundle_root, relative, "固定 bundle")
                if (
                    _sha256_file(path) != row.get("sha256")
                    or path.stat().st_size != row.get("size")
                    or _git_blob_sha(path) != row.get("git_blob_sha")
                ):
                    failures.append("source_file_integrity_mismatch")
            except (OSError, ValueError):
                failures.append("source_file_missing_or_invalid")

    try:
        resolved_bundle = LocalSpineBundleResolver(bundle_root).resolve(render_id)
        runtime_version = resolved_bundle.runtime_version
        if runtime_version != fetch_bundle.get("runtime_version"):
            failures.append("runtime_version_mismatch")
        if resolved_bundle.skel_path.relative_to(bundle_root.resolve()).as_posix() != fetch_bundle.get("skeleton_path"):
            failures.append("canonical_skeleton_path_mismatch")
        if resolved_bundle.atlas_path.relative_to(bundle_root.resolve()).as_posix() != fetch_bundle.get("atlas_path"):
            failures.append("canonical_atlas_path_mismatch")
        if [path.relative_to(bundle_root.resolve()).as_posix() for path in resolved_bundle.texture_paths] != sorted(textures):
            failures.append("atlas_texture_set_mismatch")
    except (OSError, ValueError, LocalSpineResolveError):
        failures.append("production_bundle_resolver_rejected_source")

    render_assets = render_manifest.get("assets") if isinstance(render_manifest, dict) else None
    render_entry = render_assets.get(render_id, {}) if isinstance(render_assets, dict) else {}
    if not isinstance(render_entry, dict) or not render_entry:
        failures.append("render_manifest_entry_missing")
    else:
        if render_manifest.get("source_commit") != source_commit or render_entry.get("source_commit") != source_commit:
            failures.append("render_source_commit_mismatch")
        if render_entry.get("asset_id") != render_id:
            failures.append("render_asset_identity_mismatch")
        for manifest_key, provenance_key, failure in (
            ("skel_relative_path", "skeleton_path", "render_skeleton_path_mismatch"),
            ("atlas_relative_path", "atlas_path", "render_atlas_path_mismatch"),
        ):
            if render_entry.get(manifest_key) != fetch_bundle.get(provenance_key):
                failures.append(failure)
        if render_entry.get("runtime_version") != fetch_bundle.get("runtime_version"):
            failures.append("render_runtime_version_mismatch")
        if render_entry.get("texture_count") != len(textures):
            failures.append("render_texture_count_mismatch")
        try:
            png_path = _inside(render_root, render_entry.get("rendered_png"), "渲染 PNG")
            relative_png = png_path.relative_to(render_root.resolve()).as_posix()
            metrics = analyze_png(png_path)
            png_sha = metrics["sha256"]
            dimensions = metrics["dimensions"]
            if png_sha != render_entry.get("sha256"):
                failures.append("render_png_sha256_mismatch")
            if dimensions != [render_entry.get("width"), render_entry.get("height")]:
                failures.append("render_png_dimensions_mismatch")
            visual = score_visual_metrics(metrics, baseline)
        except (OSError, ValueError, BatchValidationError):
            failures.append("render_png_missing_invalid_or_unscorable")

    failures = sorted(set(failures))
    machine_status = "FAIL" if failures else (visual or {}).get("status", "FAIL")
    return {
        "render_id": render_id,
        "resource_id": candidate.get("resource_id"),
        "character_key": candidate.get("character_key"),
        "consumer_type": candidate.get("consumer_type"),
        "machine_status": machine_status,
        "hard_failures": failures,
        "anomaly_score": (visual or {}).get("anomaly_score"),
        "anomaly_flags": (visual or {}).get("flags", []),
        "metric_scores": (visual or {}).get("metric_scores", {}),
        "visual_metrics": {
            name: round(float(metrics[name]), 8)
            for name in VISUAL_METRICS
            if metrics is not None and name in metrics
        },
        "visual_reference": {
            name: baseline.get("distributions", {}).get(name)
            for name in VISUAL_METRICS
            if isinstance(baseline.get("distributions"), dict)
            and isinstance(baseline["distributions"].get(name), dict)
        },
        "calibration_sample_count": (visual or {}).get("calibration_sample_count"),
        "png_sha256": png_sha,
        "pixel_sha256": metrics.get("rgba_pixel_sha256") if metrics else None,
        "dimensions": dimensions,
        "alpha_bbox": metrics.get("alpha_bbox") if metrics else None,
        "rendered_png": relative_png,
        "runtime_version": runtime_version or fetch_bundle.get("runtime_version"),
        "source_commit": source_commit,
        "face_anchor_state": "NOT_AUTHORED",
        "core_axis_state": "UNASSESSED",
        "manual_visual_review": "PENDING",
        "promotion_state": "NOT_ATTEMPTED",
    }


def deterministic_pass_sample(
    records: list[dict[str, Any]], *, batch_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    """依 batch、render ID 和输出 hash 稳定选出机器 PASS 样本。"""
    if not 1 <= limit <= 50:
        raise ValueError("PASS sample limit 必须在 1 到 50 之间")
    candidates = [
        row for row in records
        if row.get("machine_status") == "PASS"
        and isinstance(row.get("render_id"), str)
        and isinstance(row.get("png_sha256"), str)
    ]
    candidates.sort(
        key=lambda row: (
            hashlib.sha256(
                f"{batch_id}\0{row['render_id']}\0{row['png_sha256']}".encode("utf-8")
            ).hexdigest(),
            row["render_id"],
        )
    )
    return candidates[:limit]


def build_review_queue(
    batch: dict[str, Any],
    fetch_provenance: dict[str, Any],
    render_manifest: dict[str, Any],
    *,
    bundle_root: Path,
    render_root: Path,
    baseline: dict[str, Any],
    pass_sample_limit: int = 5,
) -> dict[str, Any]:
    candidates = batch.get("candidates") if isinstance(batch, dict) else None
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("batch 缺少候选列表")
    if not all(isinstance(value, dict) for value in (fetch_provenance, render_manifest, baseline)):
        raise ValueError("fetch、render manifest 和 baseline 须为 JSON object")
    if any(not isinstance(candidate, dict) for candidate in candidates):
        raise ValueError("batch 中含无效 candidate，拒绝静默忽略")
    candidate_ids = [candidate.get("render_id") for candidate in candidates]
    if (
        not all(isinstance(value, str) for value in candidate_ids)
        or batch.get("render_ids") != candidate_ids
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise ValueError("batch render_ids 与候选列表不一致")
    if (
        fetch_provenance.get("batch_id") != batch.get("batch_id")
        or fetch_provenance.get("generated_from_head") != batch.get("generated_from_head")
        or fetch_provenance.get("upstream_snapshot_sha") != batch.get("upstream_snapshot_sha")
    ):
        raise ValueError("fetch provenance 与 batch 身份不一致")
    items = [
        validate_candidate_render(
            candidate, fetch_provenance, render_manifest,
            bundle_root=bundle_root, render_root=render_root, baseline=baseline,
        )
        for candidate in candidates
    ]
    items.sort(key=lambda row: row["render_id"])
    sample = deterministic_pass_sample(items, batch_id=str(batch.get("batch_id", "")), limit=pass_sample_limit)
    statuses = [row["machine_status"] for row in items]
    return {
        "schema_version": 1,
        "batch_id": batch.get("batch_id"),
        "generated_from_head": batch.get("generated_from_head"),
        "upstream_snapshot_sha": batch.get("upstream_snapshot_sha"),
        "source_commit": fetch_provenance.get("source_commit"),
        "summary": {
            "candidate_count": len(items),
            "pass_count": statuses.count("PASS"),
            "pass_with_flags_count": statuses.count("PASS_WITH_FLAGS"),
            "fail_count": statuses.count("FAIL"),
            "manual_review_required_count": len(items),
            "promotion_count": 0,
        },
        "policy": {
            "visual_calibration_portraits": baseline.get("verified_portrait_count"),
            "pass_sample_policy": "sha256(batch_id + NUL + render_id + NUL + png_sha256), ascending, machine PASS only",
            "no_automatic_manifest_promotion": True,
            "visual_review_required_for_all_candidates": True,
        },
        "pass_sample": [row["render_id"] for row in sample],
        "items": items,
    }


def render_review_markdown(queue: dict[str, Any]) -> str:
    summary = queue.get("summary", {})
    lines = [
        f"# Spine Candidate Review · {queue.get('batch_id', 'unknown')}",
        "",
        f"- Candidate count: {summary.get('candidate_count', 0)}",
        f"- PASS / flagged / FAIL: {summary.get('pass_count', 0)} / {summary.get('pass_with_flags_count', 0)} / {summary.get('fail_count', 0)}",
        f"- Visual calibration: {queue.get('policy', {}).get('visual_calibration_portraits', 0)} verified portraits",
        f"- Deterministic PASS sample: {', '.join(queue.get('pass_sample', [])) or 'none'}",
        "- Manifest promotion: none; every candidate remains待人工复核（视觉与 framing）。",
        "",
        "`PASS` only means local integrity/provenance gates pass and no measured metric falls outside the baseline 5th–95th percentile. It is not artistic acceptance. `PASS_WITH_FLAGS` requires review of the listed metrics; `FAIL` blocks promotion.",
        "",
        "| Render | Runtime | Machine | Score | Flags / hard failures | PNG SHA-256 | Face Anchor | Core Axis | Review |",
        "|---|---:|---|---:|---|---|---|---|---|",
    ]
    for item in queue.get("items", []):
        flags = [*item.get("anomaly_flags", []), *item.get("hard_failures", [])]
        lines.append(
            "| {render_id} | {runtime} | {status} | {score} | {flags} | {sha} | {anchor} | {axis} | PENDING |".format(
                render_id=item.get("render_id", ""),
                runtime=item.get("runtime_version") or "unknown",
                status=item.get("machine_status", "FAIL"),
                score=item.get("anomaly_score") if item.get("anomaly_score") is not None else "—",
                flags=", ".join(flags) or "无",
                sha=item.get("png_sha256") or "—",
                anchor=item.get("face_anchor_state", "NOT_AUTHORED"),
                axis=item.get("core_axis_state", "UNASSESSED"),
            )
        )
    return "\n".join(lines) + "\n"


def create_contact_sheet(
    cards: list[dict[str, Any]], output_path: Path, *, columns: int = 4
) -> dict[str, Any]:
    """只接收 1600×2400 production white-card PNG，并稳定排序拼成审阅图。"""
    if not cards or not 1 <= columns <= 8:
        raise ValueError("contact sheet 需要卡片且 columns 必须在 1 到 8 之间")
    ordered = sorted(cards, key=lambda row: str(row.get("render_id", "")))
    if len({row.get("render_id") for row in ordered}) != len(ordered):
        raise ValueError("contact sheet 中 render_id 重复")
    cell_width, image_height, title_height, gap = 272, 360, 32, 16
    rows = math.ceil(len(ordered) / columns)
    width = gap + columns * (cell_width + gap)
    height = gap + rows * (image_height + title_height + gap)
    sheet = Image.new("RGB", (width, height), (238, 240, 243))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    cards_info: list[dict[str, Any]] = []
    for index, row in enumerate(ordered):
        render_id = row.get("render_id")
        if not isinstance(render_id, str) or not RENDER_ID_RE.fullmatch(render_id):
            raise ValueError("contact sheet render_id 无效")
        path_value = row.get("path")
        if not isinstance(path_value, (str, Path)):
            raise ValueError(f"white-card path 缺失: {render_id}")
        path = Path(path_value).resolve(strict=True)
        previous_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            with Image.open(path) as opened:
                if opened.format != "PNG" or opened.size != (1600, 2400):
                    raise ValueError(f"白卡必须是 1600×2400 PNG: {render_id}")
                opened.load()
                card = opened.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError(f"white-card 无法完整解码: {render_id}") from exc
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated
        column, line = index % columns, index // columns
        x, y = gap + column * (cell_width + gap), gap + line * (image_height + title_height + gap)
        draw.text((x, y + 7), render_id, fill=(28, 34, 42), font=font)
        thumbnail = card.resize((240, image_height), Image.Resampling.LANCZOS)
        sheet.paste(thumbnail, (x + 16, y + title_height))
        cards_info.append({"render_id": render_id, "sha256": _sha256_file(path), "dimensions": [1600, 2400]})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG", optimize=False)
    return {
        "schema_version": 1,
        "columns": columns,
        "render_ids": [row["render_id"] for row in cards_info],
        "cards": cards_info,
        "dimensions": list(sheet.size),
        "sha256": _sha256_file(output_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--fetch-provenance", type=Path, required=True)
    parser.add_argument("--render-manifest", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--render-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output_dir = require_new_external_path(
            args.output_dir, REPO_ROOT, label="review artifacts"
        )
        batch = json.loads(args.batch.read_text(encoding="utf-8"))
        fetch = json.loads(args.fetch_provenance.read_text(encoding="utf-8"))
        rendered = json.loads(args.render_manifest.read_text(encoding="utf-8"))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        queue = build_review_queue(
            batch, fetch, rendered,
            bundle_root=args.bundle_root, render_root=args.render_root, baseline=baseline,
        )
        output_dir.mkdir(parents=True, exist_ok=False)
        with (output_dir / "review-queue.json").open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        with (output_dir / "review-queue.md").open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(render_review_markdown(queue))
        print(json.dumps(queue["summary"], ensure_ascii=False, sort_keys=True))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"review queue 生成失败: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
