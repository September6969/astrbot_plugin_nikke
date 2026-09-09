# SPDX-License-Identifier: GPL-3.0-or-later
"""把原始 CharacterDetails 构造成稳定的单角色卡数据。"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from .card_models import (
    CharacterCardData,
    CubeData,
    EquipmentData,
    EquipmentOption,
    FavoriteItemData,
    OptionSummary,
)
from .character_identity import CharacterDirectoryResolver
from .log_privacy import sanitize_log_text
from .state_effect_registry import StateEffectRegistry


SLOTS = ("head", "torso", "arm", "leg")
OPTION_NAMES = {
    "statatk": ("攻击力增加", "percent"),
    "incelementdmg": ("优越代码伤害增加", "percent"),
    "statammoload": ("最大装弹数增加", "percent"),
    "statcriticaldamage": ("暴击伤害增加", "percent"),
    "statchargetime": ("蓄力速度增加", "percent"),
    "stathitrate": ("命中率增加", "percent"),
    "stataccuracy": ("命中率增加", "percent"),
    "statchargedamage": ("蓄力伤害增加", "percent"),
    "chargedamage": ("蓄力伤害增加", "percent"),
    "statcritical": ("暴击率增加", "percent"),
    "statcriticalrate": ("暴击率增加", "percent"),
    "statdef": ("防御力增加", "percent"),
    "statdefense": ("防御力增加", "percent"),
}

logger = logging.getLogger(__name__)
_INTEGER_LITERAL = re.compile(r"^[+-]?\d+$")


def _optional_int(value: Any, *, minimum: int | None = None) -> int | None:
    """只接受 JSON 整数或十进制整数字符串，异常值返回未知。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not _INTEGER_LITERAL.fullmatch(text):
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
    else:
        return None
    if minimum is not None and parsed < minimum:
        return None
    return parsed


def _optional_finite_float(value: Any) -> float | None:
    """解析动态词条数值并拒绝布尔、NaN、Infinity 和非标量。"""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _zero_if_invalid(value: Any) -> int:
    parsed = _optional_int(value, minimum=0)
    return 0 if parsed is None else parsed


def _equipped_item(
    model_type,
    tid: Any,
    level: Any,
):
    if tid in (None, "", 0, "0"):
        return None
    return model_type(tid=tid, level=_optional_int(level, minimum=0))


class CharacterCardBuilder:
    """只依据原始槽位字段解析装备，不使用拍平后的 equipment_effects。"""

    def __init__(self, state_effect_registry: StateEffectRegistry | None = None):
        self.state_effect_registry = state_effect_registry or StateEffectRegistry.from_file(
            Path(__file__).parent / "assets" / "state_effects.json"
        )

    @staticmethod
    def _option_from_function(function: dict[str, Any]) -> EquipmentOption:
        raw_type = str(function.get("function_type", "") or "Unknown")
        mapping = OPTION_NAMES.get(raw_type.casefold())
        raw_value = _optional_finite_float(function.get("function_value"))
        if raw_value is None:
            return EquipmentOption(
                raw_type=raw_type,
                display_name="未识别词条",
                value=0,
                unit="unknown",
                level=_optional_int(function.get("level"), minimum=0),
            )
        value_type = str(function.get("function_value_type", "") or "").casefold()
        if mapping:
            display_name, unit = mapping
            if value_type and value_type != unit:
                logger.warning(
                    "function_value_type mismatch: type=%s value_type=%s expected=%s, treating as unknown",
                    sanitize_log_text(raw_type, max_length=80),
                    sanitize_log_text(value_type, max_length=80),
                    sanitize_log_text(unit, max_length=80),
                )
                display_name = "未识别词条"
                unit = "unknown"
                value = abs(raw_value)
            else:
                value = abs(raw_value) / 10000 if unit == "percent" else abs(raw_value)
        else:
            display_name = "未识别词条"
            unit = "unknown"
            value = abs(raw_value)
        return EquipmentOption(
            raw_type=raw_type,
            display_name=display_name,
            value=value,
            unit=unit,
            level=_optional_int(function.get("level"), minimum=0),
        )

    def _option_from_function_with_registry(
        self,
        function: dict[str, Any],
        *,
        option_id: Any,
    ) -> EquipmentOption:
        """有来源 registry 时使用其 label/formatter，否则保留旧合同。"""
        raw_type = str(function.get("function_type", "") or "Unknown")
        metadata = self.state_effect_registry.resolve(option_id, raw_type)
        if metadata is None:
            return self._option_from_function(function)
        value, unit = metadata.format_value(function.get("function_value", 0))
        return EquipmentOption(
            raw_type=raw_type,
            display_name=metadata.label,
            value=value,
            unit=unit,
            level=_optional_int(function.get("level"), minimum=0),
        )

    def _option_from_effect(
        self,
        *,
        effect_id: Any,
        functions: list[Any],
        position: int,
    ) -> EquipmentOption:
        """把一个 option 固定为一行，多 function detail 不再拆成多个槽位。"""
        option_id = str(effect_id) if effect_id not in (None, "", 0, "0") else None
        valid_functions = [item for item in functions if isinstance(item, dict)]
        if not valid_functions:
            return EquipmentOption(
                raw_type=f"option{position}",
                display_name="空槽" if option_id is None else "未识别词条",
                value=0,
                unit="empty" if option_id is None else "unknown",
                position=position,
                option_id=option_id,
                state_effect_id=option_id,
            )

        components = tuple(
            self._option_from_function_with_registry(item, option_id=option_id)
            for item in valid_functions
        )
        if len(components) == 1:
            primary = components[0]
            return EquipmentOption(
                raw_type=primary.raw_type,
                display_name=primary.display_name,
                value=primary.value,
                unit=primary.unit,
                level=primary.level,
                position=position,
                option_id=option_id,
                state_effect_id=option_id,
                components=components,
            )

        names = list(dict.fromkeys(
            component.display_name
            for component in components
            if component.display_name != "未识别词条"
        ))
        return EquipmentOption(
            raw_type=option_id or f"option{position}",
            display_name=" / ".join(names) if names else "未识别词条",
            value=0,
            unit="composite",
            position=position,
            option_id=option_id,
            state_effect_id=option_id,
            components=components,
        )

    def build(
        self,
        *,
        account: dict[str, Any],
        directory: dict[str, Any],
        payload: dict[str, Any],
        fetched_at: str,
        plugin_version: str,
    ) -> CharacterCardData:
        roster = payload.get("roster_item", {}) or {}
        detail = payload.get("detail", {}) or {}
        effects_map = {
            str(effect.get("id")): effect
            for effect in (payload.get("state_effects", []) or [])
        }
        equipment: dict[str, EquipmentData] = {}
        totals: dict[tuple[str, str], float] = {}

        for slot in SLOTS:
            equipment_id = detail.get(f"{slot}_equip_tid")
            equipped = equipment_id not in (None, "", 0, "0")
            item = EquipmentData(
                slot=slot,
                equipment_id=str(equipment_id) if equipped else None,
                level=_optional_int(detail.get(f"{slot}_equip_lv"), minimum=0) if equipped else None,
                equipped=equipped,
            )
            for index in (1, 2, 3):
                if not equipped:
                    break
                effect_id = detail.get(f"{slot}_equip_option{index}_id")
                effect = effects_map.get(str(effect_id), {})
                functions = effect.get("function_details", []) or []
                option = self._option_from_effect(
                    effect_id=effect_id,
                    functions=functions,
                    position=index,
                )
                item.options.append(option)
                for component in option.components or (option,):
                    if component.unit in {"percent", "flat"}:
                        key = (component.display_name, component.unit)
                        totals[key] = totals.get(key, 0.0) + component.value
            equipment[slot] = item

        option_totals = [
            OptionSummary(display_name=name, unit=unit, value=value)
            for (name, unit), value in totals.items()
        ]
        commander_name = str(
            account.get("nickname")
            or account.get("role_name")
            or "指挥官"
        )
        return CharacterCardData(
            commander_name=commander_name,
            fetched_at=fetched_at,
            plugin_version=plugin_version,
            name_code=str(directory.get("name_code", roster.get("name_code", ""))),
            name_cn=CharacterDirectoryResolver.display_name(directory),
            name_en=str(directory.get("name_en", "") or ""),
            resource_id=(
                str(directory.get("resource_id"))
                if directory.get("resource_id") not in (None, "")
                else None
            ),
            costume_id=roster.get("costume_id", detail.get("costume_id")),
            rarity=directory.get("rare"),
            element=directory.get("element"),
            weapon=directory.get("weapon"),
            burst=directory.get("burst"),
            corporation=directory.get("corporation"),
            level=_zero_if_invalid(roster.get("lv", detail.get("lv", 0))),
            combat=_zero_if_invalid(roster.get("combat", detail.get("combat", 0))),
            hp=_optional_int(detail.get("hp"), minimum=0),
            attack=_optional_int(detail.get("attack"), minimum=0),
            defense=_optional_int(detail.get("defense"), minimum=0),
            skill1_level=_zero_if_invalid(detail.get("skill1_lv", 0)),
            skill2_level=_zero_if_invalid(detail.get("skill2_lv", 0)),
            burst_skill_level=_zero_if_invalid(detail.get("ulti_skill_lv", 0)),
            grade=_zero_if_invalid(roster.get("grade", detail.get("grade", 0))),
            core=_zero_if_invalid(roster.get("core", detail.get("core", 0))),
            bond_level=_optional_int(detail.get("attractive_lv"), minimum=0),
            favorite_item=_equipped_item(
                FavoriteItemData,
                detail.get("favorite_item_tid"),
                detail.get("favorite_item_lv"),
            ),
            cube=_equipped_item(
                CubeData,
                detail.get("harmony_cube_tid"),
                detail.get("harmony_cube_lv"),
            ),
            equipment=equipment,
            option_totals=option_totals,
        )
