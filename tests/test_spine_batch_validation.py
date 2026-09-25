from __future__ import annotations

from pathlib import Path

from scripts.spine_batch_validation import build_verified_baseline, score_visual_metrics


ROOT = Path(__file__).resolve().parents[1]


def test_verified_manifest_portraits_define_reproducible_baseline() -> None:
    baseline = build_verified_baseline(ROOT)

    assert baseline["verified_portrait_count"] == 38
    assert baseline["hard_fail_count"] == 0
    for metric in (
        "aspect_ratio",
        "alpha_coverage",
        "bbox_width_ratio",
        "bbox_height_ratio",
        "bbox_occupancy",
        "top_margin_ratio",
        "bottom_margin_ratio",
        "anchor_y_ratio",
    ):
        distribution = baseline["distributions"][metric]
        assert distribution["min"] <= distribution["p05"]
        assert distribution["p05"] <= distribution["median"]
        assert distribution["median"] <= distribution["p95"]
        assert distribution["p95"] <= distribution["max"]


def test_visual_score_is_calibrated_to_verified_range_and_flags_outliers() -> None:
    baseline = {
        "verified_portrait_count": 38,
        "distributions": {
            "aspect_ratio": {"min": 0.3, "p05": 0.4, "median": 0.6, "p95": 0.9, "max": 1.0},
            "alpha_coverage": {"min": 0.2, "p05": 0.3, "median": 0.4, "p95": 0.5, "max": 0.6},
            "bbox_width_ratio": {"min": 0.8, "p05": 0.85, "median": 0.9, "p95": 0.95, "max": 0.98},
            "bbox_height_ratio": {"min": 0.9, "p05": 0.92, "median": 0.95, "p95": 0.97, "max": 0.99},
            "bbox_occupancy": {"min": 0.7, "p05": 0.75, "median": 0.85, "p95": 0.92, "max": 0.96},
            "left_margin_ratio": {"min": 0.01, "p05": 0.02, "median": 0.03, "p95": 0.04, "max": 0.05},
            "top_margin_ratio": {"min": 0.01, "p05": 0.02, "median": 0.03, "p95": 0.04, "max": 0.05},
            "right_margin_ratio": {"min": 0.01, "p05": 0.02, "median": 0.03, "p95": 0.04, "max": 0.05},
            "bottom_margin_ratio": {"min": 0.01, "p05": 0.02, "median": 0.03, "p95": 0.04, "max": 0.05},
        },
    }
    typical = {name: values["median"] for name, values in baseline["distributions"].items()}
    unusual = {**typical, "aspect_ratio": 1.2}

    assert score_visual_metrics(typical, baseline)["status"] == "PASS"
    result = score_visual_metrics(unusual, baseline)
    assert result["status"] == "PASS_WITH_FLAGS"
    assert "outside_verified_range:aspect_ratio" in result["flags"]
    assert result["anomaly_score"] > 0
