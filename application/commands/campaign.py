"""战役命令输入、错误文案与图片结果适配。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from ...core.privacy import safe_exception_message
from ...features.campaign.application import CampaignApplication
from ...features.campaign.models import ClearLineupStatus, StageClearRecord
from ...integrations.blablalink.client import BlaBlaError, CookieExpired
from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandResult,
    ImageReply,
    TextReply,
)


_LOGGER = logging.getLogger(__name__)
_USAGE = "用法：/妮姬 战役 [普通/困难] <关卡名>（例如：46-40、困难 35-36）"
_COOKIE_EXPIRED = "登录状态已失效，请重新发送 /妮姬 账号 绑定。"


class CampaignCommandHandler:
    def __init__(
        self,
        *,
        application: CampaignApplication,
        present: Callable[[StageClearRecord], Awaitable[str]],
        invalidate_cookie: Callable[[str], None],
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._application = application
        self._present = present
        self._invalidate_cookie = invalidate_cookie
        self._start_feedback = start_feedback

    async def handle(self, context: CommandContext) -> CommandResult:
        stage_text = context.parameters.get("stage", "")
        mode_text = context.parameters.get("mode", "")
        query = f"{stage_text} {mode_text}".strip()
        if not query:
            return CommandResult((TextReply(_USAGE),))

        stage = self._application.resolve(query)
        if stage is None:
            return CommandResult(
                (
                    TextReply(
                        f"未找到关卡：{query}。目前仅支持已收录关卡（如普通46章、困难35章）。"
                    ),
                )
            )

        feedback = None
        try:
            if self._start_feedback is not None:
                feedback = self._start_feedback(
                    context, "正在查询战役通关阵容..."
                )
            record = await self._application.lookup(context.actor_id, stage)
            if record.status in {ClearLineupStatus.RATE_LIMITED, ClearLineupStatus.ERROR}:
                return CommandResult((TextReply(record.status_message),))
            return CommandResult((ImageReply(await self._present(record)),))
        except CookieExpired:
            self._invalidate_cookie(context.actor_id)
            return CommandResult((TextReply(_COOKIE_EXPIRED),))
        except (BlaBlaError, ValueError, RuntimeError) as exc:
            return CommandResult(
                (TextReply(f"战役查询失败：{safe_exception_message(exc)}"),)
            )
        except Exception as exc:
            _LOGGER.error("[NIKKE] 战役查询异常: %s", safe_exception_message(exc))
            return CommandResult(
                (TextReply(f"战役查询异常：{safe_exception_message(exc)}"),)
            )
        finally:
            if feedback is not None:
                await feedback.cancel()
