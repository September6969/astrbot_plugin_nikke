#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""只读检查候选资源是否具备人工审批后的 manifest 晋升前置条件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


def evaluate_promotion_gate(
    candidate: dict[str, Any],
    review: dict[str, Any],
    *,
    current_manifest_sha256: str,
) -> dict[str, Any]:
    """只判断当前证据是否满足晋升前置条件；绝不写 manifest 或资源文件。"""
    blockers: list[str] = []
    render_id = candidate.get("render_id")
    candidate_sha = candidate.get("png_sha256")
    pixel_sha = candidate.get("pixel_sha256")
    dimensions = candidate.get("dimensions")
    source_commit = candidate.get("source_commit")
    if candidate.get("machine_status") not in {"PASS", "PASS_WITH_FLAGS"}:
        blockers.append("machine_validation_not_passed")
    if candidate.get("hard_failures"):
        blockers.append("candidate_has_hard_failures")
    if not isinstance(candidate_sha, str) or not SHA256_RE.fullmatch(candidate_sha):
        blockers.append("candidate_png_hash_missing")
    if not isinstance(pixel_sha, str) or not SHA256_RE.fullmatch(pixel_sha):
        blockers.append("candidate_pixel_hash_missing")
    if (
        not isinstance(dimensions, list)
        or len(dimensions) != 2
        or any(type(value) is not int or value <= 0 for value in dimensions)
    ):
        blockers.append("candidate_dimensions_missing")
    if not isinstance(source_commit, str) or not SHA1_RE.fullmatch(source_commit):
        blockers.append("candidate_source_commit_missing")

    if review.get("render_id") != render_id:
        blockers.append("review_render_identity_mismatch")
    if review.get("decision") != "APPROVE" or not str(review.get("reviewer", "")).strip():
        blockers.append("explicit_reviewer_approval_missing")
    if review.get("visual_review") != "APPROVED":
        blockers.append("manual_visual_review_missing")
    if review.get("png_sha256") != candidate_sha:
        blockers.append("review_png_hash_mismatch")
    if review.get("source_commit") != source_commit:
        blockers.append("review_source_commit_mismatch")
    if (
        not isinstance(current_manifest_sha256, str)
        or not SHA256_RE.fullmatch(current_manifest_sha256)
        or review.get("target_manifest_sha256") != current_manifest_sha256
    ):
        blockers.append("production_manifest_changed_since_review")

    anchor = review.get("face_anchor")
    if not isinstance(anchor, dict) or anchor.get("state") != "VERIFIED":
        blockers.append("trusted_face_anchor_missing")
    else:
        if anchor.get("png_sha256") != candidate_sha or anchor.get("pixel_sha256") != pixel_sha:
            blockers.append("face_anchor_not_bound_to_rendered_png")
        if anchor.get("image_size") != dimensions:
            blockers.append("face_anchor_dimensions_mismatch")
        point = anchor.get("point")
        alpha_bbox = candidate.get("alpha_bbox")
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(type(value) is not int for value in point)
            or not isinstance(dimensions, list)
            or not isinstance(alpha_bbox, list)
            or len(alpha_bbox) != 4
            or any(type(value) is not int for value in alpha_bbox)
        ):
            blockers.append("face_anchor_geometry_missing")
        else:
            x, y = point
            left, top, right, bottom = alpha_bbox
            if not (0 <= x < dimensions[0] and 0 <= y < dimensions[1] and left <= x < right and top <= y < bottom):
                blockers.append("face_anchor_point_outside_visible_portrait")

    if review.get("framing_state") not in {"VERIFIED_HEAD_ONLY", "VERIFIED_SEMANTIC"}:
        blockers.append("framing_review_missing")
    if review.get("core_axis_state") not in {"UNAVAILABLE", "VERIFIED_SEMANTIC"}:
        blockers.append("core_axis_state_not_explicit")
    if review.get("core_axis_state") == "VERIFIED_SEMANTIC" and not str(
        review.get("core_axis_evidence_ref", "")
    ).strip():
        blockers.append("semantic_core_axis_evidence_missing")

    blockers = sorted(set(blockers))
    return {
        "schema_version": 1,
        "render_id": render_id,
        "eligible": not blockers,
        "blockers": blockers,
        "action": "NO_WRITE_PROMOTION_GATE_ONLY",
        "current_manifest_sha256": current_manifest_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        queue = json.loads(args.queue.read_text(encoding="utf-8"))
        decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
        manifest_sha = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        rows = decisions.get("items") if isinstance(decisions, dict) else None
        if not isinstance(rows, list):
            raise ValueError("decision 文件必须包含 items 数组")
        decision_by_id = {
            row.get("render_id"): row for row in rows if isinstance(row, dict) and isinstance(row.get("render_id"), str)
        }
        result = [
            evaluate_promotion_gate(
                candidate,
                decision_by_id.get(candidate.get("render_id"), {}),
                current_manifest_sha256=manifest_sha,
            )
            for candidate in queue.get("items", [])
            if isinstance(candidate, dict)
        ]
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"晋升 gate 输入无效: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"eligible_count": sum(row["eligible"] for row in result), "results": result}, ensure_ascii=False, indent=2))
    return 0 if result and all(row["eligible"] for row in result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
