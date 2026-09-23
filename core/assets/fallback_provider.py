# SPDX-License-Identifier: GPL-3.0-or-later
"""不持有缓存、网络或后台任务的 renderer 安全降级资源 provider。"""

from __future__ import annotations

from PIL import Image

from ...features.character.models import CharacterCardAssets
from .image_codec import AssetImageCodec


class FallbackAssetProvider:
    """供独立预览/布局测试使用；正式运行时由容器注入共享资源 owner。"""

    @staticmethod
    def fallback(kind: str) -> Image.Image:
        return AssetImageCodec.fallback(kind)

    def get_character_portrait(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("portrait")

    def get_favorite_item_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("favorite")

    def get_cube_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("cube")

    def get_equipment_icon(self, slot: str, *_args, **_kwargs) -> Image.Image:
        return self.fallback(slot)

    def get_element_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("element")

    def get_corporation_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("corporation")

    def get_weapon_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("weapon")

    def get_burst_icon(self, *_args, **_kwargs) -> Image.Image:
        return self.fallback("burst")

    def resolve_character_assets(self, _data, timeout: float = 6.0) -> CharacterCardAssets:
        del timeout
        return CharacterCardAssets(
            portrait=self.fallback("portrait"),
            equipment={slot: self.fallback(slot) for slot in ("head", "torso", "arm", "leg")},
            favorite_item=self.fallback("favorite"),
            cube=self.fallback("cube"),
            element=self.fallback("element"),
            corporation=self.fallback("corporation"),
            weapon=self.fallback("weapon"),
            burst=self.fallback("burst"),
        )
