# SPDX-License-Identifier: GPL-3.0-or-later
"""锁定 post-refactor Spine 覆盖审计的离线集合语义。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_spine_resource_coverage import audit


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json"


def _report() -> dict:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return audit(ROOT, snapshot, generated_from_head="fixed-test-head")


def test_coverage_audit_is_deterministic_and_offline() -> None:
    cache_path = ROOT / ".audit-cache-unused"
    assert not cache_path.exists()

    first = _report()
    second = _report()

    assert first == second
    assert not cache_path.exists()
    assert first["source"]["snapshot_schema_version"] == 2
    assert first["source"]["fb_inventory_known"] is True


def test_coverage_sets_have_explicit_non_orphan_costume_consumers() -> None:
    report = _report()
    summary = report["summary"]
    sets = report["sets"]
    costume_render_ids = {row["render_id"] for row in sets["verified_costume_consumers"]}

    assert {"c010_02", "c010_03"} <= costume_render_ids
    assert sets["manifest_without_current_character_consumer"] == []
    assert summary["manifest_without_current_character_consumer"] == 0
    assert "c010_02" not in sets["manifest_without_current_character_consumer"]
    assert "c010_03" not in sets["manifest_without_current_character_consumer"]

    for name in (
        "canonical_render_consumers_with_upstream_l2d",
        "upstream_exists_manifest_missing",
        "manifest_without_current_character_consumer",
        "manifest_png_missing_or_invalid",
        "bundled_png_not_declared_by_manifest",
        "manifest_without_face_anchor",
        "manifest_face_anchor_without_trusted_semantic_core_axis",
        "character_render_without_verified_portrait_or_unsupported",
        "render_asset_gap",
        "unsupported",
        "upstream_l2d_not_represented_by_current_character_data",
    ):
        values = sets[name]
        if all(isinstance(value, str) for value in values):
            assert values == sorted(set(values)), name

    definitions = report["definitions"]
    assert definitions["missing_manifest"] != definitions["render_asset_gap"]
    assert "Costume" in definitions["manifest_orphan"]
    assert "完整 upstream bundle" in definitions["render_asset_gap"]
    assert "视觉/来源复核" in definitions["manual_review_required"]
    assert {row["render_id"] for row in sets["manual_review_required"]} == set(sets["render_asset_gap"])


def test_c018_and_semantic_framing_regressions_are_in_audit() -> None:
    report = _report()
    summary = report["summary"]
    c018 = report["c018"]

    assert c018["resource_id"] == 18
    assert c018["render_id"] == "c018"
    assert c018["upstream_l2d_available"] is True
    assert c018["fb_available"] is False
    assert c018["runtime_version"] == "4.1"
    assert c018["manifest_declared"] is True
    assert c018["png_verified"] is True
    assert c018["face_anchor_state"] == "anchor_available_head_only"
    assert c018["core_axis"] == "unavailable"

    trusted = set(report["sets"]["trusted_semantic_core_axis_render_ids"])
    assert {"c401", "c581"} <= trusted
    assert summary["manifest_png_missing_or_invalid"] == 0
    assert summary["valid_face_anchor_render_ids"] == summary["face_anchor_render_ids"]


def test_current_coverage_categories_match_the_pinned_snapshot() -> None:
    report = _report()
    summary = report["summary"]

    assert summary["character_resources"] == 200
    assert summary["canonical_render_consumers"] == 378
    assert summary["upstream_l2d_render_ids"] == 558
    assert summary["upstream_l2d_complete_bundles"] == 558
    assert summary["manifest_render_ids"] == 11
    assert summary["bundled_png_render_ids"] == 39
    assert summary["verified_manifest_png_render_ids"] == 11
    assert summary["face_anchor_render_ids"] == 39
    assert summary["trusted_semantic_core_axis_render_ids"] == 2
    assert summary["upstream_exists_manifest_missing"] == 367
    assert summary["manifest_without_current_character_consumer"] == 0
    assert summary["render_asset_gap"] == 367
    assert summary["manual_review_required"] == 367
    assert summary["unsupported"] == 0
