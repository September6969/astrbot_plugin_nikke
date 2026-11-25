# SPDX-License-Identifier: GPL-3.0-or-later
"""同步器等级计算（12）：按资源到齐天数取最大，给出日期、瓶颈与前哨/资源箱规划。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .cost_table import RESOURCES, RESOURCE_LABELS, SyncCostTable, SyncCostTableError
from .outpost import (
    AccountSyncContext,
    OutpostRateTable,
    calculate_case_yields,
    calculate_daily_production,
    infer_academy_boosts,
)

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
    direct_inventory: Mapping[str, int] | None = None
    case_yields: Mapping[str, int] | None = None
    outpost_level: int | None = None
    wipeout_count: int | None = None
    extra_daily: Mapping[str, float] | None = None
    gainable_without_cases: int | None = None
    reachable_without_cases: int | None = None
    next_level_cost: Mapping[str, int] | None = None
    next_level_missing: Mapping[str, int] | None = None
    rate_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "target": self.target,
            "required": dict(self.required),
            "resources": [item.to_dict() for item in self.resources],
            "overall_days": self.overall_days,
            "eta": self.eta.isoformat() if self.eta else None,
            "bottlenecks": list(self.bottlenecks),
            "cost_source": self.cost_source,
            "note": self.note,
            "gainable_levels": self.gainable_levels,
            "reachable_level": self.reachable_level,
            "gainable_without_cases": self.gainable_without_cases,
            "reachable_without_cases": self.reachable_without_cases,
            "direct_inventory": dict(self.direct_inventory) if self.direct_inventory is not None else None,
            "case_yields": dict(self.case_yields) if self.case_yields is not None else None,
            "outpost_level": self.outpost_level,
            "wipeout_count": self.wipeout_count,
            "extra_daily": dict(self.extra_daily) if self.extra_daily is not None else None,
            "next_level_cost": dict(self.next_level_cost) if self.next_level_cost is not None else None,
            "next_level_missing": dict(self.next_level_missing) if self.next_level_missing is not None else None,
            "rate_note": self.rate_note,
        }


def _amount(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SyncLevelInputError(f"{field} 必须是非负整数")
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < 0:
        raise SyncLevelInputError(f"{field} 必须是非负整数")
    return value


def _opt_amount(mapping: Mapping[str, Any], key: str, field: str) -> int:
    raw = mapping.get(key, 0)
    if raw is None or raw == "":
        return 0
    return _amount(raw, field)


def _daily(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise SyncLevelInputError(f"{field} 必须是每天的数量")
    if value is None or value == "":
        return 0.0
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
    direct_inventory: Mapping[str, int] | None = None,
    case_yields: Mapping[str, int] | None = None,
    outpost_level: int | None = None,
    wipeout_count: int | None = None,
    extra_daily: Mapping[str, float] | None = None,
    rate_note: str = "",
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

    stocks = {resource: _opt_amount(inventory, resource, f"{RESOURCE_LABELS[resource]}库存") for resource in RESOURCES}
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
    gained_direct: int | None = None
    reachable_direct: int | None = None
    next_cost: dict[str, int] | None = None
    next_missing: dict[str, int] | None = None
    if cost_table is not None:
        gained, reachable_level, _ = cost_table.gainable_levels(current_level, stocks)
        if direct_inventory is not None:
            direct_stocks = {
                res: _opt_amount(direct_inventory, res, f"{RESOURCE_LABELS[res]}直接库存")
                for res in RESOURCES
            }
            gained_direct, reachable_direct, _ = cost_table.gainable_levels(current_level, direct_stocks)
        next_cost = cost_table.next_level_cost(current_level)
        if next_cost is not None:
            next_missing = {
                res: max(0, next_cost[res] - stocks.get(res, 0))
                for res in RESOURCES
            }
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
        direct_inventory=dict(direct_inventory) if direct_inventory is not None else None,
        case_yields=dict(case_yields) if case_yields is not None else None,
        outpost_level=outpost_level,
        wipeout_count=wipeout_count,
        extra_daily=dict(extra_daily) if extra_daily is not None else None,
        gainable_without_cases=gained_direct,
        reachable_without_cases=reachable_direct,
        next_level_cost=next_cost,
        next_level_missing=next_missing,
        rate_note=rate_note,
    )


def plan_sync_from_inputs(
    *,
    current: Any,
    target: Any,
    inventory: Mapping[str, Any] | None,
    production: Mapping[str, Any] | None = None,
    outpost_level: Any = None,
    academy_boosts: Mapping[str, Any] | None = None,
    academy_class: Any = None,
    hourly_override: Mapping[str, Any] | None = None,
    cases: Mapping[str, Any] | None = None,
    wipeout_count: Any = 1,
    extra_daily: Mapping[str, Any] | None = None,
    manual_costs: Mapping[str, Any] | None = None,
    table: SyncCostTable | None,
    outpost_table: OutpostRateTable | None,
    today: date | datetime | None = None,
) -> tuple[SyncLevelPlan, dict[str, Any] | None]:
    """统一执行网页端与机器人的高级同步器计算（支持前哨基地、资源箱与额外日收益）。"""
    direct_inv = {
        res: _opt_amount(inventory or {}, res, f"{RESOURCE_LABELS[res]}库存")
        for res in RESOURCES
    }
    has_explicit_prod = isinstance(production, Mapping) and any(
        production.get(res) not in (None, "") for res in RESOURCES
    )
    outpost_meta: dict[str, Any] | None = None
    case_yields: dict[str, int] | None = None
    wipeout_used: int | None = None
    extra_used: dict[str, float] | None = None
    resolved_outpost_level: int | None = None
    rate_note = ""
    total_inv: dict[str, int] = dict(direct_inv)

    if outpost_level not in (None, "") and outpost_table is not None:
        try:
            inferred_boosts, academy_note = infer_academy_boosts(academy_class)
            rate_result = outpost_table.hourly_rates(
                outpost_level,
                academy_boosts=academy_boosts if academy_boosts is not None else inferred_boosts,
                academy_note=academy_note,
                hourly_override=hourly_override,
            )
            case_yields, case_hours = calculate_case_yields(
                cases if isinstance(cases, Mapping) else None,
                rate_result.hourly,
            )
            for res in RESOURCES:
                total_inv[res] = direct_inv[res] + case_yields[res]
            daily_prod, wipeout_used, extra_used = calculate_daily_production(
                hourly_rates=rate_result.hourly,
                wipeout_count=wipeout_count,
                extra_daily=extra_daily,
            )
        except SyncCostTableError as exc:
            raise SyncLevelInputError(str(exc)) from exc

        resolved_outpost_level = rate_result.outpost_level
        rate_note = rate_result.rate_note
        if not has_explicit_prod:
            production = daily_prod
        outpost_meta = {
            "outpost_level": rate_result.outpost_level,
            "hourly": rate_result.hourly,
            "base_daily": rate_result.base_daily,
            "academy_boosts": rate_result.academy_boosts,
            "academy_note": rate_result.academy_note,
            "estimated_above_400": rate_result.estimated_above_400,
            "rate_note": rate_result.rate_note,
            "case_hours": case_hours,
            "case_yields": case_yields,
            "wipeout_count": wipeout_used,
            "extra_daily": extra_used,
            "total_daily": daily_prod,
        }
    elif isinstance(cases, Mapping):
        raise SyncLevelInputError("折算背包资源箱需要提供前哨基地等级与前哨产量表")

    plan = calculate_sync_plan(
        current=current,
        target=target,
        inventory=total_inv,
        production=production or {res: 0 for res in RESOURCES},
        table=table if not manual_costs else None,
        manual_costs=manual_costs if isinstance(manual_costs, Mapping) else None,
        today=today,
        direct_inventory=direct_inv,
        case_yields=case_yields,
        outpost_level=resolved_outpost_level,
        wipeout_count=wipeout_used,
        extra_daily=extra_used,
        rate_note=rate_note,
    )
    return plan, outpost_meta


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


def _format_num(value: float | int) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.1f}"


def render_sync_plan(plan: SyncLevelPlan) -> str:
    """渲染同步器计划文本，保留来源、前哨/资源箱信息与缺失说明。"""
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
    if plan.outpost_level is not None:
        wipe = f" + 每日歼灭 {plan.wipeout_count} 次" if plan.wipeout_count is not None else ""
        lines.append(f"前哨产出：前哨 Lv.{plan.outpost_level}（24H{wipe}）")
    if plan.rate_note:
        lines.append(f"产量说明：{plan.rate_note}")
    lines.append("")
    for item in plan.resources:
        days = "无法估算" if item.days is None else f"{item.days} 天"
        stock_detail = f"库存 {item.stock:,}"
        if plan.case_yields and plan.direct_inventory is not None:
            c_val = plan.case_yields.get(item.resource, 0)
            d_val = plan.direct_inventory.get(item.resource, 0)
            if c_val > 0:
                stock_detail = f"总库存 {item.stock:,}（直存 {d_val:,} + 箱子 {c_val:,}）"
        lines.append(
            f"{item.label}：需要 {item.required:,} · {stock_detail} · "
            f"日产量 {item.production:g} · 缺口 {item.missing:,} · {days}（{item.status}）"
        )
    lines.append("")
    if plan.reachable_level is not None and plan.gainable_levels is not None:
        extra = ""
        if (
            plan.gainable_without_cases is not None
            and plan.reachable_without_cases is not None
            and plan.gainable_without_cases != plan.gainable_levels
        ):
            extra = f"（不含箱子 Lv.{plan.reachable_without_cases}，+{plan.gainable_without_cases} 级）"
        lines.append(
            f"现有库存可立即升至：Lv.{plan.reachable_level}（+{plan.gainable_levels} 级）{extra}"
        )
    if plan.overall_days is None:
        lines.append("预计日期：无法估算（" + "、".join(plan.bottlenecks) + " 零产量且有缺口）")
    else:
        lines.append(f"全部到齐：{plan.overall_days} 天（预计 {plan.eta.isoformat()}，北京时间）")
        lines.append("瓶颈：" + ("、".join(plan.bottlenecks) or "无"))
    if plan.note:
        lines.append(plan.note)
    return "\n".join(lines)


def render_sync_overview(ctx: AccountSyncContext, table: SyncCostTable | None) -> str:
    """渲染 `/妮姬 同步器` 账号自动读取总览。"""
    if ctx.synchro_level is None:
        return "上游未返回同步器等级（缺失）。可改用 /妮姬 同步器 计算 手工输入。"
    lines = [
        f"当前同步器等级：Lv.{ctx.synchro_level}（来自已绑定账号只读资料）",
    ]
    if ctx.outpost_level is not None:
        lines.append(f"前哨基地等级：Lv.{ctx.outpost_level} · {ctx.academy_note}")
    lines.append(
        "直接库存："
        + " / ".join(f"{RESOURCE_LABELS[r]} {ctx.inventory.get(r, 0):,}" for r in RESOURCES)
    )
    if ctx.outpost_rates is not None:
        daily = {
            r: ctx.outpost_rates.hourly[r] * 26.0
            for r in RESOURCES
        }
        lines.append(
            "估算日产（24H + 每日免费歼灭1次）："
            + " / ".join(f"{RESOURCE_LABELS[r]} {_format_num(round(daily[r]))}" for r in RESOURCES)
        )
        if ctx.outpost_rates.estimated_above_400:
            lines.append(f"注：{ctx.outpost_rates.rate_note}")
    if table is not None and ctx.gainable_levels is not None and ctx.reachable_level is not None:
        lines.append(f"直接库存可升：+{ctx.gainable_levels} 级（可达 Lv.{ctx.reachable_level}）")
        if ctx.next_level_cost is not None:
            lines.append(
                f"升至 Lv.{ctx.synchro_level + 1} 单级需："
                + " / ".join(f"{RESOURCE_LABELS[r]} {ctx.next_level_cost[r]:,}" for r in RESOURCES)
            )
    suggested = ((ctx.synchro_level // 10) + 1) * 10
    if suggested <= ctx.synchro_level:
        suggested = ctx.synchro_level + 10
    lines.extend(
        (
            "",
            f"常用指令：/妮姬 同步器 计算 {suggested} ｜ /妮姬 同步器 可升",
            "含背包资源箱与自定义日收益的完整版请用 /妮姬 工作台。",
        )
    )
    return "\n".join(lines)


def render_gainable_report(ctx: AccountSyncContext, table: SyncCostTable) -> str:
    """渲染 `/妮姬 同步器 可升` 即时可升级分析报告。"""
    if ctx.synchro_level is None:
        return "上游未返回同步器等级（缺失），无法计算当前可升等级。"
    gained = ctx.gainable_levels or 0
    reachable = ctx.reachable_level or ctx.synchro_level
    remaining = ctx.remaining_inventory or ctx.inventory
    lines = [
        f"【同步器即时可升】当前 Lv.{ctx.synchro_level}（来自已绑定账号只读资料）",
        "直接库存："
        + " / ".join(f"{RESOURCE_LABELS[r]} {ctx.inventory.get(r, 0):,}" for r in RESOURCES),
        f"直接库存可立即连续升级：+{gained} 级（可升至 Lv.{reachable}）",
    ]
    if gained > 0:
        lines.append(
            "升级后剩余："
            + " / ".join(f"{RESOURCE_LABELS[r]} {remaining.get(r, 0):,}" for r in RESOURCES)
        )
    nxt_cost = table.next_level_cost(reachable)
    if nxt_cost is not None:
        shortfall = {
            r: max(0, nxt_cost[r] - remaining.get(r, 0))
            for r in RESOURCES
        }
        lines.append(
            f"再升 1 级（Lv.{reachable} → {reachable + 1}）还差："
            + " / ".join(f"{RESOURCE_LABELS[r]} {shortfall[r]:,}" for r in RESOURCES)
        )
    lines.append("注：以上仅统计直接库存；如需计入背包资源箱（1H–24H）请使用 /妮姬 工作台。")
    return "\n".join(lines)


def render_cost_lookup(
    current: int,
    target: int,
    table: SyncCostTable,
    inventory: Mapping[str, int] | None = None,
) -> str:
    """渲染双等级区间查询结果（`/妮姬 同步器 计算 <当前> <目标>`）。"""
    required = table.cost_between(current, target)
    lines = [
        f"【同步器区间消耗】Lv.{current} → Lv.{target}",
        f"成本表：{table.label} · 核验 {table.checked_at}",
        "",
    ]
    for res in RESOURCES:
        need = required[res]
        if inventory is not None:
            stock = int(inventory.get(res, 0) or 0)
            missing = max(0, need - stock)
            lines.append(f"{RESOURCE_LABELS[res]}：需要 {need:,} · 直接库存 {stock:,} · 缺口 {missing:,}")
        else:
            lines.append(f"{RESOURCE_LABELS[res]}：需要 {need:,}")
    lines.append("")
    lines.append("提示：绑定账号后可直接 /妮姬 同步器 计算 <目标等级> 自动带上前哨产量估算日期；未绑定可前往 /妮姬 大厅 使用公开计算器。")
    return "\n".join(lines)


__all__ = [
    "ResourcePlan",
    "SyncLevelInputError",
    "SyncLevelPlan",
    "calculate_sync_plan",
    "plan_sync_from_inputs",
    "render_cost_lookup",
    "render_gainable_report",
    "render_sync_overview",
    "render_sync_plan",
]
