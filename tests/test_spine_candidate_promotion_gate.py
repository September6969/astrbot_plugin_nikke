from __future__ import annotations

from scripts.check_spine_candidate_promotion import evaluate_promotion_gate


def _evidence() -> tuple[dict, dict]:
    candidate = {
        "render_id": "c020",
        "machine_status": "PASS",
        "hard_failures": [],
        "png_sha256": "a" * 64,
        "pixel_sha256": "b" * 64,
        "dimensions": [425, 891],
        "alpha_bbox": [10, 10, 415, 880],
        "source_commit": "c" * 40,
        "runtime_version": "4.1",
        "rendered_png": "c020.png",
    }
    review = {
        "render_id": "c020",
        "decision": "APPROVE",
        "reviewer": "reviewer-id",
        "visual_review": "APPROVED",
        "png_sha256": "a" * 64,
        "source_commit": "c" * 40,
        "target_manifest_sha256": "d" * 64,
        "face_anchor": {
            "state": "VERIFIED",
            "png_sha256": "a" * 64,
            "pixel_sha256": "b" * 64,
            "image_size": [425, 891],
            "point": [210, 100],
        },
        "framing_state": "VERIFIED_HEAD_ONLY",
        "core_axis_state": "UNAVAILABLE",
    }
    return candidate, review


def test_promotion_gate_requires_explicit_human_visual_and_anchor_approval() -> None:
    candidate, review = _evidence()

    result = evaluate_promotion_gate(candidate, review, current_manifest_sha256="d" * 64)

    assert result["eligible"] is True
    assert result["blockers"] == []
    assert result["action"] == "NO_WRITE_PROMOTION_GATE_ONLY"


def test_promotion_gate_blocks_unreviewed_and_manifest_drift() -> None:
    candidate, review = _evidence()
    review["decision"] = "PENDING"

    result = evaluate_promotion_gate(candidate, review, current_manifest_sha256="e" * 64)

    assert result["eligible"] is False
    assert "explicit_reviewer_approval_missing" in result["blockers"]
    assert "production_manifest_changed_since_review" in result["blockers"]
    assert result["action"] == "NO_WRITE_PROMOTION_GATE_ONLY"


def test_promotion_gate_requires_anchor_identity_to_match_candidate() -> None:
    candidate, review = _evidence()
    review["face_anchor"]["png_sha256"] = "f" * 64

    result = evaluate_promotion_gate(candidate, review, current_manifest_sha256="d" * 64)

    assert result["eligible"] is False
    assert "face_anchor_not_bound_to_rendered_png" in result["blockers"]
