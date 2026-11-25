# SPDX-License-Identifier: GPL-3.0-or-later
"""同步器公开成本表的解析与幂等写入。

数据来自 NikkeHub 公开同步器页面实际加载的前端 JS 表；只固化逐级
`credit / battleData / coreDust` 数值与来源，不复制页面文案。
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

_RANGE = re.compile(
    r"\{from:([^,]+),to:([^,]+),credit:([^,]+),battleData:([^,]+),coreDust:([^}]+)\}"
)
SYNC_SOURCE_URL = "https://nikkehub.com/zh-tw/tools/sync-level"


def _number(value: str) -> int:
    text = value.strip()
    if text.lower().startswith("0x"):
        return int(text, 16)
    if "e" in text.lower():
        return int(float(text))
    return int(text, 0)


def parse_sync_ranges(javascript: str) -> list[dict[str, int]]:
    """从公开前端 JS 中解析按等级区间的逐级成本。"""
    if not isinstance(javascript, str):
        raise ValueError("同步器数据必须是文本")
    start = javascript.find("let n=[{from:")
    if start < 0:
        raise ValueError("未找到公开同步器成本数组")
    end = javascript.find("];e.s([", start)
    if end < 0:
        raise ValueError("公开同步器成本数组不完整")
    rows = []
    for match in _RANGE.finditer(javascript[start:end + 2]):
        from_level, to_level, credit, battle, dust = (_number(item) for item in match.groups())
        if not (1 <= from_level <= to_level <= 1000):
            raise ValueError("公开同步器等级区间越界")
        if min(credit, battle, dust) < 0:
            raise ValueError("公开同步器成本为负")
        rows.append({
            "from": from_level, "to": to_level,
            "credits": credit, "battle_data": battle, "core_dust": dust,
        })
    if not rows:
        raise ValueError("公开同步器成本数组为空")
    for previous, current in zip(rows, rows[1:]):
        if current["from"] != previous["to"] + 1:
            raise ValueError("公开同步器成本区间不连续")
    return rows


def build_sync_payload(rows: list[dict[str, int]], *, checked_at: str) -> dict[str, Any]:
    levels = []
    for row in rows:
        for level in range(row["from"], row["to"] + 1):
            levels.append({
                "level": level,
                "core_dust": row["core_dust"],
                "credits": row["credits"],
                "battle_data": row["battle_data"],
            })
    if not levels:
        raise ValueError("同步器成本为空")
    return {
        "schema_version": 1,
        "label": "NikkeHub 同步器等级逐级成本（公开前端）",
        "source_url": SYNC_SOURCE_URL,
        "checked_at": checked_at,
        "scope": (
            f"GLOBAL; levels {levels[0]['level']}-{levels[-1]['level']}; "
            "per-level cost to reach that level from previous level; "
            "credits/battle data/core dust"
        ),
        "levels": levels,
    }


def write_sync_payload(path: str | Path, payload: Mapping[str, Any]) -> bool:
    """原子写；内容未变时返回 False（幂等）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return False
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
        handle.flush()
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


__all__ = [
    "SYNC_SOURCE_URL",
    "build_sync_payload",
    "parse_sync_ranges",
    "write_sync_payload",
]
