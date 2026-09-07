# SPDX-License-Identifier: GPL-3.0-or-later
"""插件运行时配置的安全边界。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_INTEGER_RE = re.compile(r"^[+-]?\d+$")

_NUMERIC_CONTRACTS = {
    "request_timeout": (20, 1, 300),
    "web_port": (6210, 1, 65535),
    "daily_hour": (8, 0, 23),
    "daily_minute": (10, 0, 59),
    "summary_hour": (8, 0, 23),
    "summary_minute": (30, 0, 59),
    "max_concurrency": (2, 1, 32),
}


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    """读取有限范围的整数；布尔值、浮点值和越界值都回退默认值。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str) and _INTEGER_RE.fullmatch(value.strip()):
        try:
            candidate = int(value.strip())
        except ValueError:
            return default
    else:
        return default
    return candidate if minimum <= candidate <= maximum else default


def normalize_runtime_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """复制配置并修正数值边界，不改变开关和其它未知配置。"""
    normalized = dict(config) if isinstance(config, Mapping) else {}
    for key, (default, minimum, maximum) in _NUMERIC_CONTRACTS.items():
        normalized[key] = bounded_int(
            normalized.get(key),
            default=default,
            minimum=minimum,
            maximum=maximum,
        )
    return normalized


def read_schedule_clock(
    read_setting,
    prefix: str,
    *,
    default_hour: int,
    default_minute: int,
) -> tuple[int, int]:
    """读取持久化时间；单个损坏字段只回退该字段，不让调度循环退出。"""

    def read_field(key: str, default: int) -> Any:
        """把损坏的持久化值隔离在字段边界内。"""
        try:
            return read_setting(key, default)
        except (TypeError, ValueError):
            return default

    hour = bounded_int(
        read_field(f"{prefix}_hour", default_hour),
        default=default_hour,
        minimum=0,
        maximum=23,
    )
    minute = bounded_int(
        read_field(f"{prefix}_minute", default_minute),
        default=default_minute,
        minimum=0,
        maximum=59,
    )
    return hour, minute
