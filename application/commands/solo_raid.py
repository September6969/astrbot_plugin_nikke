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
            status = (
                "已导入赛季：" + "、".join(season.name for season in catalog.seasons)
                if catalog.available
                else catalog.reason
            )
            return (
                "【单人突袭五队】\n"
                f"{status}\n"
                "/妮姬 单人突袭 赛季 — 查看赛季首领与弱点\n"
                "/妮姬 单人突袭 编组 <角色:B1,...> — 手工池编组\n"
                "/妮姬 单人突袭 编组 账号 — 使用登录角色池；无登录时回退本人 fresh 的 ShiftyPad 只读快照\n"
                "/妮姬 单人突袭 阵容图 <角色,...> — 生成五队图片\n"
                "/妮姬 单人突袭 编组 — 无参数时同样先登录、再 fresh ShiftyPad 只读快照\n"
                "/妮姬 单人突袭 保存 <角色,...> — 保存方案（仅本人可见）\n"
                "/妮姬 单人突袭 我的 — 回查本人已保存方案；队 <1-5> 查看单队"
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
            return "赛季数据缺失：" + catalog.reason
        season = catalog.latest()
        status = season_status(season, self._clock())
        lines = [
            f"【单人突袭赛季】{season.name}",
            f"状态：{status}",
            f"来源：{season.source_url} · 核验 {season.checked_at}",
        ]
        for boss in season.bosses:
            lines.append(
                f"· {boss.name} · 弱点 {boss.weakness}"
                + (f" · 属性 {boss.element}" if boss.element else "")
            )
            if getattr(boss, "mechanics", ""):
                lines.append("  机制：" + boss.mechanics)
        if season.ends_at:
            lines.append("说明：这是最近可核对的公开赛季；已结束时不会显示为进行中。")
        if season.note:
            lines.append("注：" + season.note)
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
            lines.append("伤害：缺少可靠伤害公式，未估算。")
        else:
            label = saved.damage_model_label or "配置化估算"
            lines.append(f"{label}：{saved.damage_total:,}")
        lines.append("该方案仅你自己可见。")
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
            f"{member.name}（{BURST_LABELS.get(member.burst, '?')}）" for member in team.members
        ) or "（空）"
        lines = [f"【单人突袭 · 第 {team.index} 队】{saved.season_name}", members]
        if team.issues:
            lines.append("问题：" + "；".join(team.issues))
        if team.damage is not None:
            label = saved.damage_model_label or "配置化估算"
            lines.append(f"{label}：{team.damage:,}")
        lines.append("该方案仅你自己可见。")
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
            return parse_members(token), "角色来源：手工输入角色池。"

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
                return members, "角色来源：已绑定登录账号角色库。"

        binding = self._fresh_readonly_binding(context)
        if binding is None:
            raise ValueError(
                "未找到可用登录角色库，也没有 fresh 的 ShiftyPad 只读绑定；"
                "请使用手工角色池或在私聊先 /妮姬 我的妮姬 导入。"
            )
        characters = binding.profile.characters
        if not characters:
            raise ValueError(
                "ShiftyPad 只读快照没有角色字段（明确缺口，未用角色数量替代角色池）。"
            )
        directory = self._character_directory()
        members_list: list[Member] = []
        missing_burst = 0
        missing_element = 0
        for character in characters:
            code = str(character.name_code or "").strip()
            if not code:
                continue
            row = directory.get(code, {})
            burst = str(row.get("burst") or "")
            element = str(row.get("element") or "")
            if not burst:
                missing_burst += 1
            if not element:
                missing_element += 1
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
            raise ValueError("ShiftyPad 只读快照没有可用角色标识，无法编组。")
        note = (
            f"角色来源：ShiftyPad 只读快照（{len(members_list)} 名，"
            f"{binding.last_sync_at}）。"
        )
        if missing_burst or missing_element:
            note += (
                f" 缺少角色目录字段：爆裂 {missing_burst} 名、元素 {missing_element} 名；"
                "未猜测，爆裂链/克制会显示缺口。"
            )
        return tuple(members_list), note


__all__ = ["SoloRaidCommandHandler", "SoloRenderer"]
