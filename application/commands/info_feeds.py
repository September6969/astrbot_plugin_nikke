# SPDX-License-Identifier: GPL-3.0-or-later
"""卡池与活动分类板、新闻/视频/日程统一订阅命令用例（04/05）。"""

from __future__ import annotations

from ...features.announcement.feeds import FeedSubscriptions
from ...features.calendar.board import build_board, normalize_group, render_board
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext


class InfoFeedsCommandHandler(ToolboxDomainHandler):
    """处理公开活动分类板与新闻/视频/日程订阅命令。"""

    async def _gacha(self, context: CommandContext, action: str, value: str) -> str:
        selected = normalize_group(action) if action.strip() else None
        if action.strip() and selected is None:
            return "未知类型；用法：/妮姬 卡池 [卡池|活动|皮肤|突袭]"
        application = getattr(self.services, "calendar", None)
        if application is None:
            return "日程服务尚未就绪，正在后台同步，请稍后重试。"
        snapshot = application.query_schedule()
        if not snapshot.service_available or not snapshot.has_snapshot:
            return "日程数据尚未就绪，正在后台同步，请稍后重试。"
        board = build_board(
            snapshot.context.events,
            snapshot.context.now,
            groups=(selected,) if selected else None,
        )
        return render_board(board)

    async def _news(self, context: CommandContext, action: str, value: str) -> str:
        feeds = self.services.feeds
        target = FeedSubscriptions.target_key(
            context.conversation_id, context.actor_id, context.is_private_chat
        )
        return feeds.command(target, action, value)


__all__ = ["InfoFeedsCommandHandler"]
