# SPDX-License-Identifier: GPL-3.0-or-later
"""角色目录的本地化字段与统一查询解析。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def _text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    return str(value).strip()


def _aliases(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in (_text(entry) for entry in value) if item]


class CharacterDirectoryResolver:
    """统一处理 name_code、官方名称和受控查询别名。"""

    def __init__(self, alias_path: str | Path | None = None):
        self._aliases_by_code: dict[str, list[str]] = {}
        self._aliases_by_zh_tw: dict[str, list[str]] = {}
        if alias_path is not None:
            self._load_aliases(Path(alias_path))

    def _load_aliases(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = payload.get("entries", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            return
        alias_to_target: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            values = _aliases(entry.get("aliases"))
            if not values:
                continue
            code = _text(entry.get("name_code"))
            zh_tw = _text(entry.get("name_zh_tw"))
            target_key = (code or zh_tw).casefold()
            if not target_key:
                continue
            for val in values:
                norm_val = val.casefold()
                existing = alias_to_target.get(norm_val)
                if existing is not None and existing != target_key:
                    raise ValueError(f"别名冲突: 别名 {val!r} 同时映射到多个不同角色 ({existing!r} 与 {target_key!r})")
                alias_to_target[norm_val] = target_key
            if code:
                self._aliases_by_code[code.casefold()] = values
            if zh_tw:
                self._aliases_by_zh_tw[zh_tw.casefold()] = values

    def enrich(self, item: dict[str, Any]) -> dict[str, Any]:
        """补齐明确的本地化字段，同时保留旧 name_cn 兼容字段。"""
        result = dict(item)
        zh_tw = _text(result.get("name_zh_tw")) or _text(result.get("name_cn"))
        zh_cn = _text(result.get("name_zh_cn"))
        aliases = _aliases(result.get("aliases"))
        aliases.extend(_aliases(result.get("name_zh_cn_aliases")))
        aliases.extend(_aliases([result.get("name_zh_cn_alias")]))
        code_key = _text(result.get("name_code")).casefold()
        zh_tw_key = zh_tw.casefold()
        aliases.extend(self._aliases_by_code.get(code_key, []))
        aliases.extend(self._aliases_by_zh_tw.get(zh_tw_key, []))
        aliases = list(dict.fromkeys(alias for alias in aliases if alias and alias != zh_cn))
        result["name_zh_tw"] = zh_tw
        result["name_zh_cn"] = zh_cn
        result["name_zh_cn_alias"] = aliases[0] if aliases else ""
        result["aliases"] = aliases
        # name_cn 是历史公共字段，继续保留为官方繁中值。
        result["name_cn"] = zh_tw or _text(result.get("name_cn"))
        return result

    @staticmethod
    def display_name(item: dict[str, Any]) -> str:
        item = item or {}
        return (
            _text(item.get("name_zh_cn"))
            or _text(item.get("name_zh_cn_alias"))
            or _text(item.get("name_zh_tw"))
            or _text(item.get("name_cn"))
            or _text(item.get("name_en"))
            or _text(item.get("name_code"))
            or "未知妮姬"
        )

    @staticmethod
    def _field_values(item: dict[str, Any]) -> list[str]:
        item = item or {}
        return [
            _text(item.get("name_code")),
            _text(item.get("name_zh_tw")) or _text(item.get("name_cn")),
            _text(item.get("name_zh_cn")),
            _text(item.get("name_zh_cn_alias")),
            _text(item.get("name_en")),
        ]

    def find(self, directory: Iterable[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        term = _text(query).casefold()
        if not term:
            return []
        items = [self.enrich(item) for item in directory if isinstance(item, dict)]
        # 精确匹配优先级固定：code → 繁中 → 官方简中/别名 → 英文 → 其他 alias。
        fields = [(item, self._field_values(item)) for item in items]
        for index in range(5):
            exact = [item for item, values in fields if values[index] and term == values[index].casefold()]
            if exact:
                return exact
        exact = [
            item for item, values in fields
            if term in {value.casefold() for value in _aliases(item.get("aliases"))}
        ]
        if exact:
            return exact
        return [
            item
            for item in items
            if any(term in value.casefold() for value in self._field_values(item)[1:] if value)
            or any(term in value.casefold() for value in _aliases(item.get("aliases")))
        ]
