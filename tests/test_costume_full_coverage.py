# SPDX-License-Identifier: GPL-3.0-or-later
"""全量 Costume 审计只以官方分母和 verified registry 计算。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts.audit_costume_spine_coverage import build_report


def test_full_coverage_separates_official_and_verified_denominators(tmp_path: Path) -> None:
    png = tmp_path / "c222_01.png"
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(png)
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    official = [{
        "resource_id": 222,
        "name": "Scarlet",
        "costumes": [{"id": 110023, "costume_index": 1}, {"id": 999999, "costume_index": 2}],
    }]
    registry = {"schema_version": 3, "entries": [{
        "costume_id": "110023", "character_resource_id": "222", "costume_name": "Racer's High",
        "spine": {"mode": "independent_asset", "asset_id": "c222_01", "skin_name": None},
        "source": "official", "source_sha256": "a" * 64, "verified_at": "2026-09-12",
    }]}
    manifest = {"assets": {"c222_01": {"rendered_png": "c222_01.png", "sha256": digest, "runtime_version": "4.0"}}}

    report = build_report(official, registry, manifest, tmp_path, source="official", source_sha256="b" * 64)

    assert report["official_costume_total"] == 2
    assert report["verified_costume_total"] == 1
    assert report["verified_subset_coverage_percent"] == 100.0
    assert report["official_costume_coverage_percent"] == 50.0
    assert report["spine_independent_total"] == 1
    assert report["mapping_missing"] == 1
    assert report["items"][1]["costume_name"] is None
