# SPDX-License-Identifier: GPL-3.0-or-later
"""遗失物类别的证据驱动分组 registry。"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from ...profile.models import MemorialCountData


logger = logging.getLogger("nikke.profile.memorial")


class MemorialCategoryRegistry:
    """按类别 key 映射最终四个 UI 格位，不使用数组顺序。"""

    GROUP_NAMES = {
        "phone": "手机",
        "call_log": "通话记录",
        "data": "数据资料",
        "bgm": "BGM",
    }
    CATEGORY_TO_GROUP = {
        "handwriting": "phone",
        "calllog": "call_log",
        "data": "data",
        "oldtales": "data",
        "unbreakablesphere": "data",
    }
    ORDER = ("phone", "call_log", "data", "bgm")

    def __init__(self, diagnostics: Callable[[str], None] | None = None) -> None:
        self.diagnostics = diagnostics

    @classmethod
    def group_for(cls, category: object) -> str | None:
        if not isinstance(category, str) or not category.strip():
            return None
        return cls.CATEGORY_TO_GROUP.get(category.strip().casefold())

    def _unknown(self, category: object) -> None:
        text = str(category).strip() if isinstance(category, str) else "<invalid>"
        message = f"未知遗失物分类未归类: {text[:80]}"
        if self.diagnostics:
            self.diagnostics(message)
        else:
            logger.warning(message)

    def summarize(
        self,
        rows: Iterable[MemorialCountData] | None,
        *,
        jukebox_count: int | None,
    ) -> tuple[list[MemorialCountData] | None, bool]:
        if rows is None and jukebox_count is None:
            return None, False
        totals: dict[str, int] = {}
        seen: set[str] = set()
        partial = False
        if rows is not None:
            for row in rows:
                group = self.group_for(row.category)
                if group is None:
                    self._unknown(row.category)
                    partial = True
                    continue
                seen.add(group)
                if row.count is None:
                    partial = True
                    continue
                totals[group] = totals.get(group, 0) + row.count
        if jukebox_count is not None:
            totals["bgm"] = jukebox_count
            seen.add("bgm")
        if not seen:
            # 全部是未知/空分类时不画四个“0”，避免把未知误报成已确认的零值。
            return None, partial
        result = [
            MemorialCountData(
                category=group,
                count=totals.get(group) if group in seen else None,
                display_name=self.GROUP_NAMES[group],
                group=group,
            )
            for group in self.ORDER
        ]
        return result, partial

    @staticmethod
    def summarize_memorials(
        memorial_counts: list[object] | None,
        jukebox_count: str | int | None = None,
    ) -> dict[str, int]:
        """提供旧 Profile DTO 所需的四格兼容摘要。

        新路径使用 :meth:`summarize` 保留未知分类与部分状态；该方法仅用于
        旧 fixture 的兼容字段，不能替代结构化摘要或作为完整性证明。
        """
        totals = {"手机": 0, "通话记录": 0, "数据资料": 0, "BGM": 0}
        if isinstance(memorial_counts, list):
            for item in memorial_counts:
                if isinstance(item, dict):
                    category = item.get("category")
                    raw_count = item.get("count")
                else:
                    category = getattr(item, "category", None)
                    raw_count = getattr(item, "count", None)
                try:
                    count = int(raw_count) if raw_count is not None else 0
                except (TypeError, ValueError):
                    count = 0
                group = MemorialCategoryRegistry.group_for(category)
                if group == "phone":
                    totals["手机"] += count
                elif group == "call_log":
                    totals["通话记录"] += count
                elif group == "data":
                    totals["数据资料"] += count
        if jukebox_count is not None:
            try:
                totals["BGM"] = int(jukebox_count)
            except (TypeError, ValueError):
                totals["BGM"] = 0
        return totals


__all__ = ["MemorialCategoryRegistry"]
