# SPDX-License-Identifier: GPL-3.0-or-later
"""插件运行时配置的安全边界。"""

from __future__ import annotations

import re
import logging
from collections.abc import Mapping
from ipaddress import ip_network
from typing import Any


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_LOGGER = logging.getLogger(__name__)
_UI_RENDERER_DEPRECATION_LOGGED = False

_NUMERIC_CONTRACTS = {
    "request_timeout": (20, 1, 300),
    "web_port": (6210, 1, 65535),
    "daily_hour": (8, 0, 23),
    "daily_minute": (10, 0, 59),
    "summary_hour": (8, 0, 23),
    "summary_minute": (30, 0, 59),
    "max_concurrency": (2, 1, 32),
    "community_run_action_budget": (5, 1, 20),
    "community_cycle_action_budget": (10, 1, 50),
    "community_action_interval_seconds": (5, 2, 60),
    "spine_worker_timeout": (4, 1, 5),
}


# 与 _conf_schema.json 的 bool 项一致；写开关默认全部关闭（fail-closed）。
_BOOLEAN_CONTRACTS = {
    "enable_arena": False,
    "arena_web_enabled": False,
    "arena_external_stats_enabled": False,
    "allow_group_bind": False,
    "voice_dynamic_enabled": True,
    "enable_daily_actions": False,
    "enable_announcement_push": False,
    "enable_cdk_redemption": False,
    "enable_shiftypad_readonly": False,
    "enable_public_share_api": False,
}
_STRING_CONTRACTS = {
    "public_base_url": "https://nikke.irises777.xyz",
    "web_host": "0.0.0.0",
    "web_trusted_proxy_ip": "",
    "binding_api_key": "",
    "spine_worker_path": "",
    "spine_worker_path_4_1": "",
    "spine_runtime_version": "4.0",
    "custom_character_aliases": "",
}
_TRUE_WORDS = frozenset({"true", "1", "yes", "on", "开", "开启", "是"})
_FALSE_WORDS = frozenset({"false", "0", "no", "off", "关", "关闭", "否", ""})


def bounded_bool(value: Any, *, default: bool) -> bool:
    """严格读取布尔值；字符串 "false"/"0"/"off" 为 False，无法识别的值回退默认值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        word = value.strip().casefold()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return default


def normalize_trusted_proxy(value: Any) -> str:
    """校验反代地址：单个 IP 或 CIDR 网段；非法值降级为空并告警，不阻断启动。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(ip_network(text, strict=False))
    except ValueError:
        _LOGGER.warning("web_trusted_proxy_ip 不是合法的 IP 或 CIDR，已忽略该配置")
        return ""


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
    """复制配置并统一图片路由；旧 ui_renderer 值只提示一次并收敛到 T2I。"""
    global _UI_RENDERER_DEPRECATION_LOGGED
    normalized = dict(config) if isinstance(config, Mapping) else {}
    normalized.pop("character_card_layout", None)
    raw_renderer = normalized.get("ui_renderer")
    if raw_renderer is not None and str(raw_renderer).strip().casefold() != "t2i":
        if not _UI_RENDERER_DEPRECATION_LOGGED:
            _LOGGER.warning(
                "ui_renderer 配置已弃用；所有图片页面统一使用 T2I，失败时回退同一查询结果文本。"
            )
            _UI_RENDERER_DEPRECATION_LOGGED = True
    normalized["ui_renderer"] = "t2i"
    for key, (default, minimum, maximum) in _NUMERIC_CONTRACTS.items():
        normalized[key] = bounded_int(
            normalized.get(key),
            default=default,
            minimum=minimum,
            maximum=maximum,
        )
    for key, bool_default in _BOOLEAN_CONTRACTS.items():
        normalized[key] = bounded_bool(normalized.get(key), default=bool_default)
    for key, str_default in _STRING_CONTRACTS.items():
        raw = normalized.get(key)
        if raw is None or isinstance(raw, (dict, list, tuple, set)):
            normalized[key] = str_default
        elif not isinstance(raw, str):
            normalized[key] = str(raw)
    normalized["web_trusted_proxy_ip"] = normalize_trusted_proxy(
        normalized["web_trusted_proxy_ip"]
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
