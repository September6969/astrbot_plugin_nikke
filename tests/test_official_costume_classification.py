# SPDX-License-Identifier: GPL-3.0-or-later
"""官方 178 Costume universe 的分类、owner 与映射回归。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))


def test_all_official_costumes_have_final_mapping() -> None:
    inventory = _load("docs/evidence/official_costume_inventory.json")["costumes"]
    matrix = _load("docs/evidence/costume_spine_candidate_matrix.json")
    registry = _load("assets/costumes.json")["entries"]
    manual = _load("docs/evidence/costume_identity_manual_validation.json")

    assert len(inventory) == len(matrix["items"]) == len(registry) == 178
    assert matrix["classification_counts"] == {
        "VERIFIED_EXISTING": 47,
        "MANUAL_VALIDATED_CANDIDATE": 131,
    }
    assert manual["entry_count"] == 131
    assert {row["costume_id"] for row in inventory} == {row["costume_id"] for row in registry}
    assert all(row["classification"] in {"VERIFIED_EXISTING", "MANUAL_VALIDATED_CANDIDATE"} for row in matrix["items"])


def test_official_costume_owners_and_render_ids_are_unique() -> None:
    entries = _load("assets/costumes.json")["entries"]
    costume_ids = [row["costume_id"] for row in entries]
    render_ids = [row["spine"]["asset_id"] for row in entries]

    assert len(costume_ids) == len(set(costume_ids)) == 178
    assert len(render_ids) == len(set(render_ids)) == 178
    for row in entries:
        owner = int(row["character_resource_id"])
        asset_id = row["spine"]["asset_id"]
        assert asset_id.startswith(f"c{owner:03d}_")
        assert row["spine"]["mode"] == "independent_asset"
        assert row["spine"]["skin_name"] is None


def test_frozen_costume_regressions_are_unchanged() -> None:
    entries = {row["costume_id"]: row["spine"]["asset_id"] for row in _load("assets/costumes.json")["entries"]}
    assert entries["30052"] == "c330_02"
    assert entries["120001"] == "c330_01"
    assert entries["30053"] == "c513_02"
    assert entries["50016"] == "c513_01"
    assert entries["10016"] == "c513_03"
    assert entries["30049"] == "c095_01"
    assert entries["110023"] == "c222_01"
    assert entries["20001"] == "c010_02"


def test_public_poster_suffix_is_not_used_as_spine_identity() -> None:
    matrix = {row["costume_id"]: row for row in _load("docs/evidence/costume_spine_candidate_matrix.json")["items"]}
    assert matrix["10005"]["public_poster_asset_id"] == "c010_02"
    assert matrix["10005"]["matched_asset_id"] == "c010_03"
    assert matrix["30006"]["public_poster_asset_id"] == "c072_02"
    assert matrix["30006"]["matched_asset_id"] == "c072_01"
    assert matrix["10005"]["evidence"]["public_poster_is_not_spine_identity"] is True


def test_manual_validation_provenance_is_complete() -> None:
    manual = _load("docs/evidence/costume_identity_manual_validation.json")["entries"]
    registry = {row["costume_id"]: row for row in _load("assets/costumes.json")["entries"]}
    assert len(manual) == 131
    for row in manual:
        assert len(row["contact_sheet_sha256"]) == 64
        assert len(row["poster_png_sha256"]) == 64
        assert len(row["render_png_sha256"]) == 64
        evidence = registry[row["costume_id"]]["asset_evidence"][-1]
        assert evidence["contact_sheet_sha256"] == row["contact_sheet_sha256"]
        assert evidence["render_png_sha256"] == row["render_png_sha256"]
