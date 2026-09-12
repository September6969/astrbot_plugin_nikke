# SPDX-License-Identifier: GPL-3.0-or-later
"""遗失物类别的证据驱动分组 registry。"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from .profile_models import MemorialCountData


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


__all__ = ["MemorialCategoryRegistry"]
