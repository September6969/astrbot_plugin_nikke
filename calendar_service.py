# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 结构化活动日程服务。

包装并继承 ScheduleService，提供 100% 向后兼容的 CalendarService 接口：
1. 维护本地结构化 activity snapshot，支持原子缓存写入；
2. 规范化 7/14/30 天 horizon 过滤，默认 14 天；
3. 输出互斥的【即将结束】、【进行中】、【即将开始】三组展示；
4. 同步失败时绝不破坏现有缓存，保留旧快照并提供告警提示；
5. list_reminder_deadlines 必须只返回 active 活动；
6. 统一使用 timezone-aware UTC datetime 计算，CST (UTC+8) 展示。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .schedule_service import ScheduleService, CAT_LABELS, CST
from .calendar_models import CalendarActivity, _aware_utc
from .calendar_sources import GameKeeNikkeScheduleSource

__all__ = ["CalendarService", "CAT_LABELS", "CST", "CalendarActivity", "GameKeeNikkeScheduleSource"]


class CalendarService(ScheduleService):
    """向下兼容的日历服务类，完整继承统一 ScheduleService。"""

    def __init__(self, data_dir: Path | str, **kwargs: Any) -> None:
        super().__init__(data_dir, **kwargs)
