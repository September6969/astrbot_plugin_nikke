# SPDX-License-Identifier: GPL-3.0-or-later
"""宿主消息投递与 T2I 渲染的迟绑定桥，维持 core/integrations 无跨层依赖。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class PortalHostBridge:
    """注入给大厅与工作台的宿主反馈能力；测试及容器初始化期间可为 None。"""

    send_to_qq: Callable[[str, str, Sequence[str]], Awaitable[str]] | None = None
    render_t2i: Callable[[str, Any], Awaitable[str | list[str] | None]] | None = None
    build_calendar_payload: Callable[[Any], Mapping[str, Any]] | None = None
    render_favorite_grid: Callable[[Any], Awaitable[str | None]] | None = None
    render_solo_raid: Callable[[Any, Any], Awaitable[str | None]] | None = None

    def attach(
        self,
        *,
        send_to_qq: Callable[[str, str, Sequence[str]], Awaitable[str]] | None = None,
        render_t2i: Callable[[str, str | Any], Awaitable[Any]] | None = None,
        build_calendar_payload: Callable[[Any], Mapping[str, Any]] | None = None,
        render_favorite_grid: Callable[[Any], Awaitable[str | None]] | None = None,
        render_solo_raid: Callable[[Any, Any], Awaitable[str | None]] | None = None,
    ) -> None:
        if send_to_qq is not None:
            self.send_to_qq = send_to_qq
        if render_t2i is not None:
            self.render_t2i = render_t2i
        if build_calendar_payload is not None:
            self.build_calendar_payload = build_calendar_payload
        if render_favorite_grid is not None:
            self.render_favorite_grid = render_favorite_grid
        if render_solo_raid is not None:
            self.render_solo_raid = render_solo_raid
