# SPDX-License-Identifier: GPL-3.0-or-later
"""跨页面共享的 T2I 展示格式与已解析资产投影。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def display_number(value: Any) -> str:
    """格式化数值；缺失值保持显式未知。"""
    return "Unknown" if value is None else f"{value:,}"


def format_compact_number(value: Any) -> str:
    """以约三位有效数字呈现大型计数，不伪装非法输入。"""
    if value is None:
        return "Unknown"
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    if value < 0:
        return "-" + format_compact_number(-value)
    if value < 1000:
        return str(int(round(value)))
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= divisor:
            scaled = value / divisor
            if round(scaled, 2) < 10:
                return f"{scaled:.2f}{suffix}"
            if round(scaled, 1) < 100:
                return f"{scaled:.1f}{suffix}"
            if round(scaled, 0) < 1000:
                return f"{scaled:.0f}{suffix}"
    return f"{value / 1_000_000_000:.0f}B"


def display_remaining(value: str | None, now: datetime | None = None) -> str:
    """只格式化具备明确时区的时间，不猜测服务器时区。"""
    if not value:
        return "Unknown"
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if end.tzinfo is None:
            return "Unknown"
        seconds = (end - (now or datetime.now(timezone.utc))).total_seconds()
        if seconds <= 0:
            return "已结束"
        minutes = max(1, int(seconds // 60))
        if minutes >= 1440:
            return f"{minutes // 1440}天 {minutes % 1440 // 60}小时"
        return f"{minutes // 60}小时 {minutes % 60}分钟"
    except (ValueError, TypeError):
        return "Unknown"


def boss_presentation(
    assets: Any,
    resolver: Any,
    boss_id: Any,
    icon_id: Any = None,
    monster_model_id: Any = None,
    name: str | None = None,
) -> dict[str, Any]:
    """只消费已解析的本地 Boss 资产；不确认时保留显式回退状态。"""
    result = {
        "name": name or f"Boss ID {boss_id}",
        "boss_image_data_uri": None,
        "asset_state": "UNRESOLVED",
        "is_fallback": True,
    }
    if assets is None:
        return result
    try:
        asset = assets.resolve_boss_asset(
            boss_id=boss_id,
            icon_id=icon_id,
            monster_model_id=monster_model_id,
            boss_name=name,
        )
        if not asset.is_fallback:
            image = resolver.encode(asset.local_path, (256, 192))
            if image:
                result.update(
                    name=asset.boss_name or result["name"],
                    boss_image_data_uri=image,
                    asset_state="resolved",
                    is_fallback=False,
                )
    except Exception:
        pass
    return result
