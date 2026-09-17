# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 角色皮肤与立绘资源映射解析器。

建立明确的链路：
player character + costume_id
        ↓
CostumeAssetResolver
        ↓
CostumeResolution (精确匹配或明确 fallback 状态声明)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("nikke.costume_resolver")


@dataclass(slots=True)
class CostumeResolution:
    """皮肤与角色资源定位结果契约。"""

    resource_id: str | None
    character_id: str | None
    costume_id: str | None
    costume_name: str | None
    spine_asset_id: str | None
    si_asset_key: str | None
    exact_match: bool
    fallback_reason: str | None  # None, "unknown_costume", "owner_mismatch", "invalid_costume_id"
    character_name: str = ""


class CostumeAssetResolver:
    """角色皮肤资源解析器，严格区分 exact match 与 fallback。"""

    RESET_TERMS = {"默认", "default", "原皮", "0", "none", "null", ""}

    def __init__(self, mapping_path: str | Path | None = None):
        if mapping_path is None:
            self.mapping_path = Path(__file__).resolve().parents[2] / "assets" / "mappings" / "costume_assets.json"
        else:
            self.mapping_path = Path(mapping_path).resolve()

        self._characters: dict[str, dict[str, Any]] = {}
        self._all_costumes: dict[str, tuple[str, dict[str, Any]]] = {}  # costume_id -> (owner_rid, costume_data)
        self._load()

    def _load(self) -> None:
        if not self.mapping_path.is_file():
            logger.warning("Costume assets mapping file not found: %s", self.mapping_path)
            return
        try:
            data = json.loads(self.mapping_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                chars = data.get("characters", {})
                if isinstance(chars, dict):
                    self._characters = chars
                    for rid, c_info in chars.items():
                        costumes = c_info.get("costumes", {})
                        if isinstance(costumes, dict):
                            for cid, c_entry in costumes.items():
                                self._all_costumes[str(cid)] = (rid, c_entry)
        except Exception as exc:
            logger.warning("Failed to load costume catalog from %s: %s", self.mapping_path, exc)

    @property
    def total_characters(self) -> int:
        return len(self._characters)

    @property
    def total_costumes(self) -> int:
        return len(self._all_costumes)

    def resolve(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
        character_id: str | int | None = None,
    ) -> CostumeResolution:
        """根据角色 resource_id 与 costume_id 精确解析皮肤。
        
        若 costume_id 有值但无法匹配或所有者不匹配，强制返回 exact_match=False，
        并附带明确的 fallback_reason，绝不谎报为 exact match。
        """
        # 1. 基础角色校验
        rid_str = str(resource_id).strip() if (resource_id is not None and not isinstance(resource_id, bool)) else None
        char_entry = self._characters.get(rid_str or "") if rid_str else None

        default_spine = char_entry.get("default", {}).get("spine_asset_id") if char_entry else (f"c{int(rid_str):03d}" if (rid_str and rid_str.isdigit()) else None)
        default_si = char_entry.get("default", {}).get("si_asset_key") if char_entry else (f"si_c{int(rid_str):03d}_00_s" if (rid_str and rid_str.isdigit()) else None)
        char_name = char_entry.get("name_cn") or char_entry.get("name_en") or "" if char_entry else ""
        cid_resolved = str(char_entry.get("character_id", "")) if char_entry else (str(character_id) if character_id else None)

        # 2. 默认原皮情况 (costume_id 为空、0 或重置词)
        if costume_id is None or isinstance(costume_id, bool):
            is_default = True
            cid_str = None
        else:
            cid_str = str(costume_id).strip()
            is_default = cid_str.lower() in self.RESET_TERMS

        if is_default:
            return CostumeResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=None,
                costume_name="默认皮肤",
                spine_asset_id=default_spine,
                si_asset_key=default_si,
                exact_match=True,
                fallback_reason=None,
                character_name=char_name,
            )

        # 3. 指定了有效格式的 costume_id
        if char_entry is None:
            return CostumeResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=cid_str,
                costume_name=None,
                spine_asset_id=default_spine,
                si_asset_key=default_si,
                exact_match=False,
                fallback_reason="unknown_character",
                character_name=char_name,
            )

        # 检查当前角色的皮肤映射
        costumes_map = char_entry.get("costumes", {})
        if cid_str in costumes_map:
            costume_info = costumes_map[cid_str]
            return CostumeResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=cid_str,
                costume_name=costume_info.get("costume_name"),
                spine_asset_id=costume_info.get("spine_asset_id"),
                si_asset_key=costume_info.get("si_asset_key"),
                exact_match=True,
                fallback_reason=None,
                character_name=char_name,
            )

        # 检查该皮肤是否存在于其它角色（所有者不匹配）
        if cid_str in self._all_costumes:
            other_owner, other_info = self._all_costumes[cid_str]
            return CostumeResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=cid_str,
                costume_name=other_info.get("costume_name"),
                spine_asset_id=default_spine,
                si_asset_key=default_si,
                exact_match=False,
                fallback_reason="owner_mismatch",
                character_name=char_name,
            )

        # 未知皮肤
        return CostumeResolution(
            resource_id=rid_str,
            character_id=cid_resolved,
            costume_id=cid_str,
            costume_name=None,
            spine_asset_id=default_spine,
            si_asset_key=default_si,
            exact_match=False,
            fallback_reason="unknown_costume",
            character_name=char_name,
        )
