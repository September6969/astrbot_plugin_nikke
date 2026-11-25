# SPDX-License-Identifier: GPL-3.0-or-later
"""本命九宫格与本命人气榜命令用例（29）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from ...features.favorite_grid.grid import render_ranking, resolve_nine
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext, CommandResult, ImageReply

GridRenderer = Callable[[Any], Awaitable[Any]]


class FavoriteGridCommandHandler(ToolboxDomainHandler):
    """处理九宫格生成与本命人气榜查询。"""

    def __init__(
        self,
        services: Any,
        *,
        render_grid: GridRenderer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(services, clock=clock)
        self._render_grid = render_grid

    async def _grid(self, context: CommandContext, action: str, value: str) -> CommandResult | str:
        text = f"{action} {value}".strip()
        cells = resolve_nine(text, self.services.grid_rows, self.services.grid_resolver)
        self.services.grid_ranking.vote(context.actor_id, cells)
        if self._render_grid is not None:
            rendered = await self._render_grid(cells)
            if isinstance(rendered, str) and rendered.strip():
                return CommandResult((ImageReply(rendered),))
        names = " / ".join(f"P{cell.index} {cell.name}" for cell in cells)
        return "九宫格：\n" + names + "\n（图片生成失败，已显示顺序列表；投票已记录。）"

    async def _grid_rank(self, context: CommandContext, action: str, value: str) -> str:
        return render_ranking(self.services.grid_ranking.ranking(limit=10))


__all__ = ["FavoriteGridCommandHandler", "GridRenderer"]
