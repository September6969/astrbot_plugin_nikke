# SPDX-License-Identifier: GPL-3.0-or-later
"""前哨研究等级的纯映射规则。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def map_research_levels(researches: Any) -> dict[str, int | None]:
    """把 Profile Outpost 的 tid/lv 列表映射为 Exia 计算合同。"""
    result: dict[str, int | None] = {
        "general": None,
        "attacker": None,
        "defender": None,
        "supporter": None,
        "elysion": None,
        "missilis": None,
        "tetra": None,
        "pilgrim": None,
        "abnormal": None,
    }
    key_by_id = {
        1001: "general",
        1101: "attacker",
        1102: "defender",
        1103: "supporter",
        1201: "elysion",
        1202: "missilis",
        1203: "tetra",
        1204: "pilgrim",
        1205: "abnormal",
    }
    if not isinstance(researches, list):
        return result
    for row in researches:
        if not isinstance(row, Mapping):
            continue
        raw_tid, raw_level = row.get("tid"), row.get("lv")
        # 拒绝布尔值、小数和宽松转换，避免异常研究等级进入真实属性计算。
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, str))
            or not str(value).isascii()
            or not str(value).isdigit()
            for value in (raw_tid, raw_level)
        ):
            continue
        tid, level = int(raw_tid), int(raw_level)
        if tid in key_by_id and level >= 0:
            result[key_by_id[tid]] = level
    return result
