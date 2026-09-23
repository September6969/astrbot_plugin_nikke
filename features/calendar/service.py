# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 结构化活动日程服务 (CalendarService)。

本服务完全继承自底层统一 ScheduleService，全面具备：
1. Runtime Status Resolver 与精确时间语义；
2. 每源 LKG 与部分故障容灾机制；
3. 字段级证据、仲裁与手动覆盖层；
4. 视觉缓存 (CalendarVisualCache) 与背景管理；
5. 对旧版 v0.4 / v0.5 Calendar 测试与调用方 100% 向后兼容。
"""

from __future__ import annotations

from typing import Any

from .application import CalendarApplication
from astrbot_plugin_nikke.features.calendar.schedule_service import (
    ScheduleService,
    CAT_LABELS,
    CST,
)


class CalendarService(ScheduleService):
    """日程服务及与其生命周期绑定的共享应用查询入口。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.application = CalendarApplication(self)


__all__ = ["CalendarService", "CAT_LABELS", "CST"]
