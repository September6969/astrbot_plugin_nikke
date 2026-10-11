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
        from ...features.account.errors import CredentialExpiredError
        operation = context.parameters.get("operation", "overview").strip().casefold()
        if operation not in {"overview", "ranking", "member"}:
            return self._text("用法：/妮姬 突袭 [排名|我的] [页码]")
        raw_page = context.parameters.get("page", "1")
        if not isinstance(raw_page, str) or not raw_page.isascii() or not raw_page.isdigit() or len(raw_page) > 6 or int(raw_page) < 1:
            return self._text("页码须为正整数；用法：/妮姬 突袭 [排名|我的] [页码]")
        page = int(raw_page)
        feedback = self._start_feedback(context, "正在查询联盟突袭战况...") if self._start_feedback else None
        try:
            if operation == "overview":
                data = await self._application.dashboard(context.actor_id)
            elif operation == "ranking":
                data = await self._application.ranking_page(context.actor_id, page)
            else:
                data = await self._application.member_page(context.actor_id, page)
            try:
                path = (await self._render_overview(data) if operation == "overview" else
                    await self._render_ranking("union_records" if operation == "ranking" else "union_member", data))
            except Exception:
                path = None
            if path:
                return CommandResult((ImageReply(path),))
            if operation != "overview":
                return self._text(format_ranking(data))
            from ...features.raid.experience import format_dashboard
            return self._text(format_dashboard(data))
        except CredentialExpiredError:
            self._invalidate_cookie(context.actor_id)
            return self._text("登录状态已失效，请重新发送 /妮姬 账号 绑定。")
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            return self._text(f"突袭查询失败：{safe_exception_message(exc)}")
        except Exception:
            return self._text("突袭查询暂不可用，请稍后重试。")
        finally:
            if feedback is not None:
                await feedback.cancel()

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
