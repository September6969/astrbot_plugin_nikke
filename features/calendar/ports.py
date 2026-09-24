# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 用例依赖的外部读取与视觉缓存端口。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .models import CalendarActivity


class CalendarFetchGateway(Protocol):
    """读取公开日程接口 JSON 的传输端口。"""

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """执行只读 GET 并返回 JSON 响应。"""


class CalendarVisualPort(Protocol):
    """视觉素材缓存端口；失败不得影响结构化日程快照。"""

    def resolve_path(self, event_id: str) -> Path | None:
        """返回已缓存素材路径，不执行网络访问。"""

    def cached_event_ids(self) -> tuple[str, ...]:
        """返回当前素材清单中的事件键。"""

    async def sync(
        self,
        activities: list[CalendarActivity],
        *,
        now: datetime | None = None,
        horizon_days: int = 30,
        max_items: int = 16,
    ) -> dict[str, int]:
        """按预算同步近期活动视觉素材。"""
