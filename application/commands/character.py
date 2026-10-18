# SPDX-License-Identifier: GPL-3.0-or-later
"""角色练度、个人角色卡与公开资料命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from ...core.privacy import safe_exception_message
from ...features.character.application import (
    CharacterAmbiguousMatch,
    CharacterApplication,
    CharacterInfoData,
    CharacterNotFound,
    CharacterNotOwned,
    CharacterRosterData,
)
from ...features.character.models import (
    CharacterCardData,
    CharacterCardRequest,
)
from ...features.character.roster_ranking import order_roster_entries
from ...integrations.blablalink.client import BlaBlaError, CookieExpired
from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandResult,
    ImageReply,
    TextReply,
)


RosterPresenter = Callable[[CharacterRosterData], Awaitable[str | None]]
CardPresenter = Callable[[CharacterCardData], Awaitable[str | None]]


class CharacterCommandHandler:
    """把角色查询编排收在命令用例，渲染与宿主反馈由注入端口提供。"""

    def __init__(
        self,
        *,
        application: CharacterApplication,
        directory: Callable[[], Sequence[Mapping[str, Any]]],
        render_roster: RosterPresenter,
        render_card: CardPresenter,
        invalidate_cookie: Callable[[str], None],
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._application = application
        self._directory = directory
        self._render_roster = render_roster
        self._render_card = render_card
        self._invalidate_cookie = invalidate_cookie
        self._start_feedback = start_feedback

    async def handle(self, context: CommandContext) -> CommandResult:
        operation = context.parameters.get("operation", "roster").strip().casefold()
        if operation == "info":
            return await self._info(context)
        if operation == "character":
            return await self._character(context)
        return await self._roster(context)

    async def _roster(self, context: CommandContext) -> CommandResult:
        try:
            data = await self._application.roster(
                context.actor_id, self._directory()
            )
            try:
                path = await self._render_roster(data)
            except Exception:
                path = None
            if isinstance(path, str) and path.strip():
                return CommandResult((ImageReply(path),))
            return self._text(self._format_roster(data))
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新绑定。")
        except Exception as exc:
            return self._text(f"练度查询失败：{safe_exception_message(exc)}")

    async def _character(self, context: CommandContext) -> CommandResult:
        query = context.parameters.get("name", "").strip()
        if not query:
            return self._text("用法：/妮姬 查询 练度 <角色名>")

        feedback = None
        if self._start_feedback is not None:
            feedback = self._start_feedback(context, "正在查询与渲染角色卡片...")
        try:
            request = CharacterCardRequest(
                qq_id=context.actor_id,
                query=query,
                directory=tuple(self._directory()),
            )
            result = await self._application.build_card(request)
            try:
                path = await self._render_card(result.card)
            except Exception:
                path = None
            if isinstance(path, str) and path.strip():
                return CommandResult((ImageReply(path),))
            return self._text(self._format_character_card(result.card))
        except CharacterAmbiguousMatch as exc:
            return self._text(self._ambiguous_message(exc))
        except CharacterNotFound:
            return self._text("查询失败：没有找到该妮姬")
        except CharacterNotOwned as exc:
            return self._text(str(exc))
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            return self._text(f"查询失败：{safe_exception_message(exc)}")
        except Exception as exc:
            return self._text(f"查询失败：{safe_exception_message(exc)}")
        finally:
            if feedback is not None:
                await feedback.cancel()

    async def _info(self, context: CommandContext) -> CommandResult:
        query = context.parameters.get("name", "").strip()
        if not query:
            return self._text("用法：/妮姬 查询 资料 <角色名>")
        try:
            data = self._application.info(query, self._directory())
        except CharacterNotFound:
            return self._text("没有找到该妮姬。")
        except CharacterAmbiguousMatch as exc:
            return self._text(self._ambiguous_message(exc))
        return self._text(self._format_info(data))

    @staticmethod
    def _ambiguous_message(error: CharacterAmbiguousMatch) -> str:
        candidates = "\n".join(
            f"{index}. {candidate}"
            for index, candidate in enumerate(error.candidates, 1)
        )
        suffix = "\n候选过多，请继续补全名称。" if error.too_many else ""
        return "找到多个角色，请输入更完整的名称：\n\n" + candidates + suffix

    @staticmethod
    def _format_info(data: CharacterInfoData) -> str:
        lines = [data.title, data.name]
        lines.extend(f"{label}：{value}" for label, value in data.rows)
        return "\n".join(lines)

    @staticmethod
    def _format_roster(data: CharacterRosterData) -> str:
        def number(value):
            if value is None:
                return "未返回"
            if isinstance(value, bool):
                return "无法识别"
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return "无法识别"
            return f"{parsed:,}" if parsed >= 1000 else str(parsed)

        def skill(value):
            if value is None:
                return "—"
            if isinstance(value, bool):
                return "?"
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return "?"
            return str(parsed) if parsed >= 0 else "?"

        characters = [
            item for item in data.characters if isinstance(item, Mapping)
        ]
        ordered = order_roster_entries(characters)
        total = len(data.characters)
        shown = ordered[:20]
        label = f"Top {len(shown)} / 共 {total} 名" if total > 20 else f"共 {total} 名"
        lines = [f"妮姬练度一览 · {data.commander_name} · {label}"]
        if not shown:
            lines.append("未获取到角色信息")
        summaries = getattr(data, "option_summaries", None)
        summaries = summaries if isinstance(summaries, Mapping) else {}
        for rank, item in enumerate(shown, 1):
            code = str(item.get("name_code") or "").strip()
            name = data.name_map.get(code) if code else None
            name = name or item.get("name_cn") or item.get("name") or "身份待核验"
            lines.append(
                f"{rank}. {name} · 等级 {number(item.get('lv'))} · 战力 {number(item.get('combat'))}"
                f" · 技能 {skill(item.get('skill1_lv'))}/{skill(item.get('skill2_lv'))}/{skill(item.get('ulti_skill_lv'))}"
                f" · 突破 {number(item.get('grade'))} · 核心 {number(item.get('core'))}"
            )
            if rank <= 3 and code:
                lines.extend(
                    CharacterCommandHandler._format_roster_options(
                        summaries.get(code)
                    )
                )
        return "\n".join(lines)

    @staticmethod
    def _format_roster_options(summary: Any) -> list[str]:
        """按同一 DTO 词条摘要生成文本；未知状态绝不显示成零或“无词条”。"""
        if summary is None:
            return []
        status = getattr(summary, "status", "")
        rows = getattr(summary, "rows", ()) or ()
        total = getattr(summary, "total", 0)
        complete = bool(getattr(summary, "complete", False))
        if status in ("ok", "partial") and rows:
            head = (
                f"词条合计：{total}阶"
                if complete
                else f"已知词条合计：{total}阶 · 部分词条未识别"
            )
            out = [head]
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                label = str(row.get("label", "") or "")
                value = str(row.get("value", "") or "")
                tier = str(row.get("tier", "") or "")
                note = str(row.get("note", "") or "")
                suffix = f"（{note}）" if note else ""
                out.append(f"- 【{label}】{value} {tier}{suffix}")
            return out
        message = str(getattr(summary, "message", "") or "")
        if status == "none":
            return ["词条：无装备词条"]
        if status == "unknown":
            return ["词条：词条字段未识别"]
        return [f"词条：{message or '详情未返回'}"]

    @staticmethod
    def _format_character_card(data: CharacterCardData) -> str:
        def value(item):
            if item is None:
                return "未知"
            if isinstance(item, bool):
                return str(item)
            if isinstance(item, int):
                return f"{item:,}"
            return str(item)

        name = data.name_cn or data.name_en or f"角色 {data.name_code}"
        lines = [
            f"妮姬练度 · {name}",
            f"稀有度：{value(data.rarity)} · 属性：{value(data.element)} · 武器：{value(data.weapon)}",
            f"爆裂阶段：{value(data.burst)} · 企业：{value(data.corporation)}",
            f"等级：{value(data.level)} · 战力：{value(data.combat)}",
            f"技能：{value(data.skill1_level)} / {value(data.skill2_level)} / {value(data.burst_skill_level)}",
            f"突破：{value(data.grade)} · 核心：{value(data.core)} · 好感：{value(data.bond_level)}",
        ]
        for slot, equipment in data.equipment.items():
            state = "已装备" if equipment.equipped else "未装备"
            level = f" Lv.{value(equipment.level)}" if equipment.level is not None else ""
            options = "、".join(
                f"{option.display_name} {value(option.value)}{option.unit}"
                for option in equipment.options
            )
            lines.append(f"装备 {slot}：{state}{level}" + (f" · {options}" if options else ""))
        if data.favorite_item is not None:
            item = data.favorite_item
            lines.append(
                f"收藏品：{item.display_name or '未知'} · 等级 {value(item.level)}"
            )
        if data.cube is not None:
            lines.append(f"魔方：{data.cube.display_name or '未知'} · 等级 {value(data.cube.level)}")
        if data.option_totals:
            lines.append("词条汇总：")
            lines.extend(
                f"{item.display_name}：{value(item.value)}{item.unit}"
                for item in data.option_totals
            )
        lines.extend(
            [f"更新时间：{data.fetched_at}", "图片暂不可用，以上内容来自本次查询快照。"]
        )
        return "\n".join(lines)

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
