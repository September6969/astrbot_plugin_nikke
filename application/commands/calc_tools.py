# SPDX-License-Identifier: GPL-3.0-or-later
"""养成工具与查询类命令用例：咨询、同步器、愿望单与超限助手（07/12/14/16）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import re
from typing import Any
import unicodedata

from ...features.counsel.bank import render_counsel_search
from ...features.overload_advice.advisor import (
    OverloadAdviceError,
    advise,
    parse_options,
    parse_targets,
    render_advice,
    simulate,
)
from ...features.sync.calculator import (
    SyncLevelInputError,
    calculate_sync_plan,
    render_sync_plan,
)
from ...features.wishlist.advisor import (
    OwnedCharacter,
    normalize_strategy,
    parse_owned,
    recommend,
    render_wishlist,
)
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext, CommandResult

_SLOT_TOKENS = {
    "头": "head", "头部": "head", "head": "head",
    "躯干": "torso", "torso": "torso",
    "手臂": "arm", "手": "arm", "arm": "arm",
    "腿": "leg", "腿部": "leg", "leg": "leg",
}


class CalcToolsCommandHandler(ToolboxDomainHandler):
    """处理咨询、同步器等级计算、愿望单与超限洗词条命令。"""

    async def _counsel(self, context: CommandContext, action: str, value: str) -> str:
        bank = self.services.counsel
        if not action.strip():
            return "用法：/妮姬 咨询 <妮姬名或别名> [问题关键词]"
        result = bank.search(action, value)
        return render_counsel_search(result, bank)

    async def _sync(self, context: CommandContext, action: str, value: str) -> str:
        key = action.strip().casefold()
        table = self.services.sync_table
        if key in {"", "帮助", "help"}:
            state = (
                f"成本表：{table.label}（核验 {table.checked_at}）"
                if table is not None
                else self.services.sync_table_error
            )
            return (
                "【同步器等级计算】\n"
                f"{state}\n"
                "手工：/妮姬 同步器 计算 <当前> <目标> <芯尘库存> <信用点库存> <战斗数据库存> "
                "<芯尘日产> <信用点日产> <战斗数据日产>\n"
                "账号：/妮姬 同步器 计算 账号 <目标> <芯尘日产> <信用点日产> <战斗数据日产>\n"
                "手工成本（无成本表）：/妮姬 同步器 计算 手工 <当前> <目标> <三项库存> <三项日产> <三项累计成本>\n"
                "只读：/妮姬 同步器 状态"
            )
        if key in {"状态", "status"}:
            account = self._account(context)
            if account is None:
                return "尚未绑定账号；可改用 /妮姬 同步器 计算 手工输入当前等级。"
            profile = await self._load_profile(account)
            outpost = profile.get("outpost") if isinstance(profile, Mapping) else None
            level = outpost.get("synchro_level") if isinstance(outpost, Mapping) else None
            if not isinstance(level, int) or isinstance(level, bool):
                return "上游未返回同步器等级（缺失）。可改用 /妮姬 同步器 计算 手工输入。"
            return f"当前同步器等级：{level}（来自已绑定账号只读资料）"
        if key not in {"计算", "calc", "calculate"}:
            return "用法：/妮姬 同步器 计算 <当前> <目标> ... 或 /妮姬 同步器 状态"
        tokens = [token for token in re.split(r"[\s,，]+", value.strip()) if token]
        today = self._clock().date()
        if tokens and tokens[0] in {"手工", "manual"}:
            if len(tokens) != 12:
                return (
                    "手工成本模式需要 11 个数字：当前、目标、三项库存、三项日产、三项累计成本。\n"
                    "例如：/妮姬 同步器 计算 手工 200 210 0 0 0 400 1000 100 3000 4500 1200"
                )
            try:
                plan = calculate_sync_plan(
                    current=tokens[1],
                    target=tokens[2],
                    inventory=dict(zip(("core_dust", "credits", "battle_data"), tokens[3:6])),
                    production=dict(zip(("core_dust", "credits", "battle_data"), tokens[6:9])),
                    table=None,
                    manual_costs=dict(zip(("core_dust", "credits", "battle_data"), tokens[9:12])),
                    today=today,
                )
            except SyncLevelInputError as exc:
                return str(exc)
            return render_sync_plan(plan)
        if table is None:
            return (
                self.services.sync_table_error
                + "\n也可使用手工成本：/妮姬 同步器 计算 手工 <当前> <目标> <三项库存> <三项日产> <三项累计成本>"
            )
        if tokens and tokens[0] == "账号":
            if len(tokens) != 5:
                return "账号模式需要：目标等级、芯尘日产、信用点日产、战斗数据日产。"
            account = self._account(context)
            if account is None:
                return "尚未绑定账号；请使用手工模式或在私聊先绑定。"
            profile = await self._load_profile(account)
            basic = profile.get("basic") if isinstance(profile, Mapping) else None
            outpost = profile.get("outpost") if isinstance(profile, Mapping) else None
            level = outpost.get("synchro_level") if isinstance(outpost, Mapping) else None
            if not isinstance(level, int) or isinstance(level, bool):
                return "上游未返回同步器等级（缺失），无法以账号模式计算。"
            inventory = self._currencies(basic)
            _, target, *production = tokens
            try:
                plan = calculate_sync_plan(
                    current=level,
                    target=target,
                    inventory=inventory,
                    production=dict(zip(("core_dust", "credits", "battle_data"), production)),
                    table=table,
                    today=today,
                )
            except SyncLevelInputError as exc:
                return str(exc)
            return "当前等级来自已绑定账号只读资料。\n" + render_sync_plan(plan)
        if len(tokens) != 8:
            return (
                "手工模式需要 8 个数字：当前、目标、三项库存、三项日产。\n"
                "例如：/妮姬 同步器 计算 200 210 0 0 0 400 1000 100"
            )
        try:
            plan = calculate_sync_plan(
                current=tokens[0],
                target=tokens[1],
                inventory=dict(zip(("core_dust", "credits", "battle_data"), tokens[2:5])),
                production=dict(zip(("core_dust", "credits", "battle_data"), tokens[5:8])),
                table=table,
                today=today,
            )
        except SyncLevelInputError as exc:
            return str(exc)
        return render_sync_plan(plan)

    @staticmethod
    def _currencies(basic: Any) -> dict[str, int]:
        mapping = {3000: "core_dust", 2000: "credits", 1000: "battle_data"}
        result: dict[str, int] = {}
        currencies = basic.get("currencies") if isinstance(basic, Mapping) else None
        for item in currencies or ():
            if not isinstance(item, Mapping):
                continue
            kind = mapping.get(item.get("type"))
            amount = item.get("value")
            if kind is None:
                continue
            try:
                result[kind] = int(amount)
            except (TypeError, ValueError):
                continue
        return result

    async def _wishlist(self, context: CommandContext, action: str, value: str) -> str:
        strategy = normalize_strategy(action or "balanced")
        owned, source_note = await self._wishlist_owned(context, value)
        result = recommend(
            self.services.wishlist_rows,
            owned,
            strategy,
            exclusions=self.services.wishlist_exclusions,
        )
        text = render_wishlist(result)
        return (source_note + "\n" + text) if source_note else text

    async def _wishlist_owned(self, context: CommandContext, value: str):
        if value.strip():
            return parse_owned(
                value,
                rows=self.services.wishlist_rows,
                resolver=getattr(self.services, "grid_resolver", None),
            ), "角色来源：手工输入。"

        account = self._account(context)
        if account is not None:
            try:
                rows = await self._load_roster(account)
            except Exception:
                rows = []
            if rows:
                owned = tuple(
                    OwnedCharacter(
                        name_code=str(row.get("name_code") or ""),
                        name="",
                        burst=str(row.get("burst") or ""),
                        limit_break=int(row.get("grade") or 0)
                        if str(row.get("grade") or "0").isdigit()
                        else 0,
                    )
                    for row in rows
                    if isinstance(row, Mapping) and row.get("name_code") not in (None, "")
                )
                if owned:
                    return owned, "角色来源：已绑定登录账号角色库。"

        binding = self._fresh_readonly_binding(context)
        if binding is None:
            raise ValueError(
                "未找到可用登录角色库，也没有 fresh 的 ShiftyPad 只读绑定；"
                "请手工输入角色池（例如 /妮姬 愿望单 均衡 拉毗:2,迪塞尔:0）"
                "或先私聊 /妮姬 我的妮姬 导入。"
            )
        characters = binding.profile.characters
        if not characters:
            raise ValueError(
                "ShiftyPad 只读快照没有角色字段（明确缺口，未用角色数量替代角色池）。"
                "请重新同步公开档案，或手工输入角色池。"
            )
        directory = self._character_directory()
        owned_items: list[OwnedCharacter] = []
        missing_grade = 0
        for character in characters:
            code = str(character.name_code or "").strip()
            if not code:
                continue
            row = directory.get(code, {})
            if character.grade is None:
                missing_grade += 1
            owned_items.append(
                OwnedCharacter(
                    name_code=code,
                    name=str(row.get("name_zh_cn") or row.get("name_zh_tw") or ""),
                    burst=str(row.get("burst") or ""),
                    limit_break=int(character.grade or 0),
                )
            )
        if not owned_items:
            raise ValueError("ShiftyPad 只读快照没有可用角色标识，无法生成愿望单。")
        note = (
            f"角色来源：ShiftyPad 只读快照（{len(owned_items)} 名，"
            f"{binding.last_sync_at}）。"
        )
        if missing_grade:
            note += f" {missing_grade} 名缺乏突破字段，按 0 参与推荐（未验证）。"
        return tuple(owned_items), note

    async def _overload(self, context: CommandContext, action: str, value: str) -> CommandResult | str:
        return self._overload_advice(action, value, simulate_attempts=None)

    async def _overload_sim(self, context: CommandContext, action: str, value: str) -> CommandResult | str:
        return self._overload_advice(action, value, simulate_attempts=100)

    def _overload_advice(self, action: str, value: str, *, simulate_attempts: int | None):
        targets, counts, flex, source_label = self._overload_targets(action)
        options = self._parse_overload_spec(value)
        advice = advise(
            options,
            targets,
            recommendation_label=source_label,
            target_counts=counts,
            flex_count=flex,
        )
        if simulate_attempts is not None:
            simulation = simulate(
                options, advice.targets, attempts=simulate_attempts, seed=0
            )
            advice = replace(advice, simulation=simulation)
        return render_advice(advice)

    def _overload_targets(self, action: str):
        text = action.strip()
        if not text:
            raise OverloadAdviceError(
                "请提供目标词条；用法：/妮姬 洗词条 <目标,目标> <部位,位置,词条,阶级[,锁]/...>"
            )
        if text in {"推荐", "recommend"}:
            raise OverloadAdviceError("请使用：/妮姬 洗词条 推荐:<角色名>")
        if text.startswith(("推荐:", "推荐：")):
            character = re.sub(r"^推荐[:：]\s*", "", text, count=1).strip()
            selected = self._character_overload_targets(character)
            if selected is not None:
                source = (
                    f"导入角色推荐 · {selected.source_url} · 核验 {selected.checked_at}"
                )
                return (
                    tuple(selected.targets),
                    dict(selected.counts),
                    selected.flex_count,
                    source,
                )
            mapping = getattr(self.services, "overload_recommendations", {}) or {}
            default_targets = mapping.get("__default__")
            if default_targets:
                return (
                    tuple(default_targets),
                    dict(getattr(self.services, "overload_default_counts", {}) or {}),
                    0,
                    "导入默认目标（非角色专属）",
                )
            label = getattr(self.services, "overload_recommendation_label", "")
            hint = f"（已加载：{label}）" if label else ""
            raise OverloadAdviceError(
                f"缺少角色“{character}”的可靠推荐表{hint}；请手工提供目标词条。"
            )
        return parse_targets(text), {}, 0, ""

    def _character_overload_targets(self, query: str):
        characters = getattr(self.services, "overload_character_targets", {}) or {}
        if not characters:
            return None
        normalized = unicodedata.normalize("NFKC", str(query or "")).casefold().strip()
        direct = next((key for key in characters if key.casefold() == normalized), None)
        if direct is not None:
            return characters[direct]
        for row in getattr(self.services, "grid_rows", ()):
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("character_key") or "")
            if key not in characters:
                continue
            aliases = (
                row.get("name_cn"), row.get("name_zh_tw"), row.get("name_en"),
                row.get("name"), row.get("name_code"),
            )
            if any(
                isinstance(value, (str, int))
                and unicodedata.normalize("NFKC", str(value)).casefold().strip() == normalized
                for value in aliases
            ):
                return characters[key]
        return None

    @staticmethod
    def _parse_overload_spec(value: str):
        text = str(value or "").strip()
        if not text:
            raise OverloadAdviceError(
                "请提供现有词条；格式：部位,位置,词条,阶级[,锁]/...，例如 头部,1,攻击力增加,15,锁"
            )
        records = []
        for chunk in text.split("/"):
            fields = [field.strip() for field in chunk.replace("，", ",").split(",")]
            if len(fields) not in (4, 5):
                raise OverloadAdviceError("每条词条需要 部位,位置,词条,阶级[,锁] 四个或五个字段")
            slot = _SLOT_TOKENS.get(fields[0].casefold(), fields[0])
            record = {
                "slot": slot,
                "position": fields[1],
                "label": fields[2],
                "tier": fields[3],
            }
            if len(fields) == 5:
                record["locked"] = fields[4] in {"锁", "锁定", "lock", "1", "true"}
            records.append(record)
        return parse_options(records)


__all__ = ["CalcToolsCommandHandler"]
