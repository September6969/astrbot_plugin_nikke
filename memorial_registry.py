# SPDX-License-Identifier: GPL-3.0-or-later
"""遗失物分类注册表与官方映射。"""

from __future__ import annotations

from typing import Any


# 官方分类映射（经 BlaBlaLink 前端 index-BgvnrvAf.js 验证）
# HandWriting -> 手机
# CallLog -> 通话记录
# 其余（Data, OldTales, UnbreakableSphere 等） -> 数据资料
# Jukebox -> BGM
OFFICIAL_MEMORIAL_MAP = {
    "HandWriting": "手机",
    "CallLog": "通话记录",
    "Data": "数据资料",
    "OldTales": "遗落传说",
    "UnbreakableSphere": "奇迹之球",
}


class MemorialCategoryRegistry:
    @staticmethod
    def get_display_name(category: str | None) -> str:
        if not category:
            return "未知分类"
        return OFFICIAL_MEMORIAL_MAP.get(category, category)

    @staticmethod
    def summarize_memorials(
        memorial_counts: list[Any] | None,
        jukebox_count: str | int | None = None,
    ) -> dict[str, int]:
        """按 BlaBlaLink 前端规范汇总四格遗失物数据：

        - 手机: HandWriting
        - 通话记录: CallLog
        - 数据资料: 其余所有分类之和 (Data, OldTales, UnbreakableSphere 等)
        - BGM: jukebox_count
        """
        notes = 0
        callrecord = 0
        data_count = 0

        if isinstance(memorial_counts, list):
            for item in memorial_counts:
                cat = None
                cnt = 0
                if isinstance(item, dict):
                    cat = item.get("category")
                    try:
                        cnt = int(item.get("count", 0))
                    except (ValueError, TypeError):
                        cnt = 0
                elif hasattr(item, "category") and hasattr(item, "count"):
                    cat = getattr(item, "category")
                    c_val = getattr(item, "count")
                    try:
                        cnt = int(c_val) if c_val is not None else 0
                    except (ValueError, TypeError):
                        cnt = 0

                if cat == "HandWriting":
                    notes += cnt
                elif cat == "CallLog":
                    callrecord += cnt
                elif cat:
                    data_count += cnt

        bgm = 0
        if jukebox_count is not None:
            try:
                bgm = int(jukebox_count)
            except (ValueError, TypeError):
                bgm = 0

        return {
            "手机": notes,
            "通话记录": callrecord,
            "数据资料": data_count,
            "BGM": bgm,
        }
