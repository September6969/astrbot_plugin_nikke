# SPDX-License-Identifier: GPL-3.0-or-later
"""生命周期编排依赖的持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol


class SchedulerSettingsStore(Protocol):
    """scheduler 读取持久化时刻配置，并记录每日汇总的幂等发送标记。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取一个已配置的时刻设置。"""

    def set_setting(self, key: str, value: Any) -> None:
        """写入调度幂等标记（如每日汇总已发送）。"""
