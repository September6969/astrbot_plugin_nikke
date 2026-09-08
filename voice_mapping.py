# SPDX-License-Identifier: GPL-3.0-or-later
"""按证据登记角色、服装和 locale 到官方语音资源的精确映射。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


class VoiceMappingValidationError(ValueError):
    """语音映射清单不符合严格合同。"""


@dataclass(frozen=True, slots=True)
class VoiceMapping:
    character: str
    costume: str
    locale: str
    map_key: str
    speech_id: str
    source: str
    source_ref: str
    checked_at: str


class VoiceMapRegistry:
    """加载精确的 Poke 语音映射；未知角色或服装不做默认借用。"""

    LOCALES = {"en", "ja", "ko"}
    IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
    COSTUME = re.compile(r"^(?:default|[a-z0-9][a-z0-9_-]{0,99})$")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.errors: list[str] = []
        self._entries: dict[tuple[str, str, str], VoiceMapping] = {}
        self._load()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def resolve(self, character: str | None, costume: str | int | None, locale: str | None) -> VoiceMapping | None:
        """只查找完整身份键；没有精确映射时返回 None。"""
        if not isinstance(character, str) or not isinstance(locale, str):
            return None
        normalized_character = character.strip().lower()
        normalized_locale = locale.strip().lower()
        normalized_costume = "default" if costume in (None, "", 0, "default") else str(costume).strip().lower()
        if not self.IDENTIFIER.fullmatch(normalized_character) or normalized_locale not in self.LOCALES:
            return None
        if not self.COSTUME.fullmatch(normalized_costume):
            return None
        return self._entries.get((normalized_character, normalized_costume, normalized_locale))

    @staticmethod
    def _reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VoiceMappingValidationError(f"JSON 对象包含重复键: {key!r}")
            result[key] = value
        return result

    def _load(self) -> None:
        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8"),
                object_pairs_hook=self._reject_duplicate_keys,
            )
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise VoiceMappingValidationError("voice_poke_map schema_version 无效")
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise VoiceMappingValidationError("voice_poke_map 缺少 entries 数组")
            for row in entries:
                entry = self._parse_entry(row)
                key = (entry.character, entry.costume, entry.locale)
                if key in self._entries:
                    raise VoiceMappingValidationError(f"重复语音身份映射: {key!r}")
                self._entries[key] = entry
        except (OSError, UnicodeError, json.JSONDecodeError, VoiceMappingValidationError) as exc:
            self.errors.append(str(exc))
            self._entries.clear()

    @classmethod
    def _parse_entry(cls, row) -> VoiceMapping:
        if not isinstance(row, dict):
            raise VoiceMappingValidationError("语音映射条目无效")
        required = ("character", "costume", "locale", "map_key", "speech_id", "source", "source_ref", "checked_at")
        if any(not isinstance(row.get(field), str) or not row[field].strip() for field in required):
            raise VoiceMappingValidationError("语音映射来源字段缺失")
        character = row["character"].strip().lower()
        costume = row["costume"].strip().lower()
        locale = row["locale"].strip().lower()
        map_key = row["map_key"].strip().lower()
        speech_id = row["speech_id"].strip().lower()
        if not cls.IDENTIFIER.fullmatch(character) or not cls.COSTUME.fullmatch(costume):
            raise VoiceMappingValidationError("语音角色或服装标识无效")
        if locale not in cls.LOCALES or not cls.IDENTIFIER.fullmatch(map_key) or not cls.IDENTIFIER.fullmatch(speech_id):
            raise VoiceMappingValidationError("语音 locale 或资源标识无效")
        if not row["source"].startswith("https://") or not row["source_ref"].startswith("https://"):
            raise VoiceMappingValidationError("语音映射来源必须是 HTTPS")
        return VoiceMapping(character, costume, locale, map_key, speech_id,
                            row["source"].strip(), row["source_ref"].strip(), row["checked_at"].strip())
