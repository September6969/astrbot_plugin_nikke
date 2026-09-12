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
    verified_source: str | None = None
    source_sha256: str | None = None


class CurrencyRegistry:
    """把 basic_info.currencies 转成不携带账号上下文的显示模型。"""

    _NIKKE_DB_COMMIT = "a2358b72bd1335c30737e46482a99947f3788bc7"
    _NIKKE_DB_SOURCE = (
        "https://github.com/Nikke-db/Nikke-db.github.io/blob/"
        f"{_NIKKE_DB_COMMIT}/images"
    )
    DEFINITIONS = {
        99: CurrencyDefinition(99, "珠宝", verified_source=None, source_sha256=None),
        1000: CurrencyDefinition(
            1000,
            "信用点",
            "credit",
            f"{_NIKKE_DB_SOURCE}/credit.png",
            "85f242e863eab4a9f30391907843073c889f0fb7607fb530d12e7a15cc6a7035",
        ),
        2000: CurrencyDefinition(
            2000,
            "战斗数据辑",
            "battledata",
            f"{_NIKKE_DB_SOURCE}/battledata.png",
            "dbea9945e42a5e6904e1d26cb8c136fb5947269b72b9fb14344565134f390486",
        ),
        3000: CurrencyDefinition(
            3000,
            "芯尘",
            "coredust",
            f"{_NIKKE_DB_SOURCE}/coredust.png",
            "e0cf067c4b6443a736b8169568e858c99ee75340553974801ed35e6a8b931034",
        ),
        5100: CurrencyDefinition(5100, "高级招募券", verified_source=None, source_sha256=None),
        5200: CurrencyDefinition(5200, "普通招募券", verified_source=None, source_sha256=None),
        11000: CurrencyDefinition(11000, "躯体标签", verified_source=None, source_sha256=None),
        12000: CurrencyDefinition(12000, "联盟芯片", verified_source=None, source_sha256=None),
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

    @classmethod
    def icon_coverage(cls) -> dict[str, Any]:
        """报告有完整来源证据的图标数量；未知图标不回退到相邻资源。"""
        verified = [
            definition for definition in cls.DEFINITIONS.values()
            if (
                definition.icon_key
                and definition.verified_source
                and isinstance(definition.source_sha256, str)
                and re.fullmatch(r"[0-9a-fA-F]{64}", definition.source_sha256)
            )
        ]
        return {
            "total": len(cls.DEFINITIONS),
            "verified": len(verified),
            "unverified": len(cls.DEFINITIONS) - len(verified),
            "unverified_types": [
                definition.type
                for definition in cls.DEFINITIONS.values()
                if definition not in verified
            ],
        }

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
