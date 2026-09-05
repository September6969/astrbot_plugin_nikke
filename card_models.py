# SPDX-License-Identifier: GPL-3.0-or-later
"""单角色练度卡的数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass(slots=True)
class EquipmentOption:
    raw_type: str
    display_name: str
    value: float
    unit: str
    level: int | None = None


@dataclass(slots=True)
class EquipmentData:
    slot: str
    equipment_id: str | None = None
    level: int | None = None
    options: list[EquipmentOption] = field(default_factory=list)
    equipped: bool = False


@dataclass(slots=True)
class FavoriteItemData:
    tid: str | int | None
    level: int | None
    display_name: str | None = None


@dataclass(slots=True)
class CubeData:
    tid: str | int | None
    level: int | None
    display_name: str | None = None


@dataclass(slots=True)
class OptionSummary:
    display_name: str
    value: float
    unit: str


@dataclass(slots=True)
class CharacterCardData:
    commander_name: str
    fetched_at: str
    plugin_version: str

    name_code: str
    name_cn: str
    name_en: str
    resource_id: str | None

    rarity: str | None
    element: str | None
    weapon: str | None
    burst: str | int | None
    corporation: str | None

    level: int
    combat: int
    hp: int | None
    attack: int | None
    defense: int | None

    skill1_level: int
    skill2_level: int
    burst_skill_level: int

    grade: int
    core: int
    bond_level: int | None

    favorite_item: FavoriteItemData | None
    cube: CubeData | None
    equipment: dict[str, EquipmentData]
    option_totals: list[OptionSummary]


@dataclass(slots=True)
class CharacterCardAssets:
    portrait: Image.Image
    equipment: dict[str, Image.Image]
    favorite_item: Image.Image
    cube: Image.Image
    element: Image.Image
    corporation: Image.Image
    weapon: Image.Image
    burst: Image.Image


