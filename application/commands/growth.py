# SPDX-License-Identifier: GPL-3.0-or-later
"""养成历史快照命令用例（27）。"""

from __future__ import annotations

from ...features.growth.history import render_growth_history
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext


class GrowthCommandHandler(ToolboxDomainHandler):
    """处理个人养成历史查询与清空命令。"""

    async def _growth(self, context: CommandContext, action: str, value: str) -> str:
        if action.strip() in {"清空", "clear"}:
            self.services.growth.clear(context.actor_id)
            return "已清空你的养成历史快照。"
        if action.strip() not in {"", "状态", "history"}:
            return "用法：/妮姬 养成历史 [清空]"
        service = self.services.growth
        roster = getattr(self.services, "roster_growth", None)
        return render_growth_history(
            service.points(context.actor_id),
            service.changes(context.actor_id),
            roster=roster.latest(context.actor_id) if roster is not None else None,
        )


__all__ = ["GrowthCommandHandler"]
