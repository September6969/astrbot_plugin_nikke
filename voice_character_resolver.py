# SPDX-License-Identifier: GPL-3.0-or-later
"""200 名可玩妮姬的语音角色统一查询与身份解析器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .character_identity import CharacterDirectoryResolver


class VoiceCharacterResolver:
    """统一解析 200 名可玩妮姬的语音角色标识。

    支持：
    - 规范角色键（如 rapi, arcana, alice, drake, scarlet）
    - Spine 资产号（如 c010, c581, c191, c101）
    - 官方资源 ID（如 10, 581, 191, 101）
    - 繁体中文名称（如 阿爾卡娜, 愛麗絲, 紅蓮, 桃樂絲, 德雷克）
    - 简体中文名称与常见别名（如 阿尔卡娜, 爱丽丝, 红莲, 桃乐丝, 德雷克）
    - 英文名称（如 Arcana, Alice, Scarlet, Dorothy, Drake）
    """

    def __init__(self, asset_dir: str | Path | None = None, user_aliases: Any = None):
        if asset_dir is None:
            asset_dir = Path(__file__).resolve().parent / "assets"
        else:
            asset_dir = Path(asset_dir).resolve()

        self.asset_dir = asset_dir
        catalog_path = self.asset_dir / "character_catalog.json"
        alias_path = self.asset_dir / "character_aliases.json"

        self.identity_resolver = CharacterDirectoryResolver(alias_path, user_aliases=user_aliases)
        self.key_to_resource_id: dict[str, int] = {}
        self.resource_id_to_key: dict[int, str] = {}
        self.spine_to_key: dict[str, str] = {}
        self.static_directory: list[dict[str, Any]] = []

        self._load_catalog(catalog_path)

    def load_user_aliases(self, user_aliases: Any) -> None:
        """加载并合并用户自定义别名。"""
        self.identity_resolver.load_user_aliases(user_aliases)

    def _load_catalog(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        characters = data.get("characters", []) if isinstance(data, dict) else []
        for row in characters:
            if not isinstance(row, dict):
                continue
            rid = row.get("resource_id")
            key = str(row.get("character_key", "")).strip().lower()
            spine = str(row.get("spine_asset_id", "")).strip().lower()
            if rid is None or not key:
                continue
            try:
                rid_int = int(rid)
            except (TypeError, ValueError):
                continue

            self.key_to_resource_id[key] = rid_int
            self.resource_id_to_key[rid_int] = key
            if spine:
                self.spine_to_key[spine] = key

            self.static_directory.append({
                "id": rid_int,
                "resource_id": rid_int,
                "name_code": row.get("name_code") or key,
                "name_zh_tw": str(row.get("name_zh_tw", "")).strip(),
                "name_cn": str(row.get("name_zh_tw", "")).strip(),
                "name_en": str(row.get("name_en", "")).strip(),
                "character_key": key,
                "spine_asset_id": spine,
            })

    def get_resource_id(self, character_key: str | None) -> int | None:
        """获取角色的 resource_id。"""
        if not character_key:
            return None
        return self.key_to_resource_id.get(str(character_key).strip().lower())

    def get_character_key(self, resource_id: int | str | None) -> str | None:
        """从 resource_id 获取规范角色键。"""
        if resource_id is None:
            return None
        try:
            return self.resource_id_to_key.get(int(resource_id))
        except (TypeError, ValueError):
            return None

    def resolve(
        self,
        query: str | None,
        directory: Iterable[dict[str, Any]] | None = None,
    ) -> str | None:
        """将用户输入的名称、代码或别名解析为 200 妮姬中的规范角色键。"""
        if not query:
            return None
        term = str(query).strip().lower()
        if not term:
            return None

        # 1. 直接匹配 canonical key
        if term in self.key_to_resource_id:
            return term

        # 2. 直接匹配 spine asset id (e.g. c010, c581)
        if term in self.spine_to_key:
            return self.spine_to_key[term]

        # 3. 直接匹配 resource_id (e.g. 10, 581)
        if term.isdigit():
            rid = int(term)
            if rid in self.resource_id_to_key:
                return self.resource_id_to_key[rid]

        # 4. 若传入实时 directory，使用 CharacterDirectoryResolver 查找
        active_directory = directory if directory else self.static_directory
        matches = self.identity_resolver.find(active_directory, query)
        if matches:
            best = matches[0]
            rid = best.get("resource_id")
            if rid is not None:
                try:
                    matched_key = self.resource_id_to_key.get(int(rid))
                    if matched_key:
                        return matched_key
                except (TypeError, ValueError):
                    pass
            code = str(best.get("name_code", "")).strip().lower()
            if code in self.key_to_resource_id:
                return code
            char_key = str(best.get("character_key", "")).strip().lower()
            if char_key in self.key_to_resource_id:
                return char_key

        # 5. 若传入的 active_directory 不是 static_directory，兜底到 static_directory
        if active_directory is not self.static_directory:
            matches = self.identity_resolver.find(self.static_directory, query)
            if matches:
                best = matches[0]
                rid = best.get("resource_id")
                if rid is not None:
                    try:
                        matched_key = self.resource_id_to_key.get(int(rid))
                        if matched_key:
                            return matched_key
                    except (TypeError, ValueError):
                        pass
                code = str(best.get("name_code", "")).strip().lower()
                if code in self.key_to_resource_id:
                    return code
                char_key = str(best.get("character_key", "")).strip().lower()
                if char_key in self.key_to_resource_id:
                    return char_key

        # 6. 检查是否直接通过规范映射解析
        canonical = self.identity_resolver.resolve_canonical(term)
        if canonical in self.key_to_resource_id:
            return canonical

        return None
