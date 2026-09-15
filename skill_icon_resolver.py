# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 角色技能图标逻辑键解析器。

职责仅包括：
角色 ID + slot + variant -> 逻辑 icon key
不执行任何网络请求或文件下载。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger("nikke.skill_resolver")


class SkillIconResolver:
    """根据真实技能表将 (resource_id, slot, variant) 解析为逻辑图标 ID。"""

    SLOT_MAP = {
        "s1": "s1",
        "skill1": "s1",
        "skill_1": "s1",
        "1": "s1",
        "s2": "s2",
        "skill2": "s2",
        "skill_2": "s2",
        "2": "s2",
        "burst": "burst",
        "burst_skill": "burst",
        "ulti": "burst",
        "ult": "burst",
        "3": "burst",
    }

    _CHAR_SPECIFIC_PATTERN = re.compile(r"icn_skill_c\d+", re.IGNORECASE)

    def __init__(self, mapping_path: str | Path | None = None):
        if mapping_path is None:
            self.mapping_path = Path(__file__).resolve().parent / "assets" / "mappings" / "skill_icons.json"
        else:
            self.mapping_path = Path(mapping_path).resolve()

        self._characters: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.mapping_path.is_file():
            logger.warning("Skill icon mapping file not found: %s", self.mapping_path)
            return
        try:
            data = json.loads(self.mapping_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                chars = data.get("characters")
                if isinstance(chars, dict):
                    self._characters = chars
        except Exception as exc:
            logger.warning("Failed to load skill icons mapping from %s: %s", self.mapping_path, exc)

    @property
    def total_characters(self) -> int:
        return len(self._characters)

    @classmethod
    def normalize_slot(cls, slot: str) -> str | None:
        if not isinstance(slot, str):
            return None
        return cls.SLOT_MAP.get(slot.strip().lower())

    @classmethod
    def is_generic_icon(cls, icon_key: str) -> bool:
        """判断图标是否为跨角色复用的通用技能图标。"""
        if not icon_key:
            return False
        # 专属技能图标包含 icn_skill_c{resource_id}
        return not bool(cls._CHAR_SPECIFIC_PATTERN.search(icon_key))

    @classmethod
    def get_logical_subpath(cls, icon_key: str) -> str:
        """返回逻辑物理相对路径（实现通用图标与专属图标去重隔离）。"""
        clean_key = str(icon_key).strip().lower()
        if cls.is_generic_icon(clean_key):
            return f"skills/generic/{clean_key}.png"
        return f"skills/character/{clean_key}.png"

    def resolve(
        self,
        resource_id: str | int,
        slot: str,
        *,
        variant: str = "normal",
    ) -> str | None:
        """解析技能图标逻辑 Key。
        
        slot: "s1" | "s2" | "burst"
        variant: "normal" | "favorite"
        
        返回:
        - 逻辑 icon key (如 "icn_skill_statreloadtime_01", "icn_skill_c102_ult")
        - 若未找到对应图标或参数非法则返回 None
        """
        if isinstance(resource_id, bool) or resource_id is None:
            return None
        rid_str = str(resource_id).strip()
        if not rid_str:
            return None

        canonical_slot = self.normalize_slot(slot)
        if canonical_slot is None:
            return None

        char_data = self._characters.get(rid_str)
        if not char_data or not isinstance(char_data, dict):
            return None

        variant_clean = str(variant or "normal").strip().lower()

        # 1. 若请求 favorite 变体，优先查找 favorite 配置
        if variant_clean == "favorite":
            fav_map = char_data.get("favorite")
            if isinstance(fav_map, dict):
                fav_icon = fav_map.get(canonical_slot)
                if fav_icon and isinstance(fav_icon, str) and fav_icon.strip():
                    return fav_icon.strip()

        # 2. 正常技能或 favorite 缺省时回退至 normal
        normal_map = char_data.get("normal")
        if isinstance(normal_map, dict):
            normal_icon = normal_map.get(canonical_slot)
            if normal_icon and isinstance(normal_icon, str) and normal_icon.strip():
                return normal_icon.strip()

        return None
