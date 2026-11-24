# SPDX-License-Identifier: GPL-3.0-or-later
"""同步器等级计算（12）：按资源到齐天数取最大，给出日期与瓶颈。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .cost_table import RESOURCES, RESOURCE_LABELS, SyncCostTable, SyncCostTableError

CST = timezone(timedelta(hours=8))


class SyncLevelInputError(ValueError):
    """同步器计算的用户输入非法。"""


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    """单项资源的库存、产量与到齐天数。"""

    resource: str
    label: str
    required: int
    stock: int
    production: float
    days: int | None
    status: str
    missing: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "label": self.label,
            "required": self.required,
            "stock": self.stock,
            "production": self.production,
            "days": self.days,
            "status": self.status,
            "missing": self.missing,
        }


@dataclass(frozen=True, slots=True)
class SyncLevelPlan:
    """一次同步器升级规划。"""

    current: int
    target: int
    required: Mapping[str, int]
    resources: tuple[ResourcePlan, ...]
    overall_days: int | None
    eta: date | None
    bottlenecks: tuple[str, ...]
    table: SyncCostTable | None
    note: str = ""
    cost_source: str = ""
    gainable_levels: int | None = None
    reachable_level: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "target": self.target,
            "required": dict(self.required),
            "resources": [item.to_dict() for item in self.resources],
            "overall_days": self.overall_days,
            "eta": self.eta.isoformat() if self.eta else None,
            "bottlenecks": list(self.bottlenecks),
        }


def _amount(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SyncLevelInputError(f"{field} 必须是非负整数")
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < 0:
        raise SyncLevelInputError(f"{field} 必须是非负整数")
    return value


def _daily(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise SyncLevelInputError(f"{field} 必须是每天的数量")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SyncLevelInputError(f"{field} 必须是每天的数量") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise SyncLevelInputError(f"{field} 必须是非负有限数")
    return parsed


def _level(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SyncLevelInputError(f"{field} 必须是整数等级")
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or not 1 <= value <= 2000:
        raise SyncLevelInputError(f"{field} 必须是 1–2000 的整数")
    return value


def calculate_sync_plan(
    *,
    current: Any,
    target: Any,
    inventory: Mapping[str, Any],
    production: Mapping[str, Any],
    table: SyncCostTable | None,
    manual_costs: Mapping[str, Any] | None = None,
    today: date | datetime | None = None,
    timezone_offset_hours: int = 8,
) -> SyncLevelPlan:
    """计算升到目标等级所需天数、预计日期与瓶颈资源。

    - 每项资源到齐天数 = ceil(缺口 / 日产量)，库存足够时为 0；
    - 日产量为 0 且有缺口时该资源不可达，整体日期为“无法估算”；
    - 整体天数取各资源的**最大值**，瓶颈为达到最大天数的资源。
    """
    current_level = _level(current, "当前等级")
    target_level = _level(target, "目标等级")
    if target_level <= current_level:
        raise SyncLevelInputError("目标等级必须高于当前等级")
    if not isinstance(inventory, Mapping) or not isinstance(production, Mapping):
        raise SyncLevelInputError("库存与产量必须是资源映射")
    if manual_costs is not None:
        if not isinstance(manual_costs, Mapping):
            raise SyncLevelInputError("手工成本必须是三项资源的累计消耗")
        required = {
            resource: _amount(manual_costs.get(resource), f"{RESOURCE_LABELS[resource]}累计成本")
            for resource in RESOURCES
        }
        cost_source = "用户手工输入（未验证；仅用于本次计算）"
        cost_table = None
    else:
        if table is None:
            raise SyncLevelInputError(
                "缺少可靠等级成本表：请导入带来源与核验日期的成本表，"
                "或使用 /妮姬 同步器 计算 手工 输入三项累计成本"
            )
        try:
            required = table.cost_between(current_level, target_level)
        except SyncCostTableError as exc:
            raise SyncLevelInputError(str(exc)) from exc
        cost_source = f"{table.label} · 核验 {table.checked_at}"
        cost_table = table

    stocks = {resource: _amount(inventory.get(resource, 0), f"{RESOURCE_LABELS[resource]}库存") for resource in RESOURCES}
    rates = {resource: _daily(production.get(resource, 0), f"{RESOURCE_LABELS[resource]}日产量") for resource in RESOURCES}

    plans: list[ResourcePlan] = []
    for resource in RESOURCES:
        need = required[resource]
        stock = stocks[resource]
        rate = rates[resource]
        missing = max(0, need - stock)
        if missing == 0:
            days: int | None = 0
            status = "库存足够"
        elif rate <= 0:
            days = None
            status = "零产量，无法达到"
        else:
            days = int(math.ceil(missing / rate))
            status = "需要积累"
        plans.append(
            ResourcePlan(
                resource=resource,
                label=RESOURCE_LABELS[resource],
                required=need,
                stock=stock,
                production=rate,
                days=days,
                status=status,
                missing=missing,
            )
        )

    reachable = [item.days for item in plans if item.days is not None]
    if any(item.days is None for item in plans):
        overall: int | None = None
        bottlenecks = tuple(item.label for item in plans if item.days is None)
        note = "存在零产量资源且有缺口，无法给出到达日期；请补充该资源的日产量或库存。"
    else:
        overall = max(reachable, default=0)
        bottlenecks = tuple(item.label for item in plans if item.days == overall)
        note = ""

    base = _as_date(today, timezone_offset_hours)
    eta = base + timedelta(days=overall) if overall is not None else None
    gained: int | None = None
    reachable_level: int | None = None
    if cost_table is not None:
        gained, reachable_level, _ = cost_table.gainable_levels(current_level, stocks)
    return SyncLevelPlan(
        current=current_level,
        target=target_level,
        required=dict(required),
        resources=tuple(plans),
        overall_days=overall,
        eta=eta,
        bottlenecks=bottlenecks,
        table=cost_table,
        note=note,
        cost_source=cost_source,
        gainable_levels=gained,
        reachable_level=reachable_level,
    )


def _as_date(value: date | datetime | None, offset_hours: int) -> date:
    if value is None:
        return datetime.now(timezone(timedelta(hours=offset_hours))).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SyncLevelInputError("当前时间必须包含明确时区")
        return value.astimezone(timezone(timedelta(hours=offset_hours))).date()
    if isinstance(value, date):
        return value
    raise SyncLevelInputError("当前日期格式无效")


def render_sync_plan(plan: SyncLevelPlan) -> str:
    """渲染同步器计划文本，保留来源与缺失说明。"""
    lines = [f"【同步器等级】{plan.current} → {plan.target}"]
    if plan.table is not None:
        lines.extend(
            (
                f"成本表：{plan.table.label} · 核验 {plan.table.checked_at} · {plan.table.source_url}",
                f"覆盖范围：{plan.table.scope}",
            )
        )
    else:
        lines.append("成本来源：" + (plan.cost_source or "用户手工输入（未验证）"))
    lines.append("")
    for item in plan.resources:
        days = "无法估算" if item.days is None else f"{item.days} 天"
        lines.append(
            f"{item.label}：需要 {item.required:,} · 库存 {item.stock:,} · "
            f"日产量 {item.production:g} · 缺口 {item.missing:,} · {days}（{item.status}）"
        )
    lines.append("")
    if plan.reachable_level is not None and plan.gainable_levels is not None:
        lines.append(
            f"现有库存可立即升至：Lv.{plan.reachable_level}（+{plan.gainable_levels} 级）"
        )
    if plan.overall_days is None:
        lines.append("预计日期：无法估算（" + "、".join(plan.bottlenecks) + " 零产量且有缺口）")
    else:
        lines.append(f"全部到齐：{plan.overall_days} 天（预计 {plan.eta.isoformat()}，北京时间）")
        lines.append("瓶颈：" + ("、".join(plan.bottlenecks) or "无"))
    if plan.note:
        lines.append(plan.note)
    return "\n".join(lines)


__all__ = [
    "ResourcePlan",
    "SyncLevelInputError",
    "SyncLevelPlan",
    "calculate_sync_plan",
    "render_sync_plan",
]
