# SPDX-License-Identifier: GPL-3.0-or-later
"""单角色练度卡的数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

@dataclass(frozen=True, slots=True)
class CostumeSelection:
    costume_id: int | str | None
    source: str
    kind: Literal["default", "alternate", "unknown"]


@dataclass(slots=True)
class EquipmentOption:
    raw_type: str
    display_name: str
    value: float
    unit: str
    level: int | None = None
    position: int | None = None
    option_id: str | None = None
    state_effect_id: str | None = None
    components: tuple["EquipmentOption", ...] = ()
    tier: int | None = None
    effect_group_id: str | None = None
    raw_value: int | None = None


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
    costume_id: int | str | None

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
    hp_source: str = "unavailable_missing_input"
    attack_source: str = "unavailable_missing_input"
    defense_source: str = "unavailable_missing_input"
    stat_calculation_reason: str | None = None
    spine_asset_id: str | None = None
    costume_selection: CostumeSelection | None = None
    base_ammo: int | None = None
    base_charge_seconds: str | None = None
    weapon_base_source: str | None = None


@dataclass(frozen=True, slots=True)
class CharacterCardRequest:
    """角色卡用例的显式输入，不暴露账号凭据或渲染资源。"""

    qq_id: str
    query: str
    directory: Sequence[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class CharacterCardResult:
    """角色卡用例的领域输出。"""

    card: CharacterCardData


@dataclass(slots=True)
class CharacterCardAssets:
    portrait: Any
    equipment: dict[str, Any]
    favorite_item: Any
    cube: Any
    element: Any
    corporation: Any
    weapon: Any
    burst: Any
    skills: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SpineAssetRef:
    """视觉 catalog 中 Spine 资源的逻辑路径描述（非可渲染 bundle）。

    PR-6B（G6-character-spine-c2）由 SpineBundle 更名，避免与
    integrations.spine.bundle.SpineBundle（可供 runtime 消费的本地文件 bundle）混淆。
    """

    skeleton: Path | str | None = None
    atlas: Path | str | None = None
    textures: list[Path | str] = field(default_factory=list)
    format: str | None = None  # "json" or "skel"
    bone_names: list[str] | None = None
    slot_names: list[str] | None = None
