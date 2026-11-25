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
    render_character_recommendation,
    resolve_preset_targets,
    simulate,
)
from ...features.sync.calculator import (
    SyncLevelInputError,
    calculate_sync_plan,
    plan_sync_from_inputs,
    render_cost_lookup,
    render_gainable_report,
    render_sync_overview,
    render_sync_plan,
)
from ...features.sync.cost_table import RESOURCES
from ...features.sync.outpost import (
    extract_account_currencies,
    extract_account_sync_context,
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
        outpost_table = getattr(self.services, "outpost_table", None)
        today = self._clock().date()

        if key.isdigit() and not value.strip():
            return await self._sync_calc_account_target(context, key, table, outpost_table, today)

        if key in {"", "状态", "status"}:
            account = self._account(context)
            if account is not None and self.services.profile_loader is not None:
                profile = await self._load_profile(account)
                ctx = extract_account_sync_context(profile, outpost_table, table)
                if key == "" and ctx.synchro_level is None:
                    return self._sync_usage_text(table)
                return render_sync_overview(ctx, table)
            if key in {"状态", "status"}:
                return "尚未绑定账号；可改用 /妮姬 同步器 计算 <当前> <目标> 或手工输入。"
            return self._sync_usage_text(table)

        if key in {"帮助", "help"}:
            return self._sync_usage_text(table)

        if key in {"可升", "gainable", "upgrade"}:
            if table is None:
                return self.services.sync_table_error or "未配置同步器等级成本表。"
            manual_tokens = [t for t in re.split(r"[\s,，]+", value.strip()) if t]
            if len(manual_tokens) == 4 and all(t.isdigit() for t in manual_tokens):
                cur_lvl = int(manual_tokens[0])
                inv = dict(zip(RESOURCES, (int(x) for x in manual_tokens[1:4])))
                gained, reachable, remaining = table.gainable_levels(cur_lvl, inv)
                return (
                    f"【同步器即时可升（手工库存）】当前 Lv.{cur_lvl}\n"
                    f"可立即连续升级：+{gained} 级（可达 Lv.{reachable}）\n"
                    f"升级后剩余：芯尘 {remaining['core_dust']:,} / 信用点 {remaining['credits']:,} / 战斗数据 {remaining['battle_data']:,}"
                )
            account = self._account(context)
            if account is None:
                return "尚未绑定账号；请先 /妮姬 账号 绑定，或使用 /妮姬 同步器 可升 <当前等级> <芯尘> <信用点> <战斗数据>。"
            profile = await self._load_profile(account)
            ctx = extract_account_sync_context(profile, outpost_table, table)
            return render_gainable_report(ctx, table)

        if key not in {"计算", "calc", "calculate"}:
            return "用法：/妮姬 同步器｜/妮姬 同步器 计算 <目标等级>｜/妮姬 同步器 可升"

        tokens = [token for token in re.split(r"[\s,，]+", value.strip()) if token]
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
                    inventory=dict(zip(RESOURCES, tokens[3:6])),
                    production=dict(zip(RESOURCES, tokens[6:9])),
                    table=None,
                    manual_costs=dict(zip(RESOURCES, tokens[9:12])),
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

        if len(tokens) == 1 and tokens[0].isdigit():
            return await self._sync_calc_account_target(context, tokens[0], table, outpost_table, today)

        if len(tokens) == 2 and all(t.isdigit() for t in tokens):
            cur_lvl, tgt_lvl = int(tokens[0]), int(tokens[1])
            if tgt_lvl <= cur_lvl:
                return "目标等级必须高于当前等级。"
            bound_inv = None
            account = self._account(context)
            if account is not None and self.services.profile_loader is not None:
                try:
                    profile = await self._load_profile(account)
                    bound_inv = extract_account_currencies(profile.get("basic") if isinstance(profile, Mapping) else None)
                except Exception:
                    bound_inv = None
            try:
                return render_cost_lookup(cur_lvl, tgt_lvl, table, inventory=bound_inv)
            except Exception as exc:
                return str(exc)

        if tokens and tokens[0] == "账号":
            if len(tokens) != 5:
                return "账号手动日产模式需要：/妮姬 同步器 计算 账号 <目标> <芯尘日产> <信用点日产> <战斗数据日产>；也可直接 /妮姬 同步器 计算 <目标> 自动估算前哨产量。"
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
                    production=dict(zip(RESOURCES, production)),
                    table=table,
                    today=today,
                )
            except SyncLevelInputError as exc:
                return str(exc)
            return "当前等级来自已绑定账号只读资料。\n" + render_sync_plan(plan)

        if len(tokens) != 8:
            return (
                "用法：\n"
                "· 已绑定账号：/妮姬 同步器 计算 <目标等级>（例如 /妮姬 同步器 计算 600）\n"
                "· 查区间总消耗：/妮姬 同步器 计算 <当前> <目标>\n"
                "· 完整手工：/妮姬 同步器 计算 <当前> <目标> <芯尘库存> <信用点库存> <战斗数据库存> <芯尘日产> <信用点日产> <战斗数据日产>"
            )
        try:
            plan = calculate_sync_plan(
                current=tokens[0],
                target=tokens[1],
                inventory=dict(zip(RESOURCES, tokens[2:5])),
                production=dict(zip(RESOURCES, tokens[5:8])),
                table=table,
                today=today,
            )
        except SyncLevelInputError as exc:
            return str(exc)
        return render_sync_plan(plan)

    def _sync_usage_text(self, table: Any) -> str:
        state = (
            f"成本表：{table.label}（核验 {table.checked_at}）"
            if table is not None
            else self.services.sync_table_error
        )
        return (
            "【同步器等级计算】\n"
            f"{state}\n"
            "常用指令（绑定后自动读取等级、库存与前哨产量）：\n"
            "· /妮姬 同步器 — 查看当前同步器等级、前哨产量与可升等级\n"
            "· /妮姬 同步器 计算 600 — 自动估算升至目标等级的日期与瓶颈\n"
            "· /妮姬 同步器 可升 — 查看直接库存立即能升多少级\n"
            "未绑定/备用：/妮姬 同步器 计算 <当前> <目标> ｜ /妮姬 大厅（公开手动计算器）"
        )

    async def _sync_calc_account_target(
        self,
        context: CommandContext,
        target: str,
        table: Any,
        outpost_table: Any,
        today: Any,
    ) -> str:
        if table is None:
            return self.services.sync_table_error or "未配置同步器等级成本表。"
        account = self._account(context)
        if account is None:
            return (
                "尚未绑定账号，无法自动读取同步器等级与库存。\n"
                "可私聊 /妮姬 账号 绑定，或使用：/妮姬 同步器 计算 <当前等级> <目标等级> 查询所需消耗，或前往 /妮姬 大厅。"
            )
        profile = await self._load_profile(account)
        ctx = extract_account_sync_context(profile, outpost_table, table)
        if ctx.synchro_level is None:
            return "上游未返回同步器等级（缺失），无法以账号模式计算。"
        try:
            if ctx.outpost_rates is not None:
                plan, _ = plan_sync_from_inputs(
                    current=ctx.synchro_level,
                    target=target,
                    inventory=ctx.inventory,
                    outpost_level=ctx.outpost_level,
                    academy_class=ctx.academy_class,
                    wipeout_count=1,
                    table=table,
                    outpost_table=outpost_table,
                    today=today,
                )
                prefix = "当前等级、库存与前哨产量来自已绑定账号只读资料（按每日免费歼灭1次估算，含资源箱完整版见 /妮姬 工作台）。\n"
            else:
                plan = calculate_sync_plan(
                    current=ctx.synchro_level,
                    target=target,
                    inventory=ctx.inventory,
                    production={res: 0 for res in RESOURCES},
                    table=table,
                    today=today,
                )
                prefix = "当前等级与库存来自已绑定账号只读资料（未读取到前哨产量表，按 0 日产估算）。\n"
        except SyncLevelInputError as exc:
            return str(exc)
        return prefix + render_sync_plan(plan)

    @staticmethod
    def _currencies(basic: Any) -> dict[str, int]:
        return extract_account_currencies(basic)

    async def _wishlist(self, context: CommandContext, action: str, value: str) -> str:
        strategy = normalize_strategy(action or "balanced")
        owned, source_note = await self._wishlist_owned(context, value)
        result = recommend(
            self.services.wishlist_rows,
            owned,
            strategy,
            exclusions=self.services.wishlist_exclusions,
            eligibility=getattr(self.services, "wishlist_eligibility", None),
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
        return await self._overload_advice(context, action, value, simulate_attempts=None)

    async def _overload_sim(self, context: CommandContext, action: str, value: str) -> CommandResult | str:
        return await self._overload_advice(context, action, value, simulate_attempts=100)

    async def _overload_advice(
        self, context: CommandContext, action: str, value: str, *, simulate_attempts: int | None
    ):
        # 快捷入口：`/妮姬 洗词条 <角色名>`（无第二个参数且命中角色专属推荐库）
        if not value.strip() and action.strip() and not action.strip().startswith(("推荐:", "推荐：", "预设:", "预设：")):
            selected = self._character_overload_targets(action.strip())
            if selected is not None:
                loader = getattr(self.services, "card_loader", None)
                account = self._account(context)
                if account is not None and loader is not None:
                    try:
                        options, resolved_name = await self._load_bound_overload_options(context.actor_id, action.strip())
                        advice = advise(
                            options,
                            tuple(selected.targets),
                            recommendation_label=f"内置角色专属推荐 · {selected.source_url} · 核验 {selected.checked_at}",
                            target_counts=dict(selected.counts),
                            flex_count=selected.flex_count,
                            avoid_targets=selected.avoid,
                            character_note=selected.note,
                        )
                        if simulate_attempts is not None:
                            advice = replace(advice, simulation=simulate(options, advice.targets, attempts=simulate_attempts))
                        return f"词条来源：已绑定账号角色实际超限词条（{resolved_name}，只读对比）。\n" + render_advice(advice)
                    except OverloadAdviceError:
                        pass
                return render_character_recommendation(action.strip(), selected)

        targets, counts, flex, source_label, char_query, avoid, char_note = self._overload_targets(action)
        source_prefix = ""
        spec = value.strip()
        if spec in {"账号", "account"} or spec.startswith(("账号:", "账号：", "account:")):
            target_char = (
                re.sub(r"^(?:账号|account)[:：]\s*", "", spec, count=1).strip()
                or char_query
            )
            if not target_char:
                raise OverloadAdviceError("使用账号模式对比时请指定角色名，例如：/妮姬 洗词条 推荐:拉毗 账号")
            options, resolved_name = await self._load_bound_overload_options(context.actor_id, target_char)
            source_prefix = f"词条来源：已绑定账号角色实际超限词条（{resolved_name}，只读对比）。\n"
        else:
            options = self._parse_overload_spec(value)
        advice = advise(
            options,
            targets,
            recommendation_label=source_label,
            target_counts=counts,
            flex_count=flex,
            avoid_targets=avoid,
            character_note=char_note,
        )
        if simulate_attempts is not None:
            simulation = simulate(
                options, advice.targets, attempts=simulate_attempts
            )
            advice = replace(advice, simulation=simulation)
        return source_prefix + render_advice(advice)

    async def _load_bound_overload_options(self, actor_id: str, query: str):
        loader = getattr(self.services, "card_loader", None)
        if loader is None:
            raise OverloadAdviceError("当前未装配账号角色详情读取能力，请改用手工词条格式。")
        card = await loader(actor_id, query)
        records = []
        equipment = getattr(card, "equipment", None) or {}
        for slot in ("head", "torso", "arm", "leg"):
            piece = equipment.get(slot) if isinstance(equipment, Mapping) else None
            if piece is None or not getattr(piece, "equipped", False):
                continue
            for position, option in enumerate(getattr(piece, "options", ()) or (), 1):
                if position > 3:
                    break
                tier = getattr(option, "tier", None)
                records.append(
                    {
                        "slot": slot,
                        "position": position,
                        "label": str(getattr(option, "display_name", "") or ""),
                        "tier": tier if isinstance(tier, int) and 1 <= tier <= 15 else 1,
                        "locked": bool(getattr(option, "locked", False)),
                    }
                )
        if not records:
            raise OverloadAdviceError("该角色当前未检测到可解析的超限装备词条；请先确认已洗出 T10 词条或改用手工输入。")
        name = str(getattr(card, "name_cn", "") or getattr(card, "name_en", "") or query)
        return parse_options(records), name

    def _overload_targets(self, action: str):
        text = action.strip()
        if not text:
            raise OverloadAdviceError(
                "用法：/妮姬 洗词条 <角色名>（如 爱丽丝）｜/妮姬 洗词条 推荐:<角色名> 账号｜/妮姬 洗词条 <目标> <部位,位置,词条,阶>"
            )
        if text in {"推荐", "recommend"}:
            raise OverloadAdviceError("请使用：/妮姬 洗词条 推荐:<角色名> 或 /妮姬 洗词条 预设:<输出|蓄力|机枪|辅助|暴击>")
        if text.startswith(("预设:", "预设：")):
            preset_name = re.sub(r"^预设[:：]\s*", "", text, count=1).strip()
            preset_targets, preset_source = resolve_preset_targets(preset_name)
            return preset_targets, {}, 0, preset_source, "", (), ""
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
                    character,
                    tuple(selected.avoid),
                    selected.note,
                )
            mapping = getattr(self.services, "overload_recommendations", {}) or {}
            default_targets = mapping.get("__default__")
            if default_targets:
                return (
                    tuple(default_targets),
                    dict(getattr(self.services, "overload_default_counts", {}) or {}),
                    0,
                    "导入默认目标（非角色专属）",
                    character,
                    (),
                    "",
                )
            label = getattr(self.services, "overload_recommendation_label", "")
            hint = f"（已加载：{label}）" if label else ""
            raise OverloadAdviceError(
                f"缺少角色“{character}”的可靠推荐表{hint}；请手工提供目标词条。"
            )
        return parse_targets(text), {}, 0, "", "", (), ""

    def _character_overload_targets(self, query: str):
        characters = getattr(self.services, "overload_character_targets", {}) or {}
        if not characters:
            return None
        normalized = unicodedata.normalize("NFKC", str(query or "")).casefold().strip()
        direct = next((key for key in characters if key.casefold() == normalized), None)
        if direct is not None:
            return characters[direct]
        rows = getattr(self.services, "grid_rows", ())
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("character_key") or row.get("name_code") or "")
            if key not in characters:
                continue
            aliases = (
                row.get("name_cn"), row.get("name_zh_cn"), row.get("name_zh_tw"),
                row.get("name_en"), row.get("name"), row.get("name_code"),
            )
            if any(
                isinstance(value, (str, int))
                and unicodedata.normalize("NFKC", str(value)).casefold().strip() == normalized
                for value in aliases
            ):
                return characters[key]
        resolver = getattr(self.services, "grid_resolver", None)
        if resolver is not None and rows:
            for row in resolver.find(rows, query)[:5]:
                key = str(row.get("character_key") or row.get("name_code") or "")
                if key in characters:
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
