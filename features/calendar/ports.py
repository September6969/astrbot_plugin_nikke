# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 用例依赖的视觉缓存端口。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import CalendarActivity


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
