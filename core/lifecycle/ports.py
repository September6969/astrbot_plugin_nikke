# SPDX-License-Identifier: GPL-3.0-or-later
"""生命周期编排依赖的持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol


class SchedulerSettingsStore(Protocol):
    """scheduler 仅需读取持久化的时刻配置。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取一个已配置的时刻设置。"""
