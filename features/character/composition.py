# SPDX-License-Identifier: GPL-3.0-or-later
"""角色卡构建器的注册表与未知词条观察器装配入口。"""

from __future__ import annotations

from pathlib import Path

from .builder import CharacterCardBuilder
from .builder import UnknownOptionObserver
from .ol_unknown_inventory import UnknownOlInventory
from .registries.overload import OverloadTierRegistry
from .registries.state_effect import StateEffectRegistry


def create_character_card_builder(
    plugin_dir: str | Path,
    *,
    unknown_ol_inventory_path: str | Path | None = None,
) -> CharacterCardBuilder:
    """从插件资产目录装载已核验词条表，并在装配期整理观察记录。"""
    assets_dir = Path(plugin_dir) / "assets"
    data_dir = assets_dir / "data"

    def registry_path(name: str) -> Path:
        for candidate in (data_dir / name, assets_dir / name):
            if candidate.is_file():
                return candidate
        return data_dir / name

    state_effect_registry = StateEffectRegistry.from_file(
        registry_path("state_effects.json")
    )
    overload_tier_registry = OverloadTierRegistry.from_file(
        registry_path("overload_tiers.json")
    )
    inventory: UnknownOptionObserver | None = None
    if unknown_ol_inventory_path is not None:
        concrete_inventory = UnknownOlInventory(unknown_ol_inventory_path)
        concrete_inventory.prune_known({
            entry.state_effect_id
            for entry in overload_tier_registry.entries
            if entry.state_effect_id is not None
        })
        inventory = concrete_inventory
    return CharacterCardBuilder(
        state_effect_registry=state_effect_registry,
        overload_tier_registry=overload_tier_registry,
        unknown_ol_inventory=inventory,
    )
