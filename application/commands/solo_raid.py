# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭五队编组与估伤命令用例（22）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from ...features.solo_raid.builder import (
    BURST_LABELS,
    Member,
    build_five_teams,
    members_from_roster,
    parse_members,
    render_plan,
)
from ...features.solo_raid.seasons import season_status
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext, CommandResult, ImageReply

SoloRenderer = Callable[[Any, Any], Awaitable[Any]]


class SoloRaidCommandHandler(ToolboxDomainHandler):
    """处理单人突袭赛季查询、五队编组、估伤、保存与阵容图命令。"""

    def __init__(
        self,
        services: Any,
        *,
        render_solo: SoloRenderer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(services, clock=clock)
        self._render_solo = render_solo

    async def _soloraid(
        self, context: CommandContext, action: str, value: str
    ) -> CommandResult | str:
        key = action.strip().casefold()
        live_fn = getattr(self.services, "live_solo_catalog", None)
        catalog = live_fn() if callable(live_fn) else self.services.solo_catalog
        if key in {"", "帮助", "help"}:
            latest_name = catalog.latest().name if catalog.available and catalog.latest() else "暂未获取"
            return (
                "【单人突袭五队助手】\n"
                f"当前赛季：{latest_name}\n"
                "• /妮姬 单人突袭 赛季 — 查看当前赛季首领弱点与机制\n"
                "• /妮姬 单人突袭 编组 — 按你绑定的角色库自动配五队\n"
                "• /妮姬 单人突袭 编组 角色1:B1,... — 手动指定角色池配队\n"
                "• /妮姬 单人突袭 阵容图 — 生成五队阵容图\n"
                "• /妮姬 单人突袭 保存 / 我的 / 队 <1-5> — 保存或查看我的五队"
            )
        if key in {"赛季", "season"}:
            return self._season_summary(catalog)
        if key in {"我的", "my"}:
            return self._saved_overview(context.actor_id)
        if key in {"队", "team"}:
            return self._saved_team(context.actor_id, value)
        if key in {"编组", "阵容图", "保存", "组队"}:
            return await self._build_or_save(context, catalog, key, value)
        return "用法：/妮姬 单人突袭 [赛季|编组|阵容图|保存|我的]"

    def _season_summary(self, catalog: Any) -> str:
        if not catalog.available:
            return "暂时没有查到单人突袭赛季信息，请稍后再试。"
        season = catalog.latest()
        status = season_status(season, self._clock())
        lines = [
            f"【单人突袭赛季】{season.name}",
            f"当前状态：{status}",
        ]
        for boss in season.bosses:
            lines.append(
                f"• 首领：{boss.name}（弱点 {boss.weakness}"
                + (f" · 属性 {boss.element}" if boss.element else "")
                + "）"
            )
            if getattr(boss, "mechanics", ""):
                lines.append("  机制提示：" + boss.mechanics)
        if season.note:
            lines.append("💡 " + season.note)
        return "\n".join(lines)

    def _saved_overview(self, actor_id: str) -> str:
        saved = self.services.solo_plans.load(actor_id)
        if saved is None:
            return "你还没有保存的单人突袭方案。"
        lines = [f"【已保存方案】{saved.season_name} · {saved.saved_at}"]
        for team in saved.teams:
            members = " / ".join(
                f"{member.name}（{BURST_LABELS.get(member.burst, '?')}）" for member in team.members
            ) or "（空）"
            lines.append(f"第 {team.index} 队：{members}")
        if saved.damage_total is None:
            lines.append("暂未启用伤害估算，仅保存了配队。")
        else:
            label = saved.damage_model_label or "预估伤害"
            lines.append(f"{label}：{saved.damage_total:,}")
        return "\n".join(lines)

    def _saved_team(self, actor_id: str, value: str) -> str:
        saved = self.services.solo_plans.load(actor_id)
        if saved is None:
            return "你还没有保存的单人突袭方案。"
        try:
            index = int(value.strip())
        except (TypeError, ValueError):
            return "用法：/妮姬 单人突袭 队 <1-5>"
        team = self.services.solo_plans.team(actor_id, index)
        if team is None:
            return f"未找到第 {index} 队。"
        members = " / ".join(
            f"{member.name}({BURST_LABELS.get(member.burst, '?')})" for member in team.members
        ) or "（空）"
        lines = [f"【单人突袭 · 第 {team.index} 队】{saved.season_name}", members]
        if team.issues:
            lines.append("⚠ " + "；".join(team.issues))
        if team.damage is not None:
            label = saved.damage_model_label or "预估伤害"
            lines.append(f"{label}：{team.damage:,}")
        return "\n".join(lines)

    async def _build_or_save(
        self, context: CommandContext, catalog: Any, key: str, value: str
    ) -> CommandResult | str:
        season = catalog.latest()
        members, source_note = await self._solo_members(context, value)
        plan = build_five_teams(
            members,
            season=season,
            damage_model=self.services.solo_damage_model,
        )
        boss = season.bosses[0] if season is not None and season.bosses else None
        plan = await self._apply_damage_engine(plan, boss)
        if key in {"阵容图", "image"}:
            if self._render_solo is not None:
                rendered = await self._render_solo(plan, boss)
                if isinstance(rendered, str) and rendered.strip():
                    return CommandResult((ImageReply(rendered),))
            return source_note + "\n" + render_plan(plan, boss=boss) + "\n（图片生成失败，已显示文字摘要。）"
        if key == "保存":
            saved = self.services.solo_plans.save(context.actor_id, plan)
            return (
                f"已保存单人突袭五队方案（{saved.season_name}，仅你本人可见）。\n"
                + source_note + "\n" + render_plan(plan, boss=boss)
            )
        return source_note + "\n" + render_plan(plan, boss=boss)

    async def _apply_damage_engine(self, plan: Any, boss: Any):
        """有本地开源引擎时用真实引擎覆盖估算；缺失时保留明确无法估伤。"""
        engine = getattr(self.services, "solo_engine", None)
        if engine is None:
            return plan
        result = await engine.estimate(
            plan.teams,
            boss_element=str(getattr(boss, "weakness", "") or getattr(boss, "element", "") or ""),
        )
        if not result.available:
            return plan if plan.damage_total is not None else replace(plan, estimate_note=result.reason)
        by_index = {item.index: item.damage for item in result.teams}
        teams = tuple(
            replace(team, damage=by_index.get(team.index)) for team in plan.teams
        )
        return replace(
            plan,
            teams=teams,
            damage_total=result.total,
            damage_model_label=result.label,
            estimate_note=result.note,
        )

    @staticmethod
    def _enrich_rows_with_directory(
        rows: list[Mapping[str, Any]], directory: Mapping[str, Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """用内置角色目录补齐账号名单缺失的中文名、爆裂阶段、属性与 resource_id。"""
        enriched: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("name_code") or row.get("character_key") or "").strip()
            meta = directory.get(code, {}) if code else {}
            merged = dict(row)
            for field in ("burst", "element", "name_zh_cn", "name_zh_tw", "name_cn", "resource_id"):
                current = merged.get(field)
                if (current is None or str(current).strip() == "") and meta.get(field) not in (None, ""):
                    merged[field] = meta[field]
            enriched.append(merged)
        return enriched

    async def _solo_members(self, context: CommandContext, value: str):
        token = value.strip()
        if token and token not in {"账号", "绑定", "my"}:
            return parse_members(token), "（按你输入的角色名单编组）"

        directory = self._character_directory()
        account = self._account(context)
        if account is not None:
            try:
                rows = await self._load_roster(account)
            except Exception:
                rows = []
            enriched_rows = self._enrich_rows_with_directory(rows, directory) if rows else []
            members = members_from_roster(enriched_rows) if enriched_rows else ()
            if members:
                return members, "（已自动按你绑定账号的角色库编组）"

        binding = self._fresh_readonly_binding(context)
        if binding is None:
            raise ValueError(
                "还没有绑定账号，暂无法自动配队。\n"
                "请私聊发送 /妮姬 账号 绑定，或直接输入角色名单：/妮姬 单人突袭 编组 红莲:B3,丽塔:B1,..."
            )
        characters = binding.profile.characters
        if not characters:
            raise ValueError(
                "同步到的档案里暂时没有具体角色名单，请重新同步，或手动输入角色列表编组。"
            )
        directory = self._character_directory()
        members_list: list[Member] = []
        for character in characters:
            code = str(character.name_code or "").strip()
            if not code:
                continue
            row = directory.get(code, {})
            burst = str(row.get("burst") or "")
            element = str(row.get("element") or "")
            members_list.append(
                Member(
                    name_code=code,
                    name=str(
                        row.get("name_zh_cn")
                        or row.get("name_zh_tw")
                        or row.get("name_cn")
                        or code
                    ),
                    burst=burst,
                    element=element,
                    resource_id=str(row.get("resource_id") or ""),
                )
            )
        if not members_list:
            raise ValueError("同步的档案里暂无可用角色，无法编组。")
        return tuple(members_list), f"（按你近期同步的角色档案编组，共 {len(members_list)} 名）"


__all__ = ["SoloRaidCommandHandler", "SoloRenderer"]
