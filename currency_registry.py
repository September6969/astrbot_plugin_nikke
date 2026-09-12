# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile 资源类型 registry；只登记已确认的静态类型。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .profile_models import CurrencyItem
from .raid_participants import format_compact_number


@dataclass(frozen=True, slots=True)
class CurrencyDefinition:
    type: int
    display_name: str
    icon_key: str | None = None


class CurrencyRegistry:
    """把 basic_info.currencies 转成不携带账号上下文的显示模型。"""

    DEFINITIONS = {
        99: CurrencyDefinition(99, "珠宝"),
        1000: CurrencyDefinition(1000, "信用点"),
        2000: CurrencyDefinition(2000, "战斗数据辑"),
        3000: CurrencyDefinition(3000, "芯尘"),
        5100: CurrencyDefinition(5100, "高级招募券"),
        5200: CurrencyDefinition(5200, "普通招募券"),
        11000: CurrencyDefinition(11000, "躯体标签"),
        12000: CurrencyDefinition(12000, "联盟芯片"),
    }
    _INTEGER = re.compile(r"^[0-9]+$", re.ASCII)

    def __init__(self) -> None:
        self.errors: list[str] = []

    @classmethod
    def _integer(cls, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if type(value) is int:
            return value if value >= 0 else None
        if isinstance(value, str) and cls._INTEGER.fullmatch(value.strip()):
            try:
                parsed = int(value.strip())
            except ValueError:
                return None
            return parsed if parsed >= 0 else None
        return None

    @classmethod
    def resolve(cls, type_value: Any) -> CurrencyDefinition | None:
        parsed = cls._integer(type_value)
        return cls.DEFINITIONS.get(parsed) if parsed is not None else None

    def parse_item(self, value: Any) -> CurrencyItem | None:
        if not isinstance(value, dict):
            self.errors.append("资源条目不是对象")
            return None
        type_value = self._integer(value.get("type"))
        amount = self._integer(value.get("value"))
        if type_value is None or amount is None:
            self.errors.append("资源条目的 type/value 不是非负整数")
            return None
        definition = self.DEFINITIONS.get(type_value)
        if definition is None:
            # 未知类型仍保留真实整数，但不猜名称或图标。
            return CurrencyItem(type_value, amount, "未知资源", None, format_compact_number(amount))
        return CurrencyItem(
            type=definition.type,
            value=amount,
            display_name=definition.display_name,
            icon_key=definition.icon_key,
            compact_value=format_compact_number(amount),
        )

    def parse(self, values: Any) -> tuple[list[CurrencyItem] | None, bool]:
        if values is None:
            return None, False
        if not isinstance(values, list):
            self.errors.append("currencies 不是数组")
            return None, True
        result: list[CurrencyItem] = []
        partial = False
        for item in values:
            parsed = self.parse_item(item)
            if parsed is None:
                partial = True
                continue
            result.append(parsed)
        return result, partial


__all__ = ["CurrencyDefinition", "CurrencyItem", "CurrencyRegistry"]
