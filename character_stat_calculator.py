# SPDX-License-Identifier: GPL-3.0-or-later
"""基于已核验静态表和真实玩家输入的 HP/ATK/DEF 计算器。

计算器故意不内置猜测常量。没有完整、带来源的静态表，或玩家输入缺少任一
必需字段时，三项结果全部返回 ``None``，并标记为 ``unavailable_missing_input``。
这样不会把战力、等级或部分装备数据伪装成真实属性。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping


class StatCalculationError(ValueError):
    """计算输入或静态表不完整。"""


@dataclass(frozen=True, slots=True)
class CharacterStatTables:
    """ExiaInvasion 兼容的静态表快照；只有 verified 才允许计算。"""

    level_stats: Mapping[str, Any]
    research_table: Any
    attractive_table: Any
    equipment_table: Any
    cube_records: Mapping[str, Any] = field(default_factory=dict)
    favorite_records: Mapping[str, Any] = field(default_factory=dict)
    cube_catalog: Mapping[str, Any] | None = None
    verified: bool = False
    source_ref: str = ""
    checked_at: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CharacterStatTables":
        if not isinstance(data, Mapping):
            raise StatCalculationError("静态表容器无效")
        return cls(
            level_stats=data.get("level_stats"),
            research_table=data.get("research_table"),
            attractive_table=data.get("attractive_table"),
            equipment_table=data.get("equipment_table"),
            cube_records=data.get("cube_records") or {},
            favorite_records=data.get("favorite_records") or {},
            cube_catalog=data.get("cube_catalog"),
            verified=data.get("status") == "VERIFIED_STATIC_RESOURCES" or data.get("verified") is True,
            source_ref=str(data.get("source_ref") or ""),
            checked_at=str(data.get("checked_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class CharacterStatResult:
    hp: int | None
    attack: int | None
    defense: int | None
    hp_source: str
    attack_source: str
    defense_source: str
    reason: str | None = None


class CharacterStatCalculator:
    """复现公开计算顺序，并对缺失输入采用全量失败策略。"""

    SOURCE_CALCULATED = "calculated_verified"
    SOURCE_UNAVAILABLE = "unavailable_missing_input"
    _RESEARCH_IDS = {
        "general": "1001",
        "attacker": "1101",
        "defender": "1102",
        "supporter": "1103",
        "elysion": "1201",
        "missilis": "1202",
        "tetra": "1203",
        "pilgrim": "1204",
        "abnormal": "1205",
    }
    _CORPORATIONS = {
        1: "ELYSION",
        2: "MISSILIS",
        3: "TETRA",
        4: "PILGRIM",
        7: "ABNORMAL",
    }
    _STAT_SPECS = (
        ("hp", "grade_hp", "core_hp", "hp", "hp_rate", "Hp", "hp"),
        ("atk", "grade_attack", "core_attack", "attack", "attack_rate", "Atk", "atk"),
        ("def", "grade_defence", "core_defence", "defence", "defence_rate", "Defence", "def"),
    )

    def __init__(self, tables: CharacterStatTables | None = None):
        self.tables = tables

    @classmethod
    def unavailable(cls, reason: str) -> CharacterStatResult:
        return CharacterStatResult(
            None,
            None,
            None,
            cls.SOURCE_UNAVAILABLE,
            cls.SOURCE_UNAVAILABLE,
            cls.SOURCE_UNAVAILABLE,
            reason,
        )

    @staticmethod
    def _finite(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise StatCalculationError(f"{label} 缺失或非法")
        return float(value)

    @classmethod
    def _nonnegative_int(cls, value: Any, label: str) -> int:
        number = cls._finite(value, label)
        if number != int(number) or number < 0:
            raise StatCalculationError(f"{label} 必须是非负整数")
        return int(number)

    @classmethod
    def _corporation(cls, value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and float(value).is_integer():
            return cls._CORPORATIONS.get(int(value))
        normalized = str(value or "").strip().upper()
        if normalized.isdigit():
            return cls._CORPORATIONS.get(int(normalized))
        return normalized if normalized in set(cls._CORPORATIONS.values()) else None

    @staticmethod
    def _records(value: Any, label: str) -> list[Mapping[str, Any]]:
        records = value if isinstance(value, list) else value.get("records") if isinstance(value, Mapping) else None
        if not isinstance(records, list) or not records:
            raise StatCalculationError(f"{label} 静态表为空")
        if not all(isinstance(record, Mapping) for record in records):
            raise StatCalculationError(f"{label} 静态表记录非法")
        return records

    @classmethod
    def _indexed(cls, record: Mapping[str, Any] | None, key: str, index: int, label: str) -> int:
        if not record:
            return 0
        values = record.get(key)
        if not isinstance(values, list) or not 0 <= index < len(values):
            raise StatCalculationError(f"{label} {key}[{index}] 缺失")
        return cls._js_round(cls._finite(values[index], f"{label} {key}[{index}]"))

    @staticmethod
    def _js_round(value: float) -> int:
        """复现正数场景下 JavaScript Math.round 的半入规则。"""
        return math.floor(value + 0.5)

    def calculate(self, inputs: Mapping[str, Any], tables: CharacterStatTables | None = None) -> CharacterStatResult:
        active = tables or self.tables
        if active is None or not active.verified:
            return self.unavailable("没有 VERIFIED_STATIC_RESOURCES 静态表")
        try:
            if not isinstance(inputs, Mapping):
                raise StatCalculationError("角色计算输入不完整")
            class_name = str(inputs.get("class_name") or "")
            corporation = self._corporation(inputs.get("corporation"))
            weapon_type = str(inputs.get("weapon_type") or "").strip().upper()
            if class_name not in {"Attacker", "Defender", "Supporter"} or corporation is None or not weapon_type:
                raise StatCalculationError("角色职业、企业或武器输入缺失")
            level = self._nonnegative_int(inputs.get("level"), "同步器等级")
            if level < 1:
                raise StatCalculationError("同步器等级必须大于 0")
            grade_raw = self._nonnegative_int(inputs.get("grade"), "突破等级")
            core_raw = self._nonnegative_int(inputs.get("core"), "核心强化等级")
            total = min(10, grade_raw + core_raw)
            grade, core = min(3, total), max(0, total - 3)
            research_levels = inputs.get("research_levels")
            if not isinstance(research_levels, Mapping):
                raise StatCalculationError("研究等级缺失")
            research_records = {str(row.get("id")): row for row in self._records(active.research_table, "研究")}
            required = ("general", class_name.casefold(), corporation.casefold())
            research_rows = []
            for key in required:
                tid = self._RESEARCH_IDS.get(key)
                if tid is None or tid not in research_records:
                    raise StatCalculationError(f"缺少 {key} 研究静态记录")
                research_rows.append((key, research_records[tid]))
                self._nonnegative_int(research_levels.get(key), f"{key} 研究等级")

            attractive_level = self._nonnegative_int(inputs.get("bond_level", 0), "好感度等级")
            attractive_row = None
            if attractive_level:
                attractive_row = next(
                    (row for row in self._records(active.attractive_table, "好感度")
                     if row.get("attractive_level") == attractive_level),
                    None,
                )
                if attractive_row is None:
                    raise StatCalculationError(f"缺少好感度 {attractive_level} 静态记录")

            level_stats = active.level_stats
            if not isinstance(level_stats, Mapping) or not isinstance(level_stats.get("statEnhance"), Mapping):
                raise StatCalculationError("等级曲线静态表无效")
            enhance = level_stats["statEnhance"]
            equipment_records = {str(row.get("id")): row for row in self._records(active.equipment_table, "装备")}
            raw_equipment = inputs.get("equipment")
            if not isinstance(raw_equipment, list) or len(raw_equipment) != 4:
                raise StatCalculationError("四件装备输入不完整")

            result: dict[str, int] = {}
            for stat, grade_key, core_key, research_key, attractive_suffix, equipment_type, resource_key in self._STAT_SPECS:
                curve = self._curve_with_level(level_stats, class_name, weapon_type, stat, level)
                grade_ratio = self._finite(enhance.get("grade_ratio"), "突破比例")
                grade_fixed = self._finite(enhance.get(grade_key), grade_key)
                core_ratio = self._finite(enhance.get(core_key), core_key)
                character_value = math.floor(curve * (1 + grade * grade_ratio / 10000) + grade * grade_fixed)
                research_value = 0.0
                for key, row in research_rows:
                    research_value += self._nonnegative_int(research_levels.get(key), f"{key} 研究等级") * self._finite(
                        row.get(research_key), f"{key} 研究 {research_key}"
                    )
                research_value = math.floor(research_value)
                attractive_key = f"{class_name.casefold()}_{attractive_suffix}"
                attractive_value = self._js_round(self._finite(attractive_row.get(attractive_key), f"好感度 {attractive_key}")) if attractive_row else 0
                core_value = self._js_round((character_value + research_value + attractive_value) * (1 + core * core_ratio / 10000))
                equipment_value = 0
                for index, equipment in enumerate(raw_equipment, 1):
                    if not isinstance(equipment, Mapping):
                        raise StatCalculationError(f"第 {index} 件装备输入非法")
                    tid = equipment.get("tid")
                    if tid in (None, "", 0, "0"):
                        continue
                    equipment_level = self._nonnegative_int(equipment.get("level"), f"第 {index} 件装备等级")
                    if "corporation_type" not in equipment:
                        raise StatCalculationError(f"第 {index} 件装备企业类型缺失")
                    # 现场合同中的 0 表示没有企业加成；Exia 也会将其归一化为 null 后加成 0。
                    equipment_corporation = self._corporation(equipment.get("corporation_type"))
                    record = equipment_records.get(str(tid))
                    if record is None or not isinstance(record.get("stat"), list):
                        raise StatCalculationError(f"装备 {tid} 静态记录缺失")
                    base_value = sum(
                        self._finite(entry.get("stat_value"), f"装备 {tid} {equipment_type}")
                        for entry in record["stat"]
                        if isinstance(entry, Mapping) and entry.get("stat_type") == equipment_type
                    )
                    corporation_bonus = 0.3 if equipment_corporation == corporation else 0
                    equipment_value += self._js_round(base_value * (1 + corporation_bonus + equipment_level * 0.1))
                cube = inputs.get("cube") or {}
                cube_record = active.cube_records.get(str(cube.get("tid"))) if isinstance(cube, Mapping) else None
                cube_value = self._indexed(cube_record, resource_key, self._nonnegative_int(cube.get("level", 0), "魔方等级") - 1, f"魔方 {cube.get('tid')}") if cube.get("tid") not in (None, "", 0, "0") else 0
                favorite = inputs.get("favorite_item") or {}
                favorite_record = active.favorite_records.get(str(favorite.get("tid"))) if isinstance(favorite, Mapping) else None
                favorite_value = self._indexed(favorite_record, resource_key, self._nonnegative_int(favorite.get("level", 0), "珍藏品等级"), f"珍藏品 {favorite.get('tid')}") if favorite.get("tid") not in (None, "", 0, "0") else 0
                result[stat] = core_value + equipment_value + cube_value + favorite_value
            return CharacterStatResult(
                result["hp"], result["atk"], result["def"],
                self.SOURCE_CALCULATED, self.SOURCE_CALCULATED, self.SOURCE_CALCULATED,
            )
        except (KeyError, TypeError, StatCalculationError) as exc:
            return self.unavailable(str(exc))

    @classmethod
    def _curve_with_level(cls, level_stats, class_name, weapon_type, stat, level):
        class_curves = (level_stats.get("curves") or {}).get(class_name.casefold())
        if not isinstance(class_curves, Mapping):
            raise StatCalculationError(f"{class_name} 等级曲线缺失")
        values = class_curves.get(stat) if stat != "def" else (class_curves.get("defByWeapon") or {}).get(weapon_type.upper())
        if not isinstance(values, list) or not 1 <= level <= len(values):
            raise StatCalculationError(f"{class_name}/{weapon_type} {stat} 等级曲线缺失")
        return cls._finite(values[level - 1], f"{stat} 等级曲线")

    def calculate_from_payload(
        self,
        *,
        account: Mapping[str, Any],
        directory: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> CharacterStatResult:
        roster = payload.get("roster_item") or {}
        detail = payload.get("detail") or {}
        equipment = payload.get("raw_equipments") or detail.get("raw_equipments")
        if equipment is None:
            equipment = [
                {
                    "tid": detail.get(f"{slot}_equip_tid"),
                    "level": detail.get(f"{slot}_equip_lv"),
                    "corporation_type": detail.get(f"{slot}_equip_corporation_type"),
                }
                for slot in ("head", "torso", "arm", "leg")
            ]
        tables = self.tables
        if tables is None and isinstance(payload.get("stat_tables"), Mapping):
            try:
                tables = CharacterStatTables.from_mapping(payload["stat_tables"])
            except StatCalculationError as exc:
                return self.unavailable(str(exc))
        return self.calculate(
            {
                "class_name": directory.get("class") or directory.get("class_name"),
                "corporation": directory.get("corporation"),
                "weapon_type": directory.get("weapon_type") or directory.get("weapon"),
                "level": roster.get("lv", detail.get("lv")),
                "grade": roster.get("grade", detail.get("grade")),
                "core": roster.get("core", detail.get("core")),
                "bond_level": detail.get("attractive_lv", 0),
                "research_levels": payload.get("research_levels") or account.get("research_levels"),
                "equipment": equipment,
                "cube": {"tid": detail.get("harmony_cube_tid"), "level": detail.get("harmony_cube_lv")},
                "favorite_item": {"tid": detail.get("favorite_item_tid"), "level": detail.get("favorite_item_lv")},
            },
            tables,
        )
