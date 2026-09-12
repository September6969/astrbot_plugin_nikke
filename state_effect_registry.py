# SPDX-License-Identifier: GPL-3.0-or-later
"""证据驱动的 NIKKE StateEffect / OL 元数据 registry。"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Iterable


class StateEffectRegistryError(ValueError):
    """StateEffect registry 不符合来源或字段合同。"""


_ID = re.compile(r"^\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VALUE_KINDS = {"percent", "flat", "seconds", "count", "multiplier", "unknown"}


@dataclass(frozen=True, slots=True)
class StateEffectMetadata:
    option_id: str
    state_effect_id: str | None
    group_id: str | None
    function_type: str
    label: str
    value_kind: str
    value_divisor: float | None
    locale: str
    source_url: str
    source_sha256: str
    checked_at: str
    value_source_url: str | None = None
    value_source_sha256: str | None = None

    def format_value(self, raw_value: Any) -> tuple[float, str]:
        """仅按来源明确的 divisor 转换，缺证据时返回安全的 unknown。"""
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.0, "unknown"
        if not math.isfinite(value) or self.value_kind == "unknown" or self.value_divisor is None:
            return abs(value) if math.isfinite(value) else 0.0, "unknown"
        converted = abs(value) / self.value_divisor
        if not math.isfinite(converted):
            return 0.0, "unknown"
        return converted, self.value_kind


class StateEffectRegistry:
    """严格加载有来源 hash 的 StateEffect 元数据；空表是安全的待核验状态。"""

    def __init__(self, entries: Iterable[StateEffectMetadata] = (), errors: Iterable[str] = ()):
        self.errors = list(errors)
        self._entries = tuple(entries)
        self._by_key = {
            (item.option_id, item.function_type.casefold(), item.locale): item
            for item in self._entries
        }
        self._by_option = {}
        for item in self._entries:
            self._by_option.setdefault((item.option_id, item.locale), []).append(item)

    @classmethod
    def empty(cls) -> "StateEffectRegistry":
        return cls()

    @classmethod
    def from_file(cls, path: str | Path) -> "StateEffectRegistry":
        target = Path(path)
        try:
            data = json.loads(
                target.read_text(encoding="utf-8"),
                object_pairs_hook=cls._reject_duplicate_keys,
            )
        except FileNotFoundError:
            return cls()
        except (OSError, UnicodeError, json.JSONDecodeError, StateEffectRegistryError) as exc:
            return cls(errors=[str(exc)])
        try:
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise StateEffectRegistryError("schema_version 无效")
            entries = data.get("entries", [])
            if not isinstance(entries, list):
                raise StateEffectRegistryError("entries 必须是数组")
            parsed = cls._parse_entries(entries)
        except StateEffectRegistryError as exc:
            return cls(errors=[str(exc)])
        return cls(parsed)

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]]) -> "StateEffectRegistry":
        try:
            return cls(cls._parse_entries(list(records)))
        except StateEffectRegistryError as exc:
            return cls(errors=[str(exc)])

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def entries(self) -> tuple[StateEffectMetadata, ...]:
        return self._entries

    def resolve(
        self,
        option_id: Any,
        function_type: Any,
        *,
        locale: str = "zh-CN",
    ) -> StateEffectMetadata | None:
        """只按 option_id、function_type 和 locale 精确命中。"""
        option_key = str(option_id or "").strip()
        function_key = str(function_type or "").strip().casefold()
        return self._by_key.get((option_key, function_key, locale))

    def resolve_option(self, option_id: Any, *, locale: str = "zh-CN") -> StateEffectMetadata | None:
        """返回唯一的现场观察记录，仅用于报告 function type 冲突。"""
        candidates = self._by_option.get((str(option_id or "").strip(), locale), [])
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise StateEffectRegistryError(f"JSON 对象包含重复键: {key!r}")
            result[key] = value
        return result

    @classmethod
    def _parse_entries(cls, records: list[Any]) -> list[StateEffectMetadata]:
        result: list[StateEffectMetadata] = []
        seen: set[tuple[str, str, str]] = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise StateEffectRegistryError(f"entry[{index}] 必须是对象")
            option_id = cls._required_id(record.get("option_id"), f"entry[{index}].option_id")
            state_effect_id = cls._optional_id(record.get("state_effect_id"), f"entry[{index}].state_effect_id")
            group_id = cls._optional_id(record.get("group_id"), f"entry[{index}].group_id")
            function_type = cls._required_text(record.get("function_type"), f"entry[{index}].function_type")
            label = cls._required_text(record.get("label"), f"entry[{index}].label")
            value_kind = cls._required_text(record.get("value_kind"), f"entry[{index}].value_kind")
            if value_kind not in _VALUE_KINDS:
                raise StateEffectRegistryError(f"entry[{index}].value_kind 无效")
            divisor = record.get("value_divisor")
            if divisor is not None:
                try:
                    divisor = float(divisor)
                except (TypeError, ValueError):
                    raise StateEffectRegistryError(f"entry[{index}].value_divisor 无效")
                if not math.isfinite(divisor) or divisor <= 0:
                    raise StateEffectRegistryError(f"entry[{index}].value_divisor 无效")
            locale = cls._required_text(record.get("locale"), f"entry[{index}].locale")
            source_url = cls._required_text(record.get("source_url"), f"entry[{index}].source_url")
            parsed_url = urlparse(source_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
                raise StateEffectRegistryError(f"entry[{index}].source_url 必须是无凭据 HTTPS")
            source_sha256 = cls._required_text(record.get("source_sha256"), f"entry[{index}].source_sha256").lower()
            if not _SHA256.fullmatch(source_sha256):
                raise StateEffectRegistryError(f"entry[{index}].source_sha256 无效")
            checked_at = cls._required_text(record.get("checked_at"), f"entry[{index}].checked_at")
            value_source_url = record.get("value_source_url")
            value_source_sha256 = record.get("value_source_sha256")
            if (value_source_url is None) != (value_source_sha256 is None):
                raise StateEffectRegistryError(
                    f"entry[{index}] 的 value_source_url/value_source_sha256 必须成对出现"
                )
            if value_source_url is not None:
                value_source_url = cls._required_text(
                    value_source_url, f"entry[{index}].value_source_url"
                )
                parsed_value_url = urlparse(value_source_url)
                if (
                    parsed_value_url.scheme != "https"
                    or not parsed_value_url.netloc
                    or parsed_value_url.username
                    or parsed_value_url.password
                ):
                    raise StateEffectRegistryError(
                        f"entry[{index}].value_source_url 必须是无凭据 HTTPS"
                    )
                value_source_sha256 = cls._required_text(
                    value_source_sha256, f"entry[{index}].value_source_sha256"
                ).lower()
                if not _SHA256.fullmatch(value_source_sha256):
                    raise StateEffectRegistryError(
                        f"entry[{index}].value_source_sha256 无效"
                    )
            key = (option_id, function_type.casefold(), locale)
            if key in seen:
                raise StateEffectRegistryError(f"重复 registry key: {key!r}")
            seen.add(key)
            result.append(StateEffectMetadata(
                option_id=option_id,
                state_effect_id=state_effect_id,
                group_id=group_id,
                function_type=function_type,
                label=label,
                value_kind=value_kind,
                value_divisor=divisor,
                locale=locale,
                source_url=source_url,
                source_sha256=source_sha256,
                checked_at=checked_at,
                value_source_url=value_source_url,
                value_source_sha256=value_source_sha256,
            ))
        return result

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise StateEffectRegistryError(f"{field} 缺失")
        return value.strip()

    @staticmethod
    def _required_id(value: Any, field: str) -> str:
        text = StateEffectRegistry._required_text(value, field)
        if not _ID.fullmatch(text):
            raise StateEffectRegistryError(f"{field} 必须是十进制 ID")
        return text

    @staticmethod
    def _optional_id(value: Any, field: str) -> str | None:
        if value in (None, ""):
            return None
        return StateEffectRegistry._required_id(value, field)
