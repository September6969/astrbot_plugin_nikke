# SPDX-License-Identifier: GPL-3.0-or-later
"""Costume schema v3 与 Scarlet Racer's High 的固定回归。"""

from __future__ import annotations

from pathlib import Path

from astrbot_plugin_nikke.costume_registry import CostumeRegistry
from astrbot_plugin_nikke.nikke_db_provider import NikkeDbProvider


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def test_scarlet_racers_high_is_verified_independent_costume() -> None:
    registry = CostumeRegistry(ASSETS)
    result = registry.resolve("110023", expected_resource_id=222)

    assert result.ok
    assert result.costume is not None
    assert result.costume.costume_name == "Racer's High"
    assert result.costume.spine_mode == "independent_asset"
    assert result.costume.spine_asset_id == "c222_01"
    assert result.costume.skin_name is None
    assert result.costume.render_id == "c222_01"


def test_scarlet_racers_high_owner_mismatch_is_rejected() -> None:
    result = CostumeRegistry(ASSETS).resolve("110023", expected_resource_id=10)
    assert not result.ok
    assert result.status == "OWNER_MISMATCH"


def test_costume_v3_render_id_does_not_fall_back_to_default(tmp_path: Path) -> None:
    provider = NikkeDbProvider(tmp_path, ASSETS)
    assert provider.resolve_character_id(222, "110023") == "c222_01"
    assert provider.resolve_render_id(222, "110023") == "c222_01"
    assert provider.resolve_render_id(222, "not-a-costume") == "missing"
