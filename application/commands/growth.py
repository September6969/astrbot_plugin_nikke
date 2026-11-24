# SPDX-License-Identifier: GPL-3.0-or-later
"""养成历史快照命令用例（27）。"""

from __future__ import annotations

import re

from ...features.growth.history import (
    diff_points,
    growth_identity_key,
    render_growth_history,
)
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext

_DAYS_RE = re.compile(r"^(\d{1,3})\s*[天日d]?$")


class GrowthCommandHandler(ToolboxDomainHandler):
    """处理个人养成历史查询与清空命令。"""

    async def _growth(self, context: CommandContext, action: str, value: str) -> str:
        key = action.strip()
        service = self.services.growth
        roster = getattr(self.services, "roster_growth", None)
        if key in {"清空", "clear"}:
            service.clear(context.actor_id)
            if roster is not None:
                roster.clear(context.actor_id)
            return "已清空你的账号与角色养成历史快照。"
        account = self._account(context)
        ident = growth_identity_key(account)
        if key in {"7天", "30天"} or _DAYS_RE.fullmatch(key):
            match = _DAYS_RE.fullmatch(key)
            assert match is not None
            days = int(match.group(1))
            pts = service.query_range(context.actor_id, days=days, identity=ident)
            changes = diff_points(pts[-2], pts[-1]) if len(pts) >= 2 else ()
            return render_growth_history(
                pts,
                changes,
                roster=roster.latest(context.actor_id, identity=ident) if roster is not None else None,
            )
        if key not in {"", "状态", "history"}:
            return "用法：/妮姬 养成历史 [7天|30天|清空]"
        return render_growth_history(
            service.points(context.actor_id, identity=ident),
            service.changes(context.actor_id, identity=ident),
            roster=roster.latest(context.actor_id, identity=ident) if roster is not None else None,
        )


__all__ = ["GrowthCommandHandler"]
