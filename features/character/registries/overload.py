# SPDX-License-Identifier: GPL-3.0-or-later
"""来源可追溯的 OL 词条等级注册表。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class OverloadTierRegistryError(ValueError):
    """OL 注册表不符合来源或字段合同。"""


_ID = re.compile(r"^\d+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OverloadTierMetadata:
    state_effect_id: str
    group_id: str
    label: str
    level: int
    source_url: str
    source_sha256: str
    algorithm_source_url: str
    algorithm_source_sha256: str


class OverloadTierRegistry:
    """按公开 BlaBlaLink 等级算法精确解析 OL 1--15。"""

    def __init__(self, entries=(), errors=()):
        self.errors = list(errors)
        self._entries = tuple(entries)
        self._by_state_effect = {entry.state_effect_id: entry for entry in self._entries}

    @classmethod
    def from_file(cls, path: str | Path) -> "OverloadTierRegistry":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(cls._parse(data))
        except (OSError, UnicodeError, json.JSONDecodeError, OverloadTierRegistryError) as exc:
            return cls(errors=[str(exc)])

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def entries(self) -> tuple[OverloadTierMetadata, ...]:
        return self._entries

    @property
    def record_count(self) -> int:
        return len(self._entries) // 5

    @property
    def group_count(self) -> int:
        return len({entry.group_id for entry in self._entries})

    def resolve(self, state_effect_id: Any) -> OverloadTierMetadata | None:
        if isinstance(state_effect_id, bool):
            return None
        text = str(state_effect_id or "").strip()
        if not _ID.fullmatch(text):
            return None
        return self._by_state_effect.get(text)

    @classmethod
    def _parse(cls, data: Any) -> list[OverloadTierMetadata]:
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise OverloadTierRegistryError("schema_version 无效")
        if data.get("status") != "PUBLIC_ALGORITHM_VERIFIED":
            raise OverloadTierRegistryError("status 必须是 PUBLIC_ALGORITHM_VERIFIED")
        source_url = cls._source_url(data.get("source_url"), "source_url")
        source_sha256 = cls._sha(data.get("source_sha256"), "source_sha256")
        algorithm_url = cls._source_url(
            data.get("algorithm_source_url"), "algorithm_source_url"
        )
        algorithm_sha256 = cls._sha(
            data.get("algorithm_source_sha256"), "algorithm_source_sha256"
        )
        groups = data.get("groups")
        if not isinstance(groups, list) or not groups:
            raise OverloadTierRegistryError("groups 必须是非空数组")

        result: list[OverloadTierMetadata] = []
        seen_ids: set[str] = set()
        seen_records: set[tuple[str, int]] = set()
        for index, record in enumerate(groups):
            if not isinstance(record, dict):
                raise OverloadTierRegistryError(f"groups[{index}] 必须是对象")
            record_id = cls._positive_int(record.get("id"), f"groups[{index}].id")
            group_id = cls._id(record.get("state_effect_group_id"), f"groups[{index}].state_effect_group_id")
            local_key = record.get("description_localkey")
            if not isinstance(local_key, str) or not local_key.strip():
                raise OverloadTierRegistryError(f"groups[{index}].description_localkey 缺失")
            label = local_key.strip().strip("【】")
            state_ids = record.get("state_effect_id_list")
            if not isinstance(state_ids, list) or len(state_ids) != 5:
                raise OverloadTierRegistryError(f"groups[{index}].state_effect_id_list 必须有 5 项")
            if record_id % 10 not in (1, 2, 3):
                raise OverloadTierRegistryError(
                    f"groups[{index}].id 不能产生完整 1--15 等级: {record_id}"
                )
            for offset, raw_state_id in enumerate(state_ids):
                state_id = cls._id(raw_state_id, f"groups[{index}].state_effect_id_list[{offset}]")
                if state_id in seen_ids:
                    raise OverloadTierRegistryError(f"重复 state_effect_id: {state_id}")
                seen_ids.add(state_id)
                level = (record_id % 10 - 1) * 5 + offset + 1
                if not 1 <= level <= 15:
                    raise OverloadTierRegistryError(f"等级超出 1--15: {level}")
                result.append(OverloadTierMetadata(
                    state_effect_id=state_id,
                    group_id=group_id,
                    label=label,
                    level=level,
                    source_url=source_url,
                    source_sha256=source_sha256,
                    algorithm_source_url=algorithm_url,
                    algorithm_source_sha256=algorithm_sha256,
                ))
            if (group_id, record_id) in seen_records:
                raise OverloadTierRegistryError(f"重复来源记录: {(group_id, record_id)!r}")
            seen_records.add((group_id, record_id))
        return result

    @staticmethod
    def _source_url(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OverloadTierRegistryError(f"{field} 缺失")
        parsed = urlparse(value.strip())
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise OverloadTierRegistryError(f"{field} 必须是无凭据 HTTPS")
        return value.strip()

    @staticmethod
    def _sha(value: Any, field: str) -> str:
        if not isinstance(value, str) or not _SHA256.fullmatch(value.strip().lower()):
            raise OverloadTierRegistryError(f"{field} 无效")
        return value.strip().lower()

    @staticmethod
    def _id(value: Any, field: str) -> str:
        if isinstance(value, bool):
            raise OverloadTierRegistryError(f"{field} 必须是十进制 ID")
        text = str(value).strip()
        if not _ID.fullmatch(text):
            raise OverloadTierRegistryError(f"{field} 必须是十进制 ID")
        return text

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise OverloadTierRegistryError(f"{field} 必须是正整数")
        return value
