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
from ...integrations.blablalink.client import BlaBlaError, CookieExpired
from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandResult,
    ImageReply,
    TextReply,
)


RosterPresenter = Callable[[CharacterRosterData], Awaitable[str]]
CardPresenter = Callable[[CharacterCardData], Awaitable[str]]
InfoPresenter = Callable[[CharacterInfoData], Awaitable[str]]


class CharacterCommandHandler:
    """把角色查询编排收在命令用例，渲染与宿主反馈由注入端口提供。"""

    def __init__(
        self,
        *,
        application: CharacterApplication,
        directory: Callable[[], Sequence[Mapping[str, Any]]],
        render_roster: RosterPresenter,
        render_card: CardPresenter,
        render_info: InfoPresenter,
        invalidate_cookie: Callable[[str], None],
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._application = application
        self._directory = directory
        self._render_roster = render_roster
        self._render_card = render_card
        self._render_info = render_info
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
            return CommandResult((ImageReply(await self._render_roster(data)),))
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
            return CommandResult((ImageReply(await self._render_card(result.card)),))
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
        return CommandResult((ImageReply(await self._render_info(data)),))

    @staticmethod
    def _ambiguous_message(error: CharacterAmbiguousMatch) -> str:
        candidates = "\n".join(
            f"{index}. {candidate}"
            for index, candidate in enumerate(error.candidates, 1)
        )
        suffix = "\n候选过多，请继续补全名称。" if error.too_many else ""
        return "找到多个角色，请输入更完整的名称：\n\n" + candidates + suffix

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
