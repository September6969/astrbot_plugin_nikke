# SPDX-License-Identifier: GPL-3.0-or-later
"""公告输入字段、locale/category/query 与版本归一化。"""

from __future__ import annotations

import re
from typing import Any

from .models import AnnouncementRecord


class AnnouncementNormalizer:
    """集中执行本地、确定性的公告字段与版本校验。"""

    SUPPORTED_LOCALES = frozenset({"en", "ja", "ko", "th", "de", "fr"})
    CACHE_LOCALES = SUPPORTED_LOCALES | {"und"}
    CATEGORY_ALIASES = {
        "公告": "general",
        "综合": "general",
        "维护": "maintenance",
        "活动": "event",
        "更新": "update",
        "版本更新": "update",
        "开发者笔记": "dev_note",
        "招募": "recruit",
        "联盟突袭": "union_raid",
        "协同作战": "coop",
        "协同": "coop",
        "coop": "coop",
    }

    @classmethod
    def normalize_locale(cls, value: str | None, *, allow_und: bool = False) -> str:
        """只允许已验证的官网语言及缓存迁移值。"""
        if value is not None and not isinstance(value, str):
            raise ValueError("公告语言必须是文本")
        locale = (value or "en").strip().casefold()
        supported = cls.CACHE_LOCALES if allow_und else cls.SUPPORTED_LOCALES
        if locale not in supported:
            raise ValueError("公告语言仅支持 en、ja、ko、th、de、fr")
        return locale

    @staticmethod
    def _locale_from_content_id(content_id: str) -> str:
        parts = content_id.split(":", 2)
        if len(parts) == 3 and parts[0] == "informationfeeds" and parts[1] in AnnouncementNormalizer.SUPPORTED_LOCALES:
            return parts[1]
        return "und"

    @classmethod
    def _normalize_category(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            if value is None:
                return None
            raise ValueError("公告分类必须是文本")
        if not value.strip():
            return None
        category = cls.CATEGORY_ALIASES.get(value.strip().casefold(), value.strip().casefold())
        if len(category) > 32 or not re.fullmatch(r"[a-z0-9_-]+", category):
            raise ValueError("公告分类仅支持本地分类标识或预设中文别名")
        return category

    @staticmethod
    def _normalize_query(value: str | None) -> str | None:
        if not isinstance(value, str):
            if value is None:
                return None
            raise ValueError("公告搜索词必须是文本")
        if not value.strip():
            return None
        query = " ".join(value.split())
        if len(query) > 80:
            raise ValueError("公告搜索词不能超过 80 个字符")
        return query.casefold()

    @staticmethod
    def _normalize_version(value: Any, field_name: str) -> int:
        """只接受正整数版本，避免把布尔值或浮点数静默截断。"""
        if type(value) is int:
            version = value
        elif isinstance(value, str) and re.fullmatch(r"[1-9]\d*", value.strip()):
            version = int(value.strip())
        else:
            raise ValueError(f"{field_name}必须是正整数")
        if version < 1:
            raise ValueError(f"{field_name}必须是正整数")
        return version


class AnnouncementVersioning:
    """判定公告修订顺序并集中计算内容/日程版本递增。"""

    @staticmethod
    def classify(
        existing: AnnouncementRecord | None,
        fingerprint: str,
        revision_history: list[str],
    ) -> str:
        if existing is None:
            return "new"
        if fingerprint == existing.content_fingerprint:
            return "unchanged"
        if fingerprint in revision_history:
            return "stale"
        return "updated"

    @staticmethod
    def next_versions(
        existing: AnnouncementRecord,
        previous_deadlines: list[Any],
        current_deadlines: list[Any],
    ) -> tuple[int, int]:
        return (
            existing.content_version + 1,
            existing.deadline_version + int(previous_deadlines != current_deadlines),
        )
