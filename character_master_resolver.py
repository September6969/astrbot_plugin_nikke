# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 官方全量角色静态 Master 解析器。

基于 BlaBlaLink 官方 200 位妮姬全量目录与 character_catalog.json 构建，
提供 Battle TID 归一化解析、官方名称与 Spine 资产定位。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ResolvedCharacter:
    id: int
    battle_tid_prefix: int
    resource_id: int
    name_code: int | None
    character_key: str
    spine_asset_id: str
    name_cn: str
    name_zh_tw: str
    name_en: str
    class_type: str
    weapon: str
    element: str
    burst: str
    corporation: str
    rare: str
    costume_id: int = 0
    default_costume_id: int | None = None


class CharacterMasterResolver:
    """全量静态角色目录解析器。"""

    def __init__(self, master_path: str | Path | None = None):
        if master_path is None:
            master_path = Path(__file__).resolve().parent / "assets" / "character_master.json"
        self._master_path = Path(master_path)
        self._characters: list[ResolvedCharacter] = []
        self._by_prefix: dict[int, ResolvedCharacter] = {}
        self._by_id: dict[int, ResolvedCharacter] = {}
        self._by_resource_id: dict[int, ResolvedCharacter] = {}
        self._by_default_costume_id: dict[int, ResolvedCharacter] = {}
        self._by_name_code: dict[int, ResolvedCharacter] = {}
        self._by_character_key: dict[str, ResolvedCharacter] = {}
        self._by_spine_id: dict[str, ResolvedCharacter] = {}
        self._by_name: dict[str, ResolvedCharacter] = {}
        self._load()

    def _load(self) -> None:
        if not self._master_path.is_file():
            return
        try:
            data = json.loads(self._master_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        chars_raw = data.get("characters", []) if isinstance(data, dict) else []
        for row in chars_raw:
            if not isinstance(row, dict):
                continue
            costume_id = int(row.get("costume_id", 0)) if row.get("costume_id") is not None else 0
            raw_def_costume = row.get("default_costume_id")
            default_costume_id = int(raw_def_costume) if raw_def_costume is not None else None
            char = ResolvedCharacter(
                id=int(row.get("id", 0)),
                battle_tid_prefix=int(row.get("battle_tid_prefix", 0)),
                resource_id=int(row.get("resource_id", 0)),
                name_code=int(row["name_code"]) if row.get("name_code") is not None else None,
                character_key=str(row.get("character_key", "")).strip().lower(),
                spine_asset_id=str(row.get("spine_asset_id", "")).strip().lower(),
                name_cn=str(row.get("name_cn", "")).strip(),
                name_zh_tw=str(row.get("name_zh_tw", "")).strip(),
                name_en=str(row.get("name_en", "")).strip(),
                class_type=str(row.get("class", "")).strip(),
                weapon=str(row.get("weapon", "")).strip(),
                element=str(row.get("element", "")).strip(),
                burst=str(row.get("burst", "")).strip(),
                corporation=str(row.get("corporation", "")).strip(),
                rare=str(row.get("rare", "")).strip(),
                costume_id=costume_id,
                default_costume_id=default_costume_id,
            )
            self._characters.append(char)

            if char.battle_tid_prefix > 0:
                self._by_prefix[char.battle_tid_prefix] = char
            if char.id > 0:
                self._by_id[char.id] = char
            if char.resource_id > 0:
                self._by_resource_id[char.resource_id] = char
            if default_costume_id is not None:
                self._by_default_costume_id[default_costume_id] = char
            if char.name_code is not None:
                self._by_name_code[char.name_code] = char
            if char.character_key:
                self._by_character_key[char.character_key] = char
            if char.spine_asset_id:
                self._by_spine_id[char.spine_asset_id] = char

            for name in (char.name_cn, char.name_zh_tw, char.name_en):
                if name:
                    self._by_name[name.casefold()] = char

    @property
    def total_count(self) -> int:
        return len(self._characters)

    @staticmethod
    def normalize_battle_tid_prefix(tid: int | str) -> int | None:
        """按既有战斗 TID 合同提取规范前缀；异常值保持未知。"""
        if isinstance(tid, bool):
            return None
        try:
            value = int(tid)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value // 100 if value >= 10000 else value

    def resolve_battle_tid(self, tid: int | str) -> ResolvedCharacter | None:
        """根据战斗返回的 6 位 TID（或 4 位前缀、raw id）解析规范角色。

        规则：
        - 5 或 6 位数字：按 tid // 100 归一化为 4 位前缀（去除突破/核心等级 00~11）
        - 直接命中 prefix / raw id / resource_id / name_code
        """
        val = self.normalize_battle_tid_prefix(tid)
        if val is None:
            return None

        # 1. 6 位或 5 位 battle TID: 归一化前缀
        raw_value = int(tid)
        if raw_value >= 10000:
            hit = self._by_prefix.get(val)
            if hit is not None:
                return hit

        # 2. 直接作为 4 位前缀
        hit = self._by_prefix.get(val)
        if hit is not None:
            return hit

        # 3. 直接作为 raw id
        hit = self._by_id.get(val)
        if hit is not None:
            return hit

        # 4. 作为 resource_id
        hit = self._by_resource_id.get(val)
        if hit is not None:
            return hit

        # 5. 作为 name_code
        hit = self._by_name_code.get(val)
        if hit is not None:
            return hit

        return None

    def resolve_member_identity(
        self, tid: int | str
    ) -> tuple[str, str, str, str, ResolvedCharacter | None]:
        """解析阵容成员身份。

        返回: (name_cn, name_en, resource_id_str, spine_asset_id, resolved_char)
        严禁把未知的 tid 作为 resource_id 返回！
        """
        char = self.resolve_battle_tid(tid)
        if char is not None:
            return (
                char.name_cn,
                char.name_en,
                str(char.resource_id),
                char.spine_asset_id,
                char,
            )
        # 未知角色降级
        return (
            f"未知妮姬({tid})",
            f"Unknown({tid})",
            "",
            "",
            None,
        )

    def resolve_by_identifier(self, query: str | int) -> ResolvedCharacter | None:
        """通用角色查询（名称、键名、Spine ID、ID）。"""
        if isinstance(query, int):
            return self.resolve_battle_tid(query)

        s = str(query).strip()
        if not s:
            return None

        if s.isdigit():
            return self.resolve_battle_tid(int(s))

        folded = s.casefold()
        if folded in self._by_character_key:
            return self._by_character_key[folded]
        if folded in self._by_spine_id:
            return self._by_spine_id[folded]
        if folded in self._by_name:
            return self._by_name[folded]

        return None

    def resolve_resource_id(self, resource_id: int | str) -> ResolvedCharacter | None:
        """根据 resource_id（如 95 或 'c095'）返回已解析角色对象。"""
        try:
            r_int = int(str(resource_id).strip().lower().lstrip("c"))
            return self._by_resource_id.get(r_int)
        except (ValueError, TypeError):
            return None

    def is_default_costume(
        self, resource_id: int | str, costume_id: int | str | None
    ) -> bool:
        """检查 costume_id 是否为指定角色的默认服装（0/None/"0"/"default" 或匹配官方 default_costume_id）。"""
        if costume_id is None:
            return True
        if isinstance(costume_id, bool):
            return False
        if isinstance(costume_id, int) and costume_id == 0:
            return True
        c_str = str(costume_id).strip().lower()
        if c_str in {"0", "default", ""}:
            return True
        if not c_str.isdigit():
            return False
        c_int = int(c_str)

        char = self.resolve_resource_id(resource_id)
        if char is not None and char.default_costume_id is not None:
            return char.default_costume_id == c_int

        matching_char = self._by_default_costume_id.get(c_int)
        if matching_char is not None:
            try:
                r_int = int(str(resource_id).strip().lower().lstrip("c"))
                return matching_char.resource_id == r_int
            except (ValueError, TypeError):
                return False

        return False
