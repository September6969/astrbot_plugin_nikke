# SPDX-License-Identifier: GPL-3.0-or-later
"""单角色 T2I payload 使用的稳定展示标签。"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


CHARACTER_EQUIPMENT_SLOT_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "head": "HEAD · 头部",
        "torso": "TORSO · 躯干",
        "arm": "ARM · 手臂",
        "leg": "LEG · 腿部",
    }
)


def format_equipment_option_value(option: Any) -> str:
    """按角色卡展示合同格式化装备词条数值。"""
    if option.unit == "empty":
        return "—"
    if option.unit == "percent":
        return f"{option.value * 100:.2f}%"
    if option.unit == "flat":
        return f"{round(option.value):,}"
    return "待确认"
