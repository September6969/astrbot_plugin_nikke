# SPDX-License-Identifier: GPL-3.0-or-later
"""按证据登记角色、服装和 locale 到官方语音资源的精确映射。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class VoiceMappingValidationError(ValueError):
    """语音映射清单不符合严格合同。"""


@dataclass(frozen=True, slots=True)
class VoiceMapping:
    character: str
    costume: str
    spine_asset_id: str
    locale: str
    map_key: str
    speech_id: str
    source: str
    source_ref: str
    checked_at: str
    line_kind: str = "Lobby_Touch"
    line_index: int = 1


class VoiceMapRegistry:
    """加载精确的 Poke 语音映射；未知角色或服装不做默认借用。"""

    LOCALES = {"en", "ja", "ko"}
    IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")
    COSTUME = re.compile(r"^(?:default|[a-zA-Z0-9][a-zA-Z0-9_-]{0,99})$")
    SPINE_ASSET = re.compile(r"^c\d+(?:_\d+)?$")
    SPEECH_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.errors: list[str] = []
        self._entries: dict[tuple[str, str, str, str, int], VoiceMapping] = {}
        self._load()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def resolve_candidates(
        self,
        character: str | None,
        costume: str | int | None,
        locale: str | None,
        *,
        spine_asset_id: str | None = None,
        line_kind: str = "Lobby_Touch",
    ) -> list[VoiceMapping]:
        """查找指定角色、服装和 locale 下所有可用的语音条目（如 Lobby_Touch_1..3）。"""
        if not isinstance(character, str) or not isinstance(locale, str):
            return []
        normalized_character = character.strip().lower()
        normalized_locale = locale.strip().lower()
        normalized_costume = "default" if costume in (None, "", 0, "default") else str(costume).strip().lower()
        if not self.IDENTIFIER.fullmatch(normalized_character) or normalized_locale not in self.LOCALES:
            return []
        if not self.COSTUME.fullmatch(normalized_costume):
            return []
        if line_kind != "Lobby_Touch":
            return []
        target_spine = str(spine_asset_id).strip().lower() if spine_asset_id is not None else None
        return [
            e for e in self._entries.values()
            if e.character == normalized_character
            and e.costume == normalized_costume
            and e.locale == normalized_locale
            and e.line_kind == line_kind
            and (target_spine is None or e.spine_asset_id == target_spine)
        ]

    def resolve_candidates_by_spine_asset(
        self,
        spine_asset_id: str | None,
        locale: str | None,
        *,
        line_kind: str = "Lobby_Touch",
    ) -> list[VoiceMapping]:
        """按共享 canonical Spine asset ID 查找所有可用的语音条目。"""
        if not isinstance(spine_asset_id, str) or not self.SPINE_ASSET.fullmatch(spine_asset_id.strip().lower()):
            return []
        if not isinstance(locale, str) or locale.strip().lower() not in self.LOCALES:
            return []
        if line_kind != "Lobby_Touch":
            return []
        return [
            entry for entry in self._entries.values()
            if entry.spine_asset_id == spine_asset_id.strip().lower()
            and entry.locale == locale.strip().lower()
            and entry.line_kind == line_kind
        ]

    def resolve(
        self,
        character: str | None,
        costume: str | int | None,
        locale: str | None,
        *,
        spine_asset_id: str | None = None,
        line_kind: str = "Lobby_Touch",
        line_index: int | None = None,
    ) -> VoiceMapping | None:
        """只查找完整身份键；没有精确映射时返回 None。对 Poke 只解析 Lobby_Touch。"""
        candidates = self.resolve_candidates(
            character, costume, locale, spine_asset_id=spine_asset_id, line_kind=line_kind
        )
        if not candidates:
            return None
        if line_index is not None:
            for c in candidates:
                if c.line_index == line_index:
                    return c
            return None
        return candidates[0]

    def resolve_by_spine_asset(
        self,
        spine_asset_id: str | None,
        locale: str | None,
        *,
        line_kind: str = "Lobby_Touch",
        line_index: int | None = None,
    ) -> VoiceMapping | None:
        """按共享 canonical Spine identity查找，避免 Voice 自行猜测皮肤。对 Poke 只解析 Lobby_Touch。"""
        candidates = self.resolve_candidates_by_spine_asset(
            spine_asset_id, locale, line_kind=line_kind
        )
        if not candidates:
            return None
        if line_index is not None:
            for c in candidates:
                if c.line_index == line_index:
                    return c
            return None
        return candidates[0]

    def resolve_poke(
        self,
        character: str | None,
        costume: str | int | None,
        locale: str | None,
        *,
        spine_asset_id: str | None = None,
        selector: Callable[[list[VoiceMapping]], VoiceMapping] | None = None,
    ) -> VoiceMapping | None:
        """为 Poke 互动从实际可用的 Lobby_Touch 映射中选取条目。

        对 3 条语音的角色在 1..3 之间随机选择；
        对仅有 1 条语音的角色（如 9 名量产型）稳定选择 line 1。
        支持传入 selector 函数便于可预测测试。
        """
        candidates = self.resolve_candidates(character, costume, locale, spine_asset_id=spine_asset_id)
        if not candidates and spine_asset_id:
            candidates = self.resolve_candidates_by_spine_asset(spine_asset_id, locale)
        if not candidates:
            return None
        if selector is not None:
            return selector(candidates)
        import random
        return random.choice(candidates)

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
            if not isinstance(data, dict) or data.get("schema_version") not in (2, 3):
                raise VoiceMappingValidationError("voice_poke_map schema_version 无效")
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise VoiceMappingValidationError("voice_poke_map 缺少 entries 数组")
            for row in entries:
                entry = self._parse_entry(row)
                key = (entry.character, entry.costume, entry.locale, entry.line_kind, entry.line_index)
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
        required = ("character", "costume", "spine_asset_id", "locale", "map_key", "speech_id", "source", "source_ref", "checked_at")
        if any(not isinstance(row.get(field), str) or not row[field].strip() for field in required):
            raise VoiceMappingValidationError("语音映射来源字段缺失")
        character = row["character"].strip().lower()
        costume = row["costume"].strip().lower()
        spine_asset_id = row["spine_asset_id"].strip().lower()
        locale = row["locale"].strip().lower()
        map_key = row["map_key"].strip().lower()
        speech_id = row["speech_id"].strip()
        line_kind = str(row.get("line_kind", "Lobby_Touch")).strip()
        line_index = row.get("line_index", 1)
        if isinstance(line_index, bool) or not isinstance(line_index, int) or not (1 <= line_index <= 10):
            raise VoiceMappingValidationError("语音 line_index 无效")
        if not cls.IDENTIFIER.fullmatch(character) or not cls.COSTUME.fullmatch(costume) or not cls.SPINE_ASSET.fullmatch(spine_asset_id):
            raise VoiceMappingValidationError("语音角色或服装标识无效")
        if locale not in cls.LOCALES or not cls.IDENTIFIER.fullmatch(map_key) or not cls.SPEECH_ID.fullmatch(speech_id):
            raise VoiceMappingValidationError("语音 locale 或资源标识无效")
        if not cls.IDENTIFIER.fullmatch(line_kind):
            raise VoiceMappingValidationError("语音 line_kind 标识无效")
        if not row["source"].startswith("https://") or not row["source_ref"].startswith("https://"):
            raise VoiceMappingValidationError("语音映射来源必须是 HTTPS")
        return VoiceMapping(character, costume, spine_asset_id, locale, map_key, speech_id,
                            row["source"].strip(), row["source_ref"].strip(), row["checked_at"].strip(),
                            line_kind, line_index)
