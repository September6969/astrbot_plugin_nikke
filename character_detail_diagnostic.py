# SPDX-License-Identifier: GPL-3.0-or-later
"""生成脱敏的 CharacterDetails 数值字段结构诊断。

诊断只保留字段名、JSON 类型、非空状态和数值形状，不输出账号数值或私密上下文。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any


_NUMERIC_TEXT = re.compile(r"^[+-]?(\d+)(?:\.(\d+))?$")
_SENSITIVE_NAME = re.compile(r"(?:cookie|token|authorization|openid|email|password|secret)", re.IGNORECASE)


def _numeric_shape(value: Any) -> dict[str, Any] | None:
    """返回不含原始值的数值形状。"""
    if isinstance(value, bool) or value is None:
        return None

    if isinstance(value, int):
        digits = str(abs(value))
        return {
            "type": "int",
            "shape": "integer",
            "digit_count": len(digits),
            "fraction_digits": 0,
            "sign": "zero" if value == 0 else ("negative" if value < 0 else "positive"),
        }

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        text = format(value, ".15g")
        match = _NUMERIC_TEXT.fullmatch(text)
        if not match:
            return None
        integer_part, fraction_part = match.groups()
        sign = "zero" if value == 0 else ("negative" if value < 0 else "positive")
        return {
            "type": "float",
            "shape": "decimal" if fraction_part else "integer",
            "digit_count": len(integer_part.lstrip("0") or "0"),
            "fraction_digits": len(fraction_part or ""),
            "sign": sign,
        }

    if isinstance(value, str):
        match = _NUMERIC_TEXT.fullmatch(value.strip())
        if not match:
            return None
        integer_part, fraction_part = match.groups()
        unsigned = value.strip().lstrip("+-")
        sign = "zero" if not any(char != "0" for char in unsigned.replace(".", "")) else (
            "negative" if value.strip().startswith("-") else "positive"
        )
        return {
            "type": "str",
            "shape": "decimal" if fraction_part else "integer",
            "digit_count": len(integer_part.lstrip("0") or "0"),
            "fraction_digits": len(fraction_part or ""),
            "sign": sign,
        }

    return None


def summarize_character_details(detail: Mapping[str, Any]) -> dict[str, Any]:
    """只提取可用于字段合同核验的脱敏数值键元数据。"""
    if not isinstance(detail, Mapping):
        return {"schema_version": 1, "detail_numeric_keys": {}}

    numeric_keys: dict[str, dict[str, Any]] = {}
    for key, value in detail.items():
        field_name = str(key)
        if _SENSITIVE_NAME.search(field_name):
            continue
        shape = _numeric_shape(value)
        if shape is None:
            continue
        shape["non_empty"] = value is not None and value != ""
        numeric_keys[field_name] = shape

    return {
        "schema_version": 1,
        "detail_numeric_keys": dict(sorted(numeric_keys.items())),
    }

