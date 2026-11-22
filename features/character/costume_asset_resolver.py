# SPDX-License-Identifier: GPL-3.0-or-later
"""离线审计兼容入口：皮肤解析已合并到 CharacterVisualAssetResolver.resolve_costume。

PR-6B（G6-character-spine-b1）起生产代码不再装配本类；AssetManager 通过
``visual_resolver.resolve_costume`` 提供 get_costume_portrait。仅
scripts/audit/audit_assets.py 仍按旧名称导入，该脚本迁移后即可删除本模块。
"""

from __future__ import annotations

from pathlib import Path

from .visual_resolver import CharacterVisualAssetResolver, CostumeResolution


class CostumeAssetResolver:
    """以同目录的 costume_visual_assets.json 为唯一数据源的兼容包装。"""

    RESET_TERMS = CharacterVisualAssetResolver.RESET_TERMS

    def __init__(self, mapping_path: str | Path | None = None):
        catalog = None
        if mapping_path is not None:
            catalog = Path(mapping_path).resolve().with_name("costume_visual_assets.json")
        self._resolver = CharacterVisualAssetResolver(catalog)

    @property
    def total_characters(self) -> int:
        return self._resolver.total_characters

    @property
    def total_costumes(self) -> int:
        return self._resolver.total_costumes

    def resolve(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
        character_id: str | int | None = None,
    ) -> CostumeResolution:
        return self._resolver.resolve_costume(resource_id, costume_id, character_id)


__all__ = ["CostumeAssetResolver", "CostumeResolution"]
