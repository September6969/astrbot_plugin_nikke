#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""从离线 coverage audit 中稳定选择默认角色 Spine 候选批次。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.phase3_output_guard import require_new_external_path


_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.ASCII)
_DEFAULT_RENDER_ID_RE = re.compile(r"^c[0-9]+$", re.ASCII)
_BATCH_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$", re.ASCII)
SELECTION_POLICY = (
    "default_only; upstream_complete; known_runtime_first_then_detect; "
    "resource_id_ascending; render_id_tiebreak; no_random_selection"
)


def build_candidate_batch(
    coverage: dict[str, Any],
    *,
    batch_id: str = "batch-001",
    batch_size: int = 20,
) -> dict[str, Any]:
    """选择当前 coverage gap 中优先级最高的默认角色，不选择 costume。"""
    if not 5 <= batch_size <= 50:
        raise ValueError("batch_size 必须在 5 到 50 之间")
    if not _BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id 只能包含小写字母、数字和连字符")
    if not isinstance(coverage, dict):
        raise ValueError("coverage summary 必须是 JSON object")

    generated_from_head = coverage.get("generated_from_head")
    source = coverage.get("source")
    snapshot_sha = source.get("commit_sha") if isinstance(source, dict) else None
    if not isinstance(generated_from_head, str) or not _SHA_RE.fullmatch(generated_from_head):
        raise ValueError("coverage summary 缺少有效 generated_from_head")
    if not isinstance(snapshot_sha, str) or not _SHA_RE.fullmatch(snapshot_sha):
        raise ValueError("coverage summary 缺少有效 upstream commit SHA")

    sets = coverage.get("sets")
    if not isinstance(sets, dict):
        raise ValueError("coverage summary 缺少 sets")
    defaults = sets.get("canonical_default_consumers")
    gaps = sets.get("render_asset_gap")
    upstream = sets.get("canonical_render_consumers_with_upstream_l2d")
    unsupported = sets.get("unsupported", [])
    if not isinstance(defaults, list) or not isinstance(gaps, list) or not isinstance(upstream, list):
        raise ValueError("coverage summary 中默认消费者、gap 或 upstream 集合格式无效")
    if not isinstance(unsupported, list):
        raise ValueError("unsupported 集合格式无效")

    gap_ids = {value for value in gaps if isinstance(value, str)}
    upstream_ids = {value for value in upstream if isinstance(value, str)}
    unsupported_ids = {
        row if isinstance(row, str) else row.get("render_id")
        for row in unsupported
        if isinstance(row, (str, dict))
    }

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in defaults:
        if not isinstance(row, dict) or row.get("kind") != "default":
            continue
        render_id = row.get("render_id")
        if (
            not isinstance(render_id, str)
            or not _DEFAULT_RENDER_ID_RE.fullmatch(render_id)
            or render_id in seen
            or render_id not in gap_ids
            or render_id not in upstream_ids
            or render_id in unsupported_ids
        ):
            continue
        resource_id = row.get("resource_id")
        if not isinstance(resource_id, (str, int)) or not str(resource_id).isdigit():
            continue
        character_key = row.get("character_key")
        if not isinstance(character_key, str) or not character_key:
            continue
        seen.add(render_id)
        candidates.append(
            {
                "render_id": render_id,
                "consumer_type": "default_character",
                "resource_id": str(resource_id),
                "character_key": character_key,
                "costume_id": None,
                "runtime_hint": None,
                "priority": 2,
                "upstream_bundle_complete": True,
                "reason": (
                    "canonical default consumer; upstream bundle is complete; "
                    "verified bundled portrait is missing; runtime must be detected from skeleton"
                ),
            }
        )

    candidates.sort(key=lambda item: (int(item["resource_id"]), item["render_id"]))
    selected = candidates[:batch_size]
    return {
        "schema_version": 1,
        "generated_from_head": generated_from_head,
        "upstream_snapshot_sha": snapshot_sha,
        "batch_id": batch_id,
        "selection_policy": SELECTION_POLICY,
        "render_ids": [item["render_id"] for item in selected],
        "candidates": selected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-id", default="batch-001")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args(argv)

    coverage = json.loads(args.coverage_summary.read_text(encoding="utf-8"))
    batch = build_candidate_batch(coverage, batch_id=args.batch_id, batch_size=args.batch_size)
    try:
        output = require_new_external_path(
            args.output, Path(__file__).resolve().parents[1], label="候选 batch"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as destination:
            destination.write(json.dumps(batch, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"batch_id": args.batch_id, "candidate_count": len(batch["candidates"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
