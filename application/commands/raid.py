# SPDX-License-Identifier: GPL-3.0-or-later
"""联盟突袭 overview、ranking 与 member 命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ...core.privacy import safe_exception_message
from ...features.raid.application import (
    RaidApplication,
    RaidMemberIdentityUnavailable,
)
from ...features.raid.models import UnionRaidOverviewData
from ...features.raid.participants import RaidRankingData, format_ranking
from ...integrations.blablalink.client import BlaBlaError, CookieExpired
from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandResult,
    ImageReply,
    TextReply,
)


OverviewPresenter = Callable[[UnionRaidOverviewData], Awaitable[str]]
RankingPresenter = Callable[[str, RaidRankingData], Awaitable[str | None]]


class RaidCommandHandler:
    """持有联盟突袭命令流程，不依赖 AstrBot event 或结果类型。"""

    def __init__(
        self,
        *,
        application: RaidApplication,
        render_overview: OverviewPresenter,
        render_ranking: RankingPresenter,
        invalidate_cookie: Callable[[str], None],
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._application = application
        self._render_overview = render_overview
        self._render_ranking = render_ranking
        self._invalidate_cookie = invalidate_cookie
        self._start_feedback = start_feedback

    async def handle(self, context: CommandContext) -> CommandResult:
        operation = context.parameters.get("operation", "overview").strip().casefold()
        if operation == "ranking":
            return await self._ranking(context)
        if operation == "member":
            return await self._member(context)
        return await self._overview(context)

    async def _overview(self, context: CommandContext) -> CommandResult:
        feedback = None
        if self._start_feedback is not None:
            feedback = self._start_feedback(context, "正在查询联盟突袭战况...")
        try:
            data = await self._application.overview(context.actor_id)
            return CommandResult((ImageReply(await self._render_overview(data)),))
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            return self._text(f"突袭查询失败：{safe_exception_message(exc)}")
        except Exception as exc:
            return self._text(f"突袭查询异常：{safe_exception_message(exc)}")
        finally:
            if feedback is not None:
                await feedback.cancel()

    async def _ranking(self, context: CommandContext) -> CommandResult:
        try:
            data = await self._application.ranking(context.actor_id)
            path = await self._render_ranking("union_records", data)
            return (
                CommandResult((ImageReply(path),))
                if path
                else self._text(format_ranking(data))
            )
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新绑定。")
        except (BlaBlaError, ValueError):
            return self._text("突袭排名暂不可用：数据不完整或请求失败，请稍后重试。")

    async def _member(self, context: CommandContext) -> CommandResult:
        try:
            data = await self._application.member(context.actor_id)
            path = await self._render_ranking("union_member", data)
            return (
                CommandResult((ImageReply(path),))
                if path
                else self._text(format_ranking(data))
            )
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新绑定。")
        except RaidMemberIdentityUnavailable as exc:
            return self._text(str(exc))
        except (BlaBlaError, ValueError):
            return self._text("我的突袭记录暂不可用：数据不完整或请求失败，请稍后重试。")

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
