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


def parse_user_aliases(raw: Any) -> list[tuple[str, list[str]]]:
    """解析用户自定义别名配置，支持 dict, list, JSON 字符串或多行 '角色名=别名1,别名2'。"""
    results: list[tuple[str, list[str]]] = []
    if not raw:
        return results

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return results
        if text.startswith(("{", "[")):
            try:
                parsed = json.loads(text)
                return parse_user_aliases(parsed)
            except (ValueError, TypeError):
                pass
        import re
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "//")):
                continue
            if "=" in line:
                target, _, alias_part = line.partition("=")
            elif ":" in line and not line.startswith("http"):
                target, _, alias_part = line.partition(":")
            else:
                continue
            target = target.strip()
            if not target:
                continue
            aliases = [a.strip() for a in re.split(r"[,，、\|\t]+", alias_part) if a.strip()]
            if aliases:
                results.append((target, aliases))
        return results

    if isinstance(raw, dict):
        import re
        for target, val in raw.items():
            t_str = _text(target)
            if not t_str:
                continue
            if isinstance(val, (list, tuple)):
                aliases = [a.strip() for a in (_text(x) for x in val) if a.strip()]
            elif isinstance(val, str):
                aliases = [a.strip() for a in re.split(r"[,，、\|\t]+", val) if a.strip()]
            else:
                continue
            if aliases:
                results.append((t_str, aliases))
        return results

    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                target = _text(item.get("name") or item.get("target") or item.get("name_code") or item.get("name_zh_tw"))
                val = item.get("aliases")
                if target and isinstance(val, (list, tuple)):
                    aliases = [a.strip() for a in (_text(x) for x in val) if a.strip()]
                    if aliases:
                        results.append((target, aliases))
            elif isinstance(item, str):
                results.extend(parse_user_aliases(item))
        return results

    return results


class CharacterDirectoryResolver:
    """统一处理 name_code、官方名称和受控查询别名。"""

    def __init__(
        self,
        alias_path: str | Path | None = None,
        user_aliases: Any = None,
        catalog_path: str | Path | None = None,
    ):
        self._aliases_by_code: dict[str, list[str]] = {}
        self._aliases_by_zh_tw: dict[str, list[str]] = {}
        self._user_aliases: dict[str, list[str]] = {}
        self._canonical_by_identifier: dict[str, str] = {}
        self._built_in_alias_to_canonical: dict[str, str] = {}
        self._user_alias_to_canonical: dict[str, str] = {}

        if catalog_path is not None:
            self._load_catalog(Path(catalog_path))
        elif alias_path is not None and (Path(alias_path).parent / "character_catalog.json").is_file():
            self._load_catalog(Path(alias_path).parent / "character_catalog.json")
        else:
            default_cat = Path(__file__).resolve().parent / "assets" / "character_catalog.json"
            if default_cat.is_file():
                self._load_catalog(default_cat)

        if alias_path is not None:
            self._load_aliases(Path(alias_path))
        else:
            default_alias = Path(__file__).resolve().parent / "assets" / "character_aliases.json"
            if default_alias.is_file():
                self._load_aliases(default_alias)
        if user_aliases:
            self.load_user_aliases(user_aliases)

    def _load_catalog(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        characters = payload.get("characters", []) if isinstance(payload, dict) else []
        for char in characters:
            if not isinstance(char, dict):
                continue
            key = str(char.get("character_key", "")).strip().lower()
            if not key:
                continue
            self._canonical_by_identifier[key] = key
            spine = str(char.get("spine_asset_id", "")).strip().lower()
            if spine:
                self._canonical_by_identifier[spine] = key
            rid = str(char.get("resource_id", "")).strip().lower()
            if rid:
                self._canonical_by_identifier[rid] = key
            code = str(char.get("name_code", "")).strip().lower()
            if code:
                self._canonical_by_identifier[code] = key
            zh_tw = str(char.get("name_zh_tw", "")).strip().lower()
            if zh_tw:
                self._canonical_by_identifier[zh_tw] = key
            name_en = str(char.get("name_en", "")).strip().lower()
            if name_en and name_en not in {"rei", "sakura"}:
                self._canonical_by_identifier[name_en] = key

    def resolve_canonical(self, target: str) -> str:
        """将名称、代码、Spine 资产号或别名解析为规范角色键。"""
        norm = str(target).strip().casefold()
        return self._canonical_by_identifier.get(norm, norm)

    def load_user_aliases(self, user_aliases: Any) -> None:
        """加载并合并用户自定义别名。支持 dict, list, JSON 字符串或多行 '角色名=别名1,别名2'。

        防冲突规则：
        1. 自定义别名不能覆盖已核验的内置标识（规范键、Spine号、官方名称、内置别名）；
        2. 两个不同角色的自定义配置不能共享相同别名；
        3. 同一角色的重复别名自动去重并保留。
        """
        parsed = parse_user_aliases(user_aliases)
        for target, aliases in parsed:
            canonical_target = self.resolve_canonical(target)
            target_key = target.strip().casefold()

            for alias in aliases:
                norm_alias = alias.strip().casefold()
                if not norm_alias:
                    continue

                # 1. 检查是否与其它角色的内置标识或内置别名冲突
                built_in_canonical = self._canonical_by_identifier.get(norm_alias)
                if built_in_canonical is not None and norm_alias not in self._user_alias_to_canonical:
                    if built_in_canonical != canonical_target:
                        raise ValueError(
                            f"别名冲突: 自定义别名 {alias!r} 与角色 {built_in_canonical!r} 的内置标识或别名冲突"
                        )

                # 2. 检查是否与其它角色的自定义别名冲突
                existing_user = self._user_alias_to_canonical.get(norm_alias)
                if existing_user is not None and existing_user != canonical_target:
                    raise ValueError(
                        f"别名冲突: 自定义别名 {alias!r} 同时映射到多个不同角色 ({existing_user!r} 与 {canonical_target!r})"
                    )

                self._user_alias_to_canonical[norm_alias] = canonical_target
                self._canonical_by_identifier[norm_alias] = canonical_target

                for key in {canonical_target, target_key}:
                    existing = self._user_aliases.setdefault(key, [])
                    if alias not in existing:
                        existing.append(alias)

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
            code_lower = code.casefold() if code else ""
            zh_tw_lower = zh_tw.casefold() if zh_tw else ""
            target_key = (code or zh_tw).casefold()
            if not target_key:
                continue

            canonical = (
                self._canonical_by_identifier.get(code_lower)
                or self._canonical_by_identifier.get(zh_tw_lower)
                or target_key
            )
            if code_lower:
                self._canonical_by_identifier.setdefault(code_lower, canonical)
            if zh_tw_lower:
                self._canonical_by_identifier.setdefault(zh_tw_lower, canonical)

            for val in values:
                norm_val = val.casefold()
                existing = alias_to_target.get(norm_val)
                if existing is not None and existing != target_key:
                    raise ValueError(f"别名冲突: 别名 {val!r} 同时映射到多个不同角色 ({existing!r} 与 {target_key!r})")
                alias_to_target[norm_val] = target_key
                self._built_in_alias_to_canonical[norm_val] = canonical
                self._canonical_by_identifier[norm_val] = canonical

            if code:
                self._aliases_by_code[code.casefold()] = values
            if zh_tw:
                self._aliases_by_zh_tw[zh_tw.casefold()] = values

    def enrich(self, item: dict[str, Any]) -> dict[str, Any]:
        """补齐明确的本地化字段，同时保留旧 name_cn 兼容字段。"""
        result = dict(item)
        zh_tw = _text(result.get("name_zh_tw")) or _text(result.get("name_cn"))
        zh_cn = _text(result.get("name_zh_cn"))
        name_en = _text(result.get("name_en"))
        code = _text(result.get("name_code"))
        aliases = _aliases(result.get("aliases"))
        aliases.extend(_aliases(result.get("name_zh_cn_aliases")))
        aliases.extend(_aliases([result.get("name_zh_cn_alias")]))
        code_key = code.casefold()
        zh_tw_key = zh_tw.casefold()
        zh_cn_key = zh_cn.casefold()
        en_key = name_en.casefold()

        aliases.extend(self._aliases_by_code.get(code_key, []))
        aliases.extend(self._aliases_by_zh_tw.get(zh_tw_key, []))

        keys_to_check = [code_key, zh_tw_key, zh_cn_key, en_key]
        for extra in ("character_key", "spine_asset_id", "resource_id"):
            val = _text(result.get(extra)).casefold()
            if val and val not in keys_to_check:
                keys_to_check.append(val)

        canonical_key = ""
        for k in keys_to_check:
            if k and k in self._canonical_by_identifier:
                canonical_key = self._canonical_by_identifier[k]
                break
        if canonical_key and canonical_key not in keys_to_check:
            keys_to_check.append(canonical_key)

        for key in keys_to_check:
            if key and key in self._user_aliases:
                aliases.extend(self._user_aliases[key])

        for existing_alias in list(aliases):
            a_key = existing_alias.casefold()
            if a_key in self._user_aliases:
                aliases.extend(self._user_aliases[a_key])

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
