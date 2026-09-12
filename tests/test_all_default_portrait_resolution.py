# SPDX-License-Identifier: GPL-3.0-or-later
"""Exhaustive test for all default character portrait resolution."""

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
                assets = {item["actual_render_id"]: item for item in data.get("default", {}).get("items", [])}
                return assets, p
            assets = data.get("assets", data.get("characters", {}))
            return assets, p
    return None, None


def get_rendered_dir() -> Path | None:
    candidates = [
        Path("/AstrBot/data/nikke/spine-rendered"),
        Path("/opt/nikke-bot/astrbot/data/nikke/spine-rendered"),
        Path(__file__).parent.parent / "assets" / "spine-rendered",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None


@pytest.fixture(scope="module")
def provider() -> NikkeDbProvider:
    base = Path(__file__).parent.parent
    return NikkeDbProvider(base / "data" / "cache", base / "assets")


@pytest.fixture(scope="module")
def character_master() -> list[dict]:
    p = Path(__file__).parent.parent / "assets" / "character_master.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("characters", [])


def test_all_default_characters_resolve(provider: NikkeDbProvider, character_master: list[dict]):
    assert len(character_master) == 200, f"Expected 200 characters in master, found {len(character_master)}"
    assets, manifest_path = get_manifest_assets()
    rendered_dir = get_rendered_dir()

    for char in character_master:
        res_id = char.get("resource_id")
        expected_spine = char.get("spine_asset_id")
        actual_spine = provider.resolve_render_id(res_id, 0)

        assert actual_spine != "missing", f"Character {char.get('name_cn')} ({res_id}) resolved to missing"
        assert actual_spine == expected_spine, f"Character {char.get('name_cn')} ({res_id}) expected {expected_spine}, got {actual_spine}"

        # Manifest check if manifest is available
        if assets is not None:
            assert actual_spine in assets, f"Default asset {actual_spine} not found in manifest {manifest_path}"
            if rendered_dir:
                entry = assets[actual_spine]
                png_name = entry.get("rendered_png", entry.get("png_file"))
                if png_name:
                    png_path = rendered_dir / png_name
                    if png_path.is_file():
                        with Image.open(png_path) as im:
                            assert im.size[0] > 0 and im.size[1] > 0
