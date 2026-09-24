# SPDX-License-Identifier: GPL-3.0-or-later
"""锁定 post-refactor Spine 覆盖审计的离线集合语义。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_spine_resource_coverage import audit, classify_undeclared_png


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


def test_undeclared_png_audit_is_deterministic_exhaustive_and_manifest_fail_closed() -> None:
    report = _report()
    review = report["undeclared_png_audit"]
    undeclared = set(report["sets"]["bundled_png_not_declared_by_manifest"])
    category_sets = {
        category: set(values)
        for category, values in review["classification_sets"].items()
    }

    assert review == _report()["undeclared_png_audit"]
    assert set(category_sets) == {
        "VERIFIED_MANIFEST_CANDIDATE",
        "VALID_VARIANT_NEEDS_REVIEW",
        "HISTORICAL_OR_TEST_ONLY",
        "STALE_OR_ORPHAN_FILE",
        "INVALID_ASSET",
    }
    assert set.union(*category_sets.values()) == undeclared
    assert sum(map(len, category_sets.values())) == len(undeclared)
    assert review["summary"]["undeclared_png_count"] == 28
    assert review["summary"]["classification_counts"] == {
        "VERIFIED_MANIFEST_CANDIDATE": 27,
        "VALID_VARIANT_NEEDS_REVIEW": 0,
        "HISTORICAL_OR_TEST_ONLY": 0,
        "STALE_OR_ORPHAN_FILE": 0,
        "INVALID_ASSET": 1,
    }
    assert category_sets["VERIFIED_MANIFEST_CANDIDATE"] == undeclared - {"c191"}
    assert category_sets["INVALID_ASSET"] == {"c191"}

    records = {row["render_id"]: row for row in review["records"]}
    assert set(records) == undeclared
    for render_id, row in records.items():
        assert row["identity_chain"]["default_character_consumer"] is True
        assert row["identity_chain"]["canonical_resource_ids"]
        assert row["upstream"]["complete_root_bundle"] is True
        assert {Path(item["path"]).suffix for item in row["upstream"]["root_files"]} >= {".skel", ".atlas", ".png"}
        assert row["bundled_png"]["decode_valid"] is True
        assert row["bundled_png"]["manifest_declared"] is False
        assert row["bundled_png"]["manifest_trusted"] is False
        assert row["source_provenance"]["skeleton_runtime_metadata"] in {"4.0.47", "4.1.20"}
        assert row["source_provenance"]["generation_record_valid"] is True
        assert row["source_provenance"]["renderer_build_digest_recorded"] is False
        assert row["source_provenance"]["pinned_source_bundle_complete"] is True
        assert row["face_anchor"]["identity_valid"] is True
        assert row["face_anchor"]["png_sha256_matches"] is True
        assert row["face_anchor"]["rgba_pixel_sha256_matches"] is True
        assert row["face_anchor"]["dimensions_match"] is True
        assert row["face_anchor"]["trusted_semantic_core_axis"] is False
        assert row["face_anchor"]["core_axis_state"] == "unavailable"
        assert row["evidence_usage"]["centering_sample"] is True
        assert row["production_eligibility"]["accepted_by_manifest_trust_boundary"] is False
        assert row["production_eligibility"]["automatic_manifest_promotion"] is False

    for render_id, row in records.items():
        matches = render_id != "c191"
        assert row["source_provenance"]["generation_inputs_match_pinned_bundle"] is matches
        assert row["source_provenance"]["source_bundle_sha256_bound_to_render"] is matches
    assert records["c191"]["classification"] == "INVALID_ASSET"
    assert records["c191"]["source_provenance"]["state"] == "generation_source_mismatch"

    # 当前 11 个 manifest 项保持不变；未声明 PNG 不因审计输出被提升为生产资源。
    assert undeclared.isdisjoint(report["manifest_status"])
    assert report["summary"]["manifest_render_ids"] == 11
    assert report["summary"]["verified_manifest_png_render_ids"] == 11
    assert review["scope"]["manifest_trust_boundary_changed"] is False


def test_undeclared_png_classification_priority_and_variants_are_explicit() -> None:
    default = {"kind": "default", "render_id": "c999"}
    variant = {"kind": "verified_costume", "render_id": "c999_01"}

    assert classify_undeclared_png(
        image_valid=False,
        anchor_present=False,
        anchor_valid=False,
        consumers=[default],
        upstream_bundle_complete=True,
        centering_sample=True,
    )[0] == "INVALID_ASSET"
    assert classify_undeclared_png(
        image_valid=True,
        anchor_present=False,
        anchor_valid=False,
        consumers=[],
        upstream_bundle_complete=True,
        centering_sample=False,
    )[0] == "STALE_OR_ORPHAN_FILE"
    assert classify_undeclared_png(
        image_valid=True,
        anchor_present=False,
        anchor_valid=False,
        consumers=[variant],
        upstream_bundle_complete=True,
        centering_sample=False,
    )[0] == "VALID_VARIANT_NEEDS_REVIEW"
    assert classify_undeclared_png(
        image_valid=True,
        anchor_present=True,
        anchor_valid=False,
        consumers=[default],
        upstream_bundle_complete=True,
        centering_sample=True,
    )[0] == "INVALID_ASSET"
    assert classify_undeclared_png(
        image_valid=True,
        anchor_present=True,
        anchor_valid=True,
        consumers=[default],
        upstream_bundle_complete=True,
        centering_sample=True,
        generation_record_valid=False,
        pinned_source_matches=False,
    )[0] == "HISTORICAL_OR_TEST_ONLY"
    candidate, reason = classify_undeclared_png(
        image_valid=True,
        anchor_present=True,
        anchor_valid=True,
        consumers=[default],
        upstream_bundle_complete=True,
        centering_sample=True,
        generation_record_valid=True,
        pinned_source_matches=True,
    )
    assert candidate == "VERIFIED_MANIFEST_CANDIDATE"
    assert "不自动提升" in reason

    assert classify_undeclared_png(
        image_valid=True,
        anchor_present=True,
        anchor_valid=True,
        consumers=[default],
        upstream_bundle_complete=True,
        centering_sample=True,
        generation_record_valid=True,
        pinned_source_matches=False,
    )[0] == "INVALID_ASSET"
