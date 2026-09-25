from __future__ import annotations

from scripts.build_spine_candidate_batch import build_candidate_batch


def test_batch_selection_is_deterministic_and_defaults_only() -> None:
    coverage = {
        "generated_from_head": "a" * 40,
        "source": {"commit_sha": "b" * 40},
        "sets": {
            "canonical_default_consumers": [
                {
                    "character_key": "signal",
                    "identity": "22:default",
                    "kind": "default",
                    "render_id": "c022",
                    "resource_id": "22",
                },
                {
                    "character_key": "delta",
                    "identity": "20:default",
                    "kind": "default",
                    "render_id": "c020",
                    "resource_id": "20",
                },
            ],
            "canonical_render_consumers_with_upstream_l2d": ["c020", "c020_01", "c022"],
            "render_asset_gap": ["c020", "c020_01", "c022"],
            "unsupported": [],
        },
    }

    first = build_candidate_batch(coverage, batch_id="batch-001", batch_size=10)
    second = build_candidate_batch(coverage, batch_id="batch-001", batch_size=10)

    assert first == second
    assert first["render_ids"] == ["c020", "c022"]
    assert first["generated_from_head"] == "a" * 40
    assert first["upstream_snapshot_sha"] == "b" * 40
    assert [candidate["consumer_type"] for candidate in first["candidates"]] == [
        "default_character",
        "default_character",
    ]
    assert [candidate["resource_id"] for candidate in first["candidates"]] == ["20", "22"]
    assert all(candidate["upstream_bundle_complete"] for candidate in first["candidates"])
