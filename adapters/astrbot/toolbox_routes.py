# SPDX-License-Identifier: GPL-3.0-or-later
"""本地工具命令的别名表与日程类型选择（05/04）。

单独成文件是为了让 ``command_runtime.py`` 只保留路由职责并满足体量门禁；
不改变任何命令的既有分派顺序。
"""

from __future__ import annotations

# 本地工具命令到应用层 feature 的稳定映射；新增别名只需在此登记。
TOOLBOX_COMMANDS: dict[str, str] = {
    "卡池": "gacha", "gacha": "gacha",
    "新闻": "news", "feeds": "news", "newsroom": "news",
    "咨询": "counsel", "counsel": "counsel",
    "同步器": "sync", "sync": "sync", "synclevel": "sync",
    "愿望单": "wishlist", "wishlist": "wishlist",
    "洗词条": "overload", "overload": "overload",
    "洗词条模拟": "overload_sim", "overloadsim": "overload_sim",
    "单人突袭": "soloraid", "soloraid": "soloraid", "solo_raid": "soloraid",
    "uid": "uid", "我的妮姬": "uid", "mynikke": "uid",
    "养成历史": "growth", "growth": "growth",
    "九宫格": "grid", "grid": "grid", "favorite": "grid",
    "本命榜": "grid_rank", "favorite_rank": "grid_rank",
}

CALENDAR_BOARD_GROUPS: frozenset[str] = frozenset({"卡池", "活动", "皮肤", "突袭"})

DOMAIN_HANDLER_ATTRS: dict[str, str] = {
    "gacha": "info_feeds",
    "news": "info_feeds",
    "counsel": "calc_tools",
    "sync": "calc_tools",
    "wishlist": "calc_tools",
    "overload": "calc_tools",
    "overload_sim": "calc_tools",
    "soloraid": "solo_raid",
    "uid": "shiftypad",
    "growth": "growth",
    "grid": "favorite_grid",
    "grid_rank": "favorite_grid",
}


def toolbox_feature(command_key: str) -> str | None:
    """返回命令对应的工具 feature；未登记时返回 None。"""
    return TOOLBOX_COMMANDS.get(str(command_key or "").strip().casefold())


def toolbox_handler_attr(feature: str) -> str | None:
    """返回功能对应的按领域拆分处理器字段名。"""
    return DOMAIN_HANDLER_ATTRS.get(str(feature or "").strip())


def is_calendar_board_group(value: str) -> bool:
    """日程命令的类型参数是否应转到卡池/活动日历视图。"""
    return str(value or "").strip() in CALENDAR_BOARD_GROUPS


__all__ = [
    "CALENDAR_BOARD_GROUPS",
    "DOMAIN_HANDLER_ATTRS",
    "TOOLBOX_COMMANDS",
    "is_calendar_board_group",
    "toolbox_feature",
    "toolbox_handler_attr",
]
