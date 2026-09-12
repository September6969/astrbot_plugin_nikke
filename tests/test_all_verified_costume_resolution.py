# SPDX-License-Identifier: GPL-3.0-or-later
"""Exhaustive test for all verified costume resolution."""

import json
from pathlib import Path
from typing import Any
import pytest
from PIL import Image

from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider


def get_manifest_assets() -> tuple[dict[str, Any] | None, Path | None]:
    candidates = [
        Path("/AstrBot/data/nikke/spine-manifest.json"),
        Path("/opt/nikke-bot/astrbot/data/nikke/spine-manifest.json"),
        Path(__file__).parent.parent / "docs" / "evidence" / "spine_runtime_resolution_audit.json",
    ]
    for p in candidates:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if p.name == "spine_runtime_resolution_audit.json":
                assets = {item["actual_render_id"]: item for item in data.get("alternate", {}).get("items", [])}
                return assets, p
            assets = data.get("assets", data.get("characters", {}))
            return assets, p
    return None, None


@pytest.fixture(scope="module")
def provider() -> NikkeDbProvider:
    base = Path(__file__).parent.parent
    return NikkeDbProvider(base / "data" / "cache", base / "assets")


@pytest.fixture(scope="module")
def costume_entries() -> list[dict]:
    p = Path(__file__).parent.parent / "assets" / "costumes.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("entries", [])


def test_all_verified_costumes_resolve(provider: NikkeDbProvider, costume_entries: list[dict]):
    assert len(costume_entries) == 42, f"Expected 42 verified costumes, got {len(costume_entries)}"
    assets, manifest_path = get_manifest_assets()

    for entry in costume_entries:
        cid = entry.get("costume_id")
        rid = entry.get("character_resource_id")
        assert cid and str(cid).isdigit() and int(cid) > 0, f"Invalid costume ID: {cid}"
        assert rid and str(rid).isdigit() and int(rid) > 0, f"Invalid character resource ID: {rid}"

        spine = entry.get("spine", {})
        mode = spine.get("mode")
        assert mode in ("independent_asset", "shared_skin"), f"Invalid Spine mode: {mode}"
        asset_id = spine.get("asset_id")
        assert asset_id and asset_id.startswith("c"), f"Invalid Spine asset ID: {asset_id}"
        skin_name = spine.get("skin_name")
        if mode == "shared_skin":
            assert skin_name, f"Shared skin mode requires skin_name: {entry}"
            expected_render_id = f"{asset_id}@{skin_name}"
        else:
            assert skin_name is None, f"Independent asset mode must have null skin_name: {entry}"
            expected_render_id = asset_id

        actual_render_id = provider.resolve_render_id(rid, cid)
        assert actual_render_id != "missing", f"Costume {cid} for resource {rid} resolved to missing"
        assert actual_render_id == expected_render_id, (
            f"Costume {cid} for resource {rid} expected {expected_render_id}, got {actual_render_id}"
        )

        # Crucial security assertion: alternate skin MUST NEVER fall back to base skin
        base_render_id = provider.resolve_render_id(rid, 0)
        assert actual_render_id != base_render_id, (
            f"Costume {cid} ({entry.get('costume_name')}) falls back to default base skin {base_render_id}!"
        )

        if assets is not None:
            assert expected_render_id in assets, (
                f"Verified costume render_id {expected_render_id} not present in manifest {manifest_path}"
            )
