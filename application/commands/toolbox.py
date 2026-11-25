# SPDX-License-Identifier: GPL-3.0-or-later
"""本地工具命令用例门面与按领域拆分后的统一装配工厂。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .calc_tools import CalcToolsCommandHandler
from .contracts import CommandContext, CommandResult
from .favorite_grid import FavoriteGridCommandHandler, GridRenderer
from .growth import GrowthCommandHandler
from .info_feeds import InfoFeedsCommandHandler
from .shiftypad import ShiftypadCommandHandler
from .solo_raid import SoloRaidCommandHandler, SoloRenderer

FEATURE_TO_DOMAIN_ATTR: dict[str, str] = {
    "gacha": "info_feeds",
    "news": "info_feeds",
    "counsel": "calc_tools",
    "sync": "calc_tools",
    "wishlist": "calc_tools",
    "overload": "calc_tools",
    "overload_sim": "calc_tools",
    "soloraid": "solo_raid",
    "uid": "shiftypad",
    "growth": "growth",
    "grid": "favorite_grid",
    "grid_rank": "favorite_grid",
}


def build_toolbox_handlers(
    services: Any,
    *,
    render_grid: GridRenderer | None = None,
    render_solo: SoloRenderer | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """按业务领域实例化六组独立的工具命令处理器。"""
    if services is None:
        return {
            "info_feeds": None,
            "calc_tools": None,
            "solo_raid": None,
            "shiftypad": None,
            "growth": None,
            "favorite_grid": None,
        }
    return {
        "info_feeds": InfoFeedsCommandHandler(services, clock=clock),
        "calc_tools": CalcToolsCommandHandler(services, clock=clock),
        "solo_raid": SoloRaidCommandHandler(services, render_solo=render_solo, clock=clock),
        "shiftypad": ShiftypadCommandHandler(services, clock=clock),
        "growth": GrowthCommandHandler(services, clock=clock),
        "favorite_grid": FavoriteGridCommandHandler(services, render_grid=render_grid, clock=clock),
    }


class ToolboxCommandHandler:
    """兼容既有集成调用方的轻量门面，内部严格委托给各领域处理器。"""

    def __init__(
        self,
        services: Any,
        *,
        render_grid: GridRenderer | None = None,
        render_solo: SoloRenderer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.services = services
        self._domain_handlers = build_toolbox_handlers(
            services,
            render_grid=render_grid,
            render_solo=render_solo,
            clock=clock,
        )

    async def handle(self, context: CommandContext) -> CommandResult:
        feature = context.parameters.get("feature", "").strip()
        attr = FEATURE_TO_DOMAIN_ATTR.get(feature)
        delegate = self._domain_handlers.get(attr) if attr else None
        if delegate is None:
            delegate = InfoFeedsCommandHandler(self.services)
        return await delegate.handle(context)


__all__ = [
    "FEATURE_TO_DOMAIN_ATTR",
    "ToolboxCommandHandler",
    "build_toolbox_handlers",
]
