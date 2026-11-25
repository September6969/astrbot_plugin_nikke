# SPDX-License-Identifier: GPL-3.0-or-later
"""前哨基地产量、资源箱折算、战术学院加成与已绑定账号同步器上下文提取。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .cost_table import RESOURCES, SyncCostTable, SyncCostTableError

CASE_HOURS: tuple[int, ...] = (1, 2, 4, 8, 12, 24)
ACADEMY_MAX_BOOSTS: dict[str, float] = {
    "credits": 60.0,
    "battle_data": 45.0,
    "core_dust": 45.0,
}
OUTPOST_RATIOS: dict[str, int] = {
    "credits": 3,
    "battle_data": 3,
    "core_dust": 1,
}
_CURRENCY_TYPE_MAP = {
    3000: "core_dust",
    2000: "credits",
    1000: "battle_data",
}
_CURRICULUM_LESSON_BONUS: tuple[tuple[int, str, float], ...] = (
    (2002, "credits", 10.0),
    (2003, "battle_data", 10.0),
    (3002, "credits", 10.0),
    (3003, "core_dust", 10.0),
    (5002, "credits", 10.0),
    (6002, "battle_data", 15.0),
    (7002, "credits", 10.0),
    (7003, "core_dust", 15.0),
    (8002, "credits", 10.0),
    (9001, "credits", 10.0),
    (9002, "battle_data", 20.0),
    (9003, "core_dust", 20.0),
)


@dataclass(frozen=True, slots=True)
class OutpostRateRow:
    """单个前哨等级的原始每分钟分子值。"""

    level: int
    credits: float
    battle_data: float
    core_dust: float


@dataclass(frozen=True, slots=True)
class OutpostRateResult:
    """给定前哨等级与学院加成后的每小时与基础每日产量。"""

    outpost_level: int
    hourly: dict[str, float]
    base_daily: dict[str, float]
    academy_boosts: dict[str, float]
    academy_note: str
    estimated_above_400: bool
    rate_note: str


@dataclass(frozen=True, slots=True)
class AccountSyncContext:
    """从已绑定账号 profile 与本地静态表提取出的同步器状态摘要。"""

    synchro_level: int | None
    outpost_level: int | None
    academy_class: int | None
    academy_lesson: int | None
    academy_boosts: dict[str, float]
    academy_note: str
    inventory: dict[str, int]
    outpost_rates: OutpostRateResult | None
    gainable_levels: int | None
    reachable_level: int | None
    remaining_inventory: dict[str, int] | None
    next_level_cost: dict[str, int] | None
    next_level_missing: dict[str, int] | None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_boost_pct(value: Any, field: str, default: float) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise SyncCostTableError(f"{field} 必须是非负数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SyncCostTableError(f"{field} 必须是数字") from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > 300:
        raise SyncCostTableError(f"{field} 必须在 0–300 之间")
    return parsed


def normalize_academy_boosts(
    boosts: Mapping[str, Any] | None,
    *,
    defaults: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """规范化三项资源的战术学院百分比加成。"""
    base = dict(defaults or ACADEMY_MAX_BOOSTS)
    if boosts is None:
        return base
    if not isinstance(boosts, Mapping):
        raise SyncCostTableError("战术学院加成必须是对象")
    return {
        resource: _parse_boost_pct(
            boosts.get(resource),
            f"academy_boosts.{resource}",
            base[resource],
        )
        for resource in RESOURCES
    }


def infer_academy_boosts(
    academy_class: Any,
    academy_lesson: Any = None,
) -> tuple[dict[str, float], str]:
    """根据 BlaBlaLink 返回的战术学院班级/课程编号精确计算产量加成百分比。"""
    raw_class = _parse_int(academy_class)
    raw_lesson = _parse_int(academy_lesson)
    if (raw_class is None or raw_class <= 0) and (raw_lesson is None or raw_lesson <= 0):
        return (
            dict(ACADEMY_MAX_BOOSTS),
            "战术学院字段缺失，按满级加成估算（信用点+60% / 战斗数据+45% / 芯尘+45%，可手动调整）",
        )
    class_num = (
        (raw_class // 1000 if raw_class >= 1000 else raw_class)
        if raw_class
        else (raw_lesson // 1000 if raw_lesson and raw_lesson >= 1000 else 1)
    )
    if raw_lesson is not None and raw_lesson >= 1000:
        effective_lesson = raw_lesson
    elif raw_lesson is not None and 1 <= raw_lesson <= 99:
        effective_lesson = class_num * 1000 + raw_lesson
    else:
        effective_lesson = class_num * 1000 + 99

    if class_num >= 10 or effective_lesson >= 9003:
        return (
            dict(ACADEMY_MAX_BOOSTS),
            f"战术学院已满级加成（Class {class_num}，信用点+60% / 战斗数据+45% / 芯尘+45%）",
        )

    boosts = {res: 0.0 for res in RESOURCES}
    for lesson_id, resource, delta in _CURRICULUM_LESSON_BONUS:
        if lesson_id <= effective_lesson:
            boosts[resource] += delta
    return (
        boosts,
        f"战术学院 Class {class_num} / 课程 {effective_lesson} 精确加成（信用点+{boosts['credits']:g}% / 战斗数据+{boosts['battle_data']:g}% / 芯尘+{boosts['core_dust']:g}%）",
    )


@dataclass(frozen=True, slots=True)
class OutpostRateTable:
    """前哨基地防御产量表（支持 Lv.1–400 查表与 Lv.>400 线性曲线外推）。"""

    rows: tuple[OutpostRateRow, ...]
    source_url: str
    checked_at: str
    divisor: int = 10000
    label: str = "前哨基地防御产量表"

    @property
    def max_level(self) -> int:
        return self.rows[-1].level if self.rows else 0

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        source_url: str,
        checked_at: str,
        divisor: int = 10000,
        label: str = "前哨基地防御产量表",
    ) -> "OutpostRateTable":
        rows: list[OutpostRateRow] = []
        seen: set[int] = set()
        for index, rec in enumerate(records):
            if not isinstance(rec, Mapping):
                raise SyncCostTableError(f"outpost levels[{index}] 必须是对象")
            level = _parse_int(rec.get("level"))
            if level is None or not 1 <= level <= 2000:
                raise SyncCostTableError(f"outpost levels[{index}].level 无效")
            if level in seen:
                raise SyncCostTableError(f"前哨等级重复：{level}")
            seen.add(level)
            values: dict[str, float] = {}
            for res in RESOURCES:
                raw = rec.get(res)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
                    raise SyncCostTableError(f"outpost levels[{index}].{res} 无效")
                values[res] = float(raw)
            rows.append(
                OutpostRateRow(
                    level=level,
                    credits=values["credits"],
                    battle_data=values["battle_data"],
                    core_dust=values["core_dust"],
                )
            )
        if not rows:
            raise SyncCostTableError("前哨产量表为空")
        rows.sort(key=lambda r: r.level)
        if not isinstance(divisor, int) or isinstance(divisor, bool) or divisor <= 0:
            raise SyncCostTableError("前哨产量 divisor 必须是正整数")
        return cls(
            rows=tuple(rows),
            source_url=str(source_url or "").strip(),
            checked_at=str(checked_at or "").strip(),
            divisor=divisor,
            label=str(label or "前哨基地防御产量表").strip(),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "OutpostRateTable":
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SyncCostTableError(f"前哨产量表无法读取：{target.name}") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SyncCostTableError("前哨产量表不是合法 UTF-8 JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            raise SyncCostTableError("前哨产量表 schema_version 必须为 1")
        levels = payload.get("levels")
        if not isinstance(levels, list):
            raise SyncCostTableError("前哨产量表 levels 必须是数组")
        return cls.from_records(
            levels,
            source_url=str(payload.get("source_url") or ""),
            checked_at=str(payload.get("checked_at") or ""),
            divisor=int(payload.get("divisor") or 10000),
            label=str(payload.get("label") or "前哨基地防御产量表"),
        )

    def _raw_row_for(self, outpost_level: int) -> tuple[OutpostRateRow, bool]:
        by_level = {row.level: row for row in self.rows}
        if outpost_level in by_level:
            return by_level[outpost_level], False
        last = self.rows[-1]
        if outpost_level < self.rows[0].level:
            return self.rows[0], True
        if outpost_level <= last.level:
            nearest = min(self.rows, key=lambda r: abs(r.level - outpost_level))
            return nearest, False
        # Lv.>400 按末尾区间平均增量线性外推（社区前哨增长斜率平滑缓减）。
        tail = self.rows[-11:] if len(self.rows) >= 11 else self.rows
        span = max(1, tail[-1].level - tail[0].level)
        extra_levels = outpost_level - last.level
        extrapolated = {}
        for res in RESOURCES:
            slope = (getattr(tail[-1], res) - getattr(tail[0], res)) / span
            extrapolated[res] = getattr(last, res) + max(0.0, slope) * extra_levels
        return (
            OutpostRateRow(
                level=outpost_level,
                credits=extrapolated["credits"],
                battle_data=extrapolated["battle_data"],
                core_dust=extrapolated["core_dust"],
            ),
            True,
        )

    def hourly_rates(
        self,
        outpost_level: Any,
        *,
        academy_boosts: Mapping[str, Any] | None = None,
        academy_note: str = "",
        hourly_override: Mapping[str, Any] | None = None,
    ) -> OutpostRateResult:
        lvl = _parse_int(outpost_level)
        if lvl is None or not 1 <= lvl <= 2000:
            raise SyncCostTableError("前哨基地等级必须是 1–2000 的整数")
        boosts = normalize_academy_boosts(academy_boosts)
        row, extrapolated = self._raw_row_for(lvl)
        hourly: dict[str, float] = {}
        for res in RESOURCES:
            raw_val = getattr(row, res)
            base_per_min = raw_val * OUTPOST_RATIOS[res] / self.divisor
            per_min = base_per_min * (1.0 + boosts[res] / 100.0)
            hourly[res] = round(per_min * 60.0, 2)

        overridden = False
        if isinstance(hourly_override, Mapping):
            for res in RESOURCES:
                ov = hourly_override.get(res)
                if ov is None or ov == "":
                    continue
                if isinstance(ov, bool):
                    raise SyncCostTableError(f"自定义小时产量 {res} 无效")
                try:
                    parsed = float(ov)
                except (TypeError, ValueError) as exc:
                    raise SyncCostTableError(f"自定义小时产量 {res} 必须是数字") from exc
                if not math.isfinite(parsed) or parsed < 0:
                    raise SyncCostTableError(f"自定义小时产量 {res} 必须是非负有限数")
                hourly[res] = parsed
                overridden = True

        base_daily = {res: round(hourly[res] * 24.0, 2) for res in RESOURCES}
        notes: list[str] = []
        if overridden:
            notes.append("包含用户自定义小时产量覆盖")
        elif extrapolated:
            notes.append(
                f"前哨 Lv.{lvl} 超过内置表上限 Lv.{self.max_level}，按末尾曲线线性外推（误差约 ±5%，可在工作台手动覆盖小时产量）"
            )
        elif lvl > 400:
            notes.append(f"基于前哨 Lv.{lvl} 交叉核验扩展表精确查表（非外推，含 Lv.533 跃升节点）")
        else:
            notes.append(f"基于前哨 Lv.{lvl} WTFPL 开源基准表精确计算")

        return OutpostRateResult(
            outpost_level=lvl,
            hourly=hourly,
            base_daily=base_daily,
            academy_boosts=boosts,
            academy_note=academy_note or "战术学院满级加成（可手动调整）",
            estimated_above_400=extrapolated and not overridden,
            rate_note="；".join(notes),
        )


def calculate_case_yields(
    cases: Mapping[str, Mapping[str, Any]] | None,
    hourly_rates: Mapping[str, float],
) -> tuple[dict[str, int], dict[str, int]]:
    """计算背包资源箱（1H/2H/4H/8H/12H/24H）折算出的总资源量与总小时数。"""
    yields = {res: 0 for res in RESOURCES}
    total_hours = {res: 0 for res in RESOURCES}
    if not cases:
        return yields, total_hours
    if not isinstance(cases, Mapping):
        raise SyncCostTableError("资源箱参数格式无效")

    for res in RESOURCES:
        res_map = cases.get(res)
        if not res_map:
            continue
        if not isinstance(res_map, Mapping):
            raise SyncCostTableError(f"{res} 资源箱必须是对象")
        hours_sum = 0
        for h in CASE_HOURS:
            raw_count = res_map.get(f"{h}h")
            if raw_count is None:
                raw_count = res_map.get(f"{h}H")
            if raw_count is None:
                raw_count = res_map.get(str(h))
            if raw_count is None or raw_count == "":
                continue
            count = _parse_int(raw_count)
            if count is None or count < 0 or count > 1_000_000:
                raise SyncCostTableError(f"{res} 的 {h}H 资源箱数量无效")
            hours_sum += h * count
        total_hours[res] = hours_sum
        rate = float(hourly_rates.get(res, 0.0) or 0.0)
        yields[res] = int(math.floor(hours_sum * rate))
    return yields, total_hours


def calculate_daily_production(
    *,
    hourly_rates: Mapping[str, float],
    wipeout_count: Any = 1,
    extra_daily: Mapping[str, Any] | None = None,
) -> tuple[dict[str, float], int, dict[str, float]]:
    """计算每日总收益 = 24H 基础挂机 + 歼灭次数×2H + 额外日收益。"""
    wipeouts = 1 if wipeout_count is None or wipeout_count == "" else _parse_int(wipeout_count)
    if wipeouts is None or not 0 <= wipeouts <= 20:
        raise SyncCostTableError("每日一举歼灭次数必须是 0–20 的整数")
    extras: dict[str, float] = {res: 0.0 for res in RESOURCES}
    if extra_daily is not None:
        if not isinstance(extra_daily, Mapping):
            raise SyncCostTableError("额外日收益必须是对象")
        for res in RESOURCES:
            raw = extra_daily.get(res)
            if raw is None or raw == "":
                continue
            if isinstance(raw, bool):
                raise SyncCostTableError(f"额外日收益 {res} 无效")
            try:
                parsed = float(raw)
            except (TypeError, ValueError) as exc:
                raise SyncCostTableError(f"额外日收益 {res} 必须是数字") from exc
            if not math.isfinite(parsed) or parsed < 0:
                raise SyncCostTableError(f"额外日收益 {res} 必须是非负有限数")
            extras[res] = parsed

    hours_per_day = 24 + 2 * wipeouts
    daily = {
        res: round(float(hourly_rates.get(res, 0.0) or 0.0) * hours_per_day + extras[res], 2)
        for res in RESOURCES
    }
    return daily, wipeouts, extras


def extract_account_currencies(basic: Any) -> dict[str, int]:
    """从 BlaBlaLink basic.currencies 提取芯尘、信用点与战斗数据直接库存。"""
    result = {res: 0 for res in RESOURCES}
    currencies = basic.get("currencies") if isinstance(basic, Mapping) else None
    for item in currencies or ():
        if not isinstance(item, Mapping):
            continue
        kind = _CURRENCY_TYPE_MAP.get(_parse_int(item.get("type")) or -1)
        if kind is None:
            continue
        amount = _parse_int(item.get("value"))
        if amount is not None and amount >= 0:
            result[kind] = amount
    return result


def extract_account_sync_context(
    profile: Mapping[str, Any] | None,
    outpost_table: OutpostRateTable | None,
    cost_table: SyncCostTable | None,
) -> AccountSyncContext:
    """整合已绑定账号资料、前哨产量估算与可升等级信息。"""
    data = profile if isinstance(profile, Mapping) else {}
    basic = data.get("basic") if isinstance(data.get("basic"), Mapping) else {}
    outpost = data.get("outpost") if isinstance(data.get("outpost"), Mapping) else {}

    synchro_level = _parse_int(outpost.get("synchro_level"))
    outpost_level = _parse_int(outpost.get("outpost_battle_level"))
    academy_class = _parse_int(outpost.get("tactic_academy_class"))
    academy_lesson = _parse_int(outpost.get("tactic_academy_lesson"))
    academy_boosts, academy_note = infer_academy_boosts(academy_class, academy_lesson)
    inventory = extract_account_currencies(basic)

    outpost_rates: OutpostRateResult | None = None
    if outpost_table is not None and outpost_level is not None and outpost_level >= 1:
        outpost_rates = outpost_table.hourly_rates(
            outpost_level,
            academy_boosts=academy_boosts,
            academy_note=academy_note,
        )

    gainable_levels: int | None = None
    reachable_level: int | None = None
    remaining: dict[str, int] | None = None
    next_cost: dict[str, int] | None = None
    next_missing: dict[str, int] | None = None
    if cost_table is not None and synchro_level is not None and synchro_level >= 1:
        gainable_levels, reachable_level, remaining = cost_table.gainable_levels(
            synchro_level, inventory
        )
        next_cost = cost_table.next_level_cost(synchro_level)
        if next_cost is not None:
            next_missing = {
                res: max(0, next_cost[res] - inventory.get(res, 0))
                for res in RESOURCES
            }

    return AccountSyncContext(
        synchro_level=synchro_level,
        outpost_level=outpost_level,
        academy_class=academy_class,
        academy_lesson=academy_lesson,
        academy_boosts=academy_boosts,
        academy_note=academy_note,
        inventory=inventory,
        outpost_rates=outpost_rates,
        gainable_levels=gainable_levels,
        reachable_level=reachable_level,
        remaining_inventory=remaining,
        next_level_cost=next_cost,
        next_level_missing=next_missing,
    )


__all__ = [
    "ACADEMY_MAX_BOOSTS",
    "AccountSyncContext",
    "CASE_HOURS",
    "OUTPOST_RATIOS",
    "OutpostRateResult",
    "OutpostRateRow",
    "OutpostRateTable",
    "calculate_case_yields",
    "calculate_daily_production",
    "extract_account_currencies",
    "extract_account_sync_context",
    "infer_academy_boosts",
    "normalize_academy_boosts",
]
