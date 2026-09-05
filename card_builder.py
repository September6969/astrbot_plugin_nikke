# SPDX-License-Identifier: GPL-3.0-or-later
"""把原始 CharacterDetails 构造成稳定的单角色卡数据。"""

from __future__ import annotations

import logging
from typing import Any

from .card_models import (
    CharacterCardData,
    CubeData,
    EquipmentData,
    EquipmentOption,
    FavoriteItemData,
    OptionSummary,
)


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


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _equipped_item(
    model_type,
    tid: Any,
    level: Any,
):
    if tid in (None, "", 0, "0"):
        return None
    return model_type(tid=tid, level=_optional_int(level))


class CharacterCardBuilder:
    """只依据原始槽位字段解析装备，不使用拍平后的 equipment_effects。"""

    @staticmethod
    def _option_from_function(function: dict[str, Any]) -> EquipmentOption:
        raw_type = str(function.get("function_type", "") or "Unknown")
        mapping = OPTION_NAMES.get(raw_type.casefold())
        raw_value = float(function.get("function_value", 0) or 0)
        value_type = str(function.get("function_value_type", "") or "").casefold()
        if mapping:
            display_name, unit = mapping
            if value_type and value_type != unit:
                logger.warning(
                    "function_value_type mismatch: type=%s value_type=%s expected=%s, treating as unknown",
                    raw_type, value_type, unit,
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
            level=_optional_int(function.get("level")),
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
                level=_optional_int(detail.get(f"{slot}_equip_lv")) if equipped else None,
                equipped=equipped,
            )
            for index in (1, 2, 3):
                if not equipped:
                    break
                effect_id = detail.get(f"{slot}_equip_option{index}_id")
                if effect_id in (None, "", 0, "0"):
                    continue
                effect = effects_map.get(str(effect_id), {})
                functions = effect.get("function_details", []) or []
                if not functions:
                    item.options.append(
                        EquipmentOption(
                            raw_type=str(effect_id),
                            display_name="未识别词条",
                            value=0,
                            unit="unknown",
                        )
                    )
                    continue
                for function in functions:
                    option = self._option_from_function(function)
                    item.options.append(option)
                    if option.unit in {"percent", "flat"}:
                        key = (option.display_name, option.unit)
                        totals[key] = totals.get(key, 0.0) + option.value
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
            name_cn=str(directory.get("name_cn", "") or "未知妮姬"),
            name_en=str(directory.get("name_en", "") or ""),
            resource_id=(
                str(directory.get("resource_id"))
                if directory.get("resource_id") not in (None, "")
                else None
            ),
            rarity=directory.get("rare"),
            element=directory.get("element"),
            weapon=directory.get("weapon"),
            burst=directory.get("burst"),
            corporation=directory.get("corporation"),
            level=int(roster.get("lv", detail.get("lv", 0)) or 0),
            combat=int(roster.get("combat", detail.get("combat", 0)) or 0),
            hp=_optional_int(detail.get("hp")),
            attack=_optional_int(detail.get("attack")),
            defense=_optional_int(detail.get("defense")),
            skill1_level=int(detail.get("skill1_lv", 0) or 0),
            skill2_level=int(detail.get("skill2_lv", 0) or 0),
            burst_skill_level=int(detail.get("ulti_skill_lv", 0) or 0),
            grade=int(roster.get("grade", detail.get("grade", 0)) or 0),
            core=int(roster.get("core", detail.get("core", 0)) or 0),
            bond_level=_optional_int(detail.get("attractive_lv")),
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
