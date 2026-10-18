# SPDX-License-Identifier: GPL-3.0-or-later
"""练度总览的共享排序与稳定身份规则。

T2I 页面与文本回退必须复用同一排序来源，否则“详情 top-3”和“展示 top-3”
可能指向不同角色。这里只做纯数据投影，不触发任何网络或渲染副作用。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def roster_number(value: Any) -> int | None:
    """只接受可验证的非负整数，保留真实的零值。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isascii() and raw.isdecimal():
            return int(raw)
    return None


def roster_metric(item: Mapping[str, Any]) -> tuple[int, int]:
    """练度总览唯一排序键：先按战力、再按等级降序，未知值按零处理。"""
    return (
        roster_number(item.get("combat")) or 0,
        roster_number(item.get("lv")) or 0,
    )


def order_roster_entries(characters: Any) -> list[Mapping[str, Any]]:
    """按排序键稳定降序返回条目；非映射项按空映射参与排序但不丢失位置。"""
    indexed = [
        (index, item if isinstance(item, Mapping) else {})
        for index, item in enumerate(characters or ())
    ]
    indexed.sort(key=lambda pair: roster_metric(pair[1]), reverse=True)
    return [item for _, item in indexed]


def stable_name_code(item: Mapping[str, Any]) -> str:
    """提取稳定身份 name_code；缺失或非法时返回空串，绝不按昵称关联。"""
    raw = item.get("name_code")
    if raw is None or isinstance(raw, bool):
        return ""
    return str(raw).strip()


def select_top_codes(characters: Any, limit: int = 3) -> list[str]:
    """先截取正式排序的前 limit 行，再过滤无效标识并去重（绝不向后补位）。

    详情抓取必须与页面展示的 top-N 行完全对应：某一行缺少稳定 name_code 时
    只表示该行无法关联，不能改用第 N+1 名补位，否则会产生无用详情请求。
    """
    codes: list[str] = []
    seen: set[str] = set()
    for item in order_roster_entries(characters)[: max(limit, 0)]:
        code = stable_name_code(item)
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes
