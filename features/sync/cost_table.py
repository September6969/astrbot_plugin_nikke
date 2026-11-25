# SPDX-License-Identifier: GPL-3.0-or-later
"""同步器等级成本表（12）。

仓库没有可再分发的可靠等级成本表，因此本模块只提供**严格校验的导入格式**：
运营者或用户必须显式提供带来源、核验日期和连续等级覆盖的成本表，否则计算入口
会返回“缺少可靠成本表”，绝不内置或猜测每一级的消耗。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

RESOURCES: tuple[str, ...] = ("core_dust", "credits", "battle_data")
RESOURCE_LABELS = {"core_dust": "芯尘", "credits": "信用点", "battle_data": "战斗数据"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MIN_LEVEL = 1
_MAX_LEVEL = 2000


class SyncCostTableError(ValueError):
    """成本表不符合来源或覆盖合同。"""


@dataclass(frozen=True, slots=True)
class SyncCostRow:
    """升到 level 时需要的三类资源总量。"""

    level: int
    core_dust: int
    credits: int
    battle_data: int


@dataclass(frozen=True, slots=True)
class SyncCostTable:
    """带来源证据的同步器等级成本表。"""

    rows: tuple[SyncCostRow, ...]
    source_url: str
    checked_at: str
    scope: str = "GLOBAL"
    label: str = "同步器等级成本表"

    @property
    def levels(self) -> tuple[int, ...]:
        return tuple(row.level for row in self.rows)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        source_url: str,
        checked_at: str,
        scope: str = "GLOBAL",
        label: str = "同步器等级成本表",
    ) -> "SyncCostTable":
        """从内存记录构造；测试与离线导入共用同一套校验。"""
        source = _require_source(source_url)
        checked = _require_text(checked_at, "checked_at")
        rows: list[SyncCostRow] = []
        seen: set[int] = set()
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise SyncCostTableError(f"levels[{index}] 必须是对象")
            level = _require_level(record.get("level"), f"levels[{index}].level")
            if level in seen:
                raise SyncCostTableError(f"等级重复：{level}")
            seen.add(level)
            rows.append(
                SyncCostRow(
                    level=level,
                    core_dust=_require_amount(record.get("core_dust"), f"levels[{index}].core_dust"),
                    credits=_require_amount(record.get("credits"), f"levels[{index}].credits"),
                    battle_data=_require_amount(record.get("battle_data"), f"levels[{index}].battle_data"),
                )
            )
        if not rows:
            raise SyncCostTableError("成本表为空")
        rows.sort(key=lambda row: row.level)
        # 连续覆盖是可靠累计成本的前提，缺口必须显式失败而不是按比例脑补。
        for previous, current in zip(rows, rows[1:]):
            if current.level != previous.level + 1:
                raise SyncCostTableError(
                    f"等级覆盖不连续：{previous.level} 之后缺少 {previous.level + 1}"
                )
        return cls(tuple(rows), source, checked, scope, label)

    @classmethod
    def from_file(cls, path: str | Path) -> "SyncCostTable":
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SyncCostTableError(f"成本表无法读取：{target.name}") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SyncCostTableError("成本表不是合法 UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise SyncCostTableError("成本表根节点必须是对象")
        if payload.get("schema_version") != 1:
            raise SyncCostTableError("成本表 schema_version 必须为 1")
        levels = payload.get("levels")
        if not isinstance(levels, list):
            raise SyncCostTableError("成本表 levels 必须是数组")
        return cls.from_records(
            levels,
            source_url=payload.get("source_url"),
            checked_at=payload.get("checked_at"),
            scope=str(payload.get("scope", "GLOBAL")),
            label=str(payload.get("label", "同步器等级成本表")),
        )

    def cost_between(self, current: int, target: int) -> dict[str, int]:
        """返回 current→target 的三类资源累计消耗；覆盖不足时显式失败。"""
        current = _require_level(current, "current")
        target = _require_level(target, "target")
        if target <= current:
            raise SyncCostTableError("目标等级必须高于当前等级")
        rows = {row.level: row for row in self.rows}
        missing = [level for level in range(current + 1, target + 1) if level not in rows]
        if missing:
            covered = (
                f"（当前成本表仅覆盖 Lv.{self.rows[0].level - 1}→{self.rows[-1].level}）"
                if self.rows
                else ""
            )
            raise SyncCostTableError(
                "成本表未覆盖等级：" + "、".join(str(level) for level in missing[:5])
                + (" 等" if len(missing) > 5 else "")
                + covered
                + "；可改用手工成本模式：/妮姬 同步器 计算 手工 ..."
            )
        return {
            resource: sum(getattr(rows[level], resource) for level in range(current + 1, target + 1))
            for resource in RESOURCES
        }

    def gainable_levels(
        self, current: int, inventory: Mapping[str, int]
    ) -> tuple[int, int, dict[str, int]]:
        """计算以当前库存可立即连续升到的等级与剩余库存。"""
        current = _require_level(current, "current")
        rows = {row.level: row for row in self.rows}
        remaining = {
            resource: max(0, int(inventory.get(resource, 0)))
            for resource in RESOURCES
        }
        gained = 0
        level = current
        while (nxt := level + 1) in rows:
            row = rows[nxt]
            if any(remaining[res] < getattr(row, res) for res in RESOURCES):
                break
            for res in RESOURCES:
                remaining[res] -= getattr(row, res)
            level = nxt
            gained += 1
        return gained, level, remaining


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncCostTableError(f"{field} 缺失")
    return value.strip()


def _require_source(value: Any) -> str:
    text = _require_text(value, "source_url")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SyncCostTableError("source_url 必须是无凭据 HTTPS 地址")
    return text


def _require_level(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SyncCostTableError(f"{field} 必须是整数")
    if not _MIN_LEVEL <= value <= _MAX_LEVEL:
        raise SyncCostTableError(f"{field} 超出 {_MIN_LEVEL}–{_MAX_LEVEL}")
    return value


def _require_amount(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SyncCostTableError(f"{field} 必须是非负整数")
    return value


__all__ = [
    "RESOURCE_LABELS",
    "RESOURCES",
    "SyncCostRow",
    "SyncCostTable",
    "SyncCostTableError",
]
