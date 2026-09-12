# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression test for Eunhwa: Tactical Upgrade portrait resolution with Day Off skin TID 30049."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.card_models import CharacterCardData
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider


ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


def test_character_master_eunhwa_tactical_upgrade():
    resolver = CharacterMasterResolver(ASSETS_DIR / "character_master.json")
    char = resolver.resolve_resource_id(95)
    assert char is not None
    assert char.name_cn == "银华：战术升级"
    assert char.character_key == "eunhwa_tactical_upgrade"
    assert char.resource_id == 95
    assert char.name_code == 5149
    assert char.id == 209501
    assert char.battle_tid_prefix == 2095
    assert char.spine_asset_id == "c095"
    assert char.costume_id == 0
    assert char.default_costume_id is None

    # Resolve by battle_tid
    char_by_tid = resolver.resolve_battle_tid(209501)
    assert char_by_tid is not None
    assert char_by_tid.resource_id == 95

    # Resolve by name
    char_by_name = resolver.resolve_by_identifier("银华：战术升级")
    assert char_by_name is not None
    assert char_by_name.resource_id == 95

    # is_default_costume checks: 0, None, "", "0", "default" are default
    assert resolver.is_default_costume(95, 0) is True
    assert resolver.is_default_costume(95, None) is True
    assert resolver.is_default_costume(95, "") is True
    assert resolver.is_default_costume(95, "0") is True
    assert resolver.is_default_costume(95, "default") is True

    # 30049 is an alternate skin ("Day Off"), NOT default costume
    assert resolver.is_default_costume(95, 30049) is False
    assert resolver.is_default_costume(95, "30049") is False
    assert resolver.is_default_costume("c095", 30049) is False
    assert resolver.is_default_costume(95, "invalid") is False
    assert resolver.is_default_costume(222, 30049) is False


def test_nikke_db_provider_resolves_eunhwa_portraits(tmp_path):
    provider = NikkeDbProvider(tmp_path, ASSETS_DIR)

    # Default appearance (0, None, "0", "default") resolves to c095 (base military uniform)
    assert provider.resolve_render_id(95, None) == "c095"
    assert provider.resolve_render_id(95, 0) == "c095"
    assert provider.resolve_render_id(95, "0") == "c095"
    assert provider.resolve_render_id(95, "default") == "c095"
    assert provider.resolve_render_id("95", 0) == "c095"
    assert provider.resolve_render_id("c095", 0) == "c095"
    assert provider.resolve_character_id(95, 0) == "c095"
    assert provider.costume_cache_token(0, resource_id=95) == ("default", "default")
    assert provider.costume_cache_token(None, resource_id=95) == ("default", "default")

    # Alternate skin 30049 ("Day Off") resolves to c095_01 (independent Spine asset)
    assert provider.resolve_render_id(95, 30049) == "c095_01"
    assert provider.resolve_render_id(95, "30049") == "c095_01"
    assert provider.resolve_render_id("95", 30049) == "c095_01"
    assert provider.resolve_render_id("c095", 30049) == "c095_01"
    assert provider.resolve_character_id(95, 30049) == "c095_01"
    assert provider.costume_cache_token(30049, resource_id=95) == ("known", "known:30049:c095_01")
    assert provider.resolve_render_id(95, 30049) != "c095"

    # Non-default invalid/unknown costumes must return "missing" (never fall back to c095)
    assert provider.resolve_render_id(95, "invalid-skin") == "missing"
    assert provider.resolve_render_id(95, 999999) == "missing"

    # Other characters: 30049 does not belong to Marian (222)
    assert provider.resolve_render_id(222, 30049) == "missing"

    # Known alternate costume for Marian: Racer's High (110023 -> c222_01)
    assert provider.resolve_render_id(222, "110023") == "c222_01"
    assert provider.resolve_render_id(222, 110023) == "c222_01"
    assert provider.resolve_render_id(222, "not-a-costume") == "missing"


def test_asset_manager_portrait_resolution_with_manifest(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    rendered_dir = tmp_path / "spine-rendered"
    rendered_dir.mkdir()

    # Create dummy rendered PNG for c095 (504x892) and c095_01 (398x892)
    c095_img = Image.new("RGBA", (504, 892), (255, 0, 0, 255))
    c095_path = rendered_dir / "c095.png"
    c095_img.save(c095_path)

    c095_01_img = Image.new("RGBA", (398, 892), (0, 255, 0, 255))
    c095_01_path = rendered_dir / "c095_01.png"
    c095_01_img.save(c095_01_path)

    manifest_data = {
        "schema_version": 2,
        "assets": {
            "c095": {
                "runtime_version": "4.1",
                "rendered_png": "c095.png",
                "sha256": hashlib.sha256(c095_path.read_bytes()).hexdigest(),
                "width": 504,
                "height": 892,
                "bbox": [16, 16, 488, 876],
            },
            "c095_01": {
                "runtime_version": "4.1",
                "rendered_png": "c095_01.png",
                "sha256": hashlib.sha256(c095_01_path.read_bytes()).hexdigest(),
                "width": 398,
                "height": 892,
                "bbox": [16, 16, 382, 876],
            },
        },
    }
    manifest_path = tmp_path / "spine-manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    manager = AssetManager(
        cache_dir,
        ASSETS_DIR,
        remote=False,
        spine_manifest_path=manifest_path,
        spine_rendered_dir=rendered_dir,
    )

    # 1. Default portrait (costume_id=0 or None) -> c095 (504x892)
    default_portrait = manager.get_character_portrait(5149, 95, 0)
    assert default_portrait is not None
    assert default_portrait.size == (504, 892)

    # 2. Alternate skin portrait (costume_id=30049) -> c095_01 (398x892)
    skin_portrait = manager.get_character_portrait(5149, 95, 30049)
    assert skin_portrait is not None
    assert skin_portrait.size == (398, 892)

    # 3. Unknown skin (costume_id=999999) -> placeholder (600x900), NEVER default c095 or c095_01
    placeholder_portrait = manager.get_character_portrait(5149, 95, 999999)
    assert placeholder_portrait is not None
    assert placeholder_portrait.size == (600, 900)
    assert placeholder_portrait.size != (504, 892)
    assert placeholder_portrait.size != (398, 892)

    # 4. resolve_character_assets with card data for Day Off
    card_data = CharacterCardData(
        commander_name="Test",
        fetched_at="2026-09-12 12:00:00",
        plugin_version="0.3.0",
        name_code="5149",
        name_cn="银华：战术升级",
        name_en="Eunhwa: Tactical Upgrade",
        resource_id="95",
        costume_id=30049,
        rarity="SSR",
        element="Fire",
        weapon="SR",
        burst="III",
        corporation="Elysion",
        level=1,
        combat=0,
        hp=0,
        attack=0,
        defense=0,
        skill1_level=1,
        skill2_level=1,
        burst_skill_level=1,
        grade=0,
        core=0,
        bond_level=None,
        favorite_item=None,
        cube=None,
        equipment={},
        option_totals={},
    )
    resolved = manager.resolve_character_assets(card_data, timeout=5.0)
    assert resolved.portrait is not None
    assert resolved.portrait.size == (398, 892)
    manager.close()
