# SPDX-License-Identifier: GPL-3.0-or-later
"""资源组件组合根与兼容性 facade；解析、缓存和下载由 core.assets 子组件持有。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from astrbot_plugin_nikke.features.character.costume_asset_resolver import CostumeAssetResolver
from astrbot_plugin_nikke.features.character.lineup_portrait_resolver import LineupPortraitResolver
from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.features.character.models import CharacterCardAssets, CharacterCardData
from astrbot_plugin_nikke.features.character.registries.static import StaticDataRegistry
from astrbot_plugin_nikke.features.character.skill_icon_resolver import SkillIconResolver
from astrbot_plugin_nikke.features.character.visual_resolver import CharacterVisualAssetResolver
from astrbot_plugin_nikke.features.profile.currency_registry import CurrencyRegistry
from astrbot_plugin_nikke.features.raid.boss_resolver import BossAssetResolver
from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer

from .assets.downloader import AssetDownloader
from .assets.environment import AssetEnvironment
from .assets.icon_assets import IconAssetService, load_static_icon_mappings
from .assets.image_cache import AssetImageCache
from .assets.image_codec import AssetImageCodec
from .assets.models import AssetResult
from .assets.prefetcher import CharacterCardPrefetcher
from .assets.resource_url import game_resource_url
from .assets.spine_assets import CharacterAssetService, SpineAssetService
from .assets.spine_manifest import SpineManifestStore

logger = logging.getLogger("nikke.asset_manager")


class AssetManager:
    """维护唯一资源依赖图并委托到无状态域服务或独立生命周期组件。"""

    MAX_BYTES = AssetImageCodec.MAX_BYTES
    MAX_PIXELS = AssetImageCodec.MAX_PIXELS
    MAX_PREFETCH_TASKS = CharacterCardPrefetcher.MAX_PREFETCH_TASKS
    REMOTE_DOWNLOAD_LIMIT = AssetDownloader.REMOTE_DOWNLOAD_LIMIT
    CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"

    def __init__(
        self,
        cache_dir: str | Path,
        asset_dir: str | Path,
        *,
        remote: bool = False,
        spine_renderer: SpinePreRenderer | None = None,
        spine_budget_seconds: float = 20.0,
        spine_manifest_path: str | Path | None = None,
        spine_rendered_dir: str | Path | None = None,
    ) -> None:
        self.cache_dir, self.asset_dir = Path(cache_dir), Path(asset_dir)
        self.remote = remote
        if isinstance(spine_budget_seconds, bool) or not isinstance(spine_budget_seconds, (int, float)) or spine_budget_seconds <= 0:
            raise ValueError("Spine 预渲染预算必须是正数")
        self.spine_budget_seconds = float(spine_budget_seconds)
        self.character_master = CharacterMasterResolver(self._character_master_path())
        self.spine_renderer = spine_renderer if spine_renderer is not None else SpinePreRenderer(self.cache_dir)
        self.nikke_db = NikkeDbProvider(
            self.cache_dir, self.asset_dir, remote=remote, master_resolver=self.character_master
        )
        self.spine_manifest = SpineManifestStore(
            self.asset_dir,
            self.cache_dir,
            manifest_path=spine_manifest_path,
            rendered_dir=spine_rendered_dir,
        )
        self.spine_manifest_path = Path(spine_manifest_path) if spine_manifest_path is not None else None
        self.spine_rendered_dir = Path(spine_rendered_dir) if spine_rendered_dir is not None else None
        self.blabla_assets_dir = self.asset_dir.parent / "data" / "nikke" / "blabla-assets"
        self.lineup_resolver = LineupPortraitResolver(self.blabla_assets_dir, self.asset_dir)
        self.boss_resolver = BossAssetResolver(self.blabla_assets_dir, self.asset_dir)
        self.lineup_portrait_resolver = self.lineup_resolver
        self.boss_asset_resolver = self.boss_resolver
        self.registry = StaticDataRegistry(self.asset_dir)
        self.currency_registry = CurrencyRegistry()
        for error in self.registry.errors:
            logger.warning("静态 registry 校验失败：%s", error)
        self.equipment_map = self.registry.mapping("equipment")
        self.favorite_items_map = self.registry.mapping("favorite_item")
        self.cubes_map = self.registry.mapping("cube")
        self.costumes_map = self.registry.mapping("costume")
        self.skill_resolver = SkillIconResolver(self.asset_dir / "mappings" / "skill_icons.json")
        self.costume_resolver = CostumeAssetResolver(self.asset_dir / "mappings" / "costume_assets.json")
        self.visual_resolver = CharacterVisualAssetResolver(
            self.asset_dir / "mappings" / "costume_visual_assets.json",
            self.asset_dir / "mappings" / "spine_metadata.json",
        )
        self.cube_icons_map, self.favorite_item_icons_map = load_static_icon_mappings(self.asset_dir)
        self.sources = self._load_sources()
        mirror_parent = self.blabla_assets_dir.parent.parent.parent
        self.image_cache = AssetImageCache(
            self.cache_dir,
            self.asset_dir,
            extra_roots=(self.blabla_assets_dir, mirror_parent),
        )
        self.downloader = AssetDownloader(self.image_cache, remote_enabled=remote)
        self._failed = self.downloader.failed_until
        self.environment = AssetEnvironment(
            cache_dir=self.cache_dir,
            asset_dir=self.asset_dir,
            remote=remote,
            sources=self.sources,
            image_cache=self.image_cache,
            downloader=self.downloader,
            nikke_db=self.nikke_db,
            spine_renderer=self.spine_renderer,
            spine_budget_seconds=self.spine_budget_seconds,
            spine_manifest=self.spine_manifest,
            character_master=self.character_master,
            registry=self.registry,
            currency_registry=self.currency_registry,
            skill_resolver=self.skill_resolver,
            costume_resolver=self.costume_resolver,
            visual_resolver=self.visual_resolver,
            lineup_resolver=self.lineup_resolver,
            boss_resolver=self.boss_resolver,
            cube_icons_map=self.cube_icons_map,
            favorite_item_icons_map=self.favorite_item_icons_map,
        )
        self._spine = SpineAssetService(self.environment)
        self._characters = CharacterAssetService(
            self.environment,
            self._spine,
            lineup_lookup=lambda **kwargs: self.resolve_lineup_portrait(**kwargs),
            boss_lookup=lambda **kwargs: self.resolve_boss_asset(**kwargs),
        )
        self._icons = IconAssetService(self.environment)
        self._prefetcher = CharacterCardPrefetcher(self.environment, self._characters, self._icons)
        self._closed = False

    def _character_master_path(self) -> Path:
        candidates = (self.asset_dir / "data" / "character_master.json", self.asset_dir / "character_master.json")
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _load_sources(self) -> dict[str, Any]:
        path = self.asset_dir / "data" / "sources.json"
        if not path.is_file():
            path = self.asset_dir / "sources.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def game_resource_url(path: str) -> str:
        return game_resource_url(path)

    @staticmethod
    def _key(value) -> str:
        return AssetEnvironment.key(value)

    @classmethod
    def _decode(cls, content: bytes, require_alpha: bool = False) -> Image.Image:
        return AssetImageCodec.decode(content, require_alpha=require_alpha)

    @classmethod
    def validate_image(cls, content_or_path: bytes | str | Path, require_alpha: bool = False) -> Image.Image:
        return AssetImageCodec.validate(content_or_path, require_alpha=require_alpha)

    @classmethod
    def fallback(cls, kind: str) -> Image.Image:
        return AssetImageCodec.fallback(kind)

    def _load(self, kind: str, key: str, remote_url: str = "", *, allow_source: bool = True) -> Image.Image | None:
        return self.environment.load(kind, key, remote_url, allow_source=allow_source)

    def refresh_spine_manifest(self) -> None:
        self.spine_manifest.refresh()

    def _spine_cache_key(self, char_id, costume_id, runtime_version, animation: str | None = None) -> str:
        return self._spine.cache_key(char_id, costume_id, runtime_version, animation)

    def get_character_portrait(self, name_code, resource_id, costume_id=None):
        return self._characters.get_character_portrait(name_code, resource_id, costume_id)

    def get_lineup_portrait(self, tid=None, costume_id=None, character_id=None, avatar_id=None):
        return self._characters.get_lineup_portrait(tid, costume_id, character_id, avatar_id)

    def resolve_lineup_portrait(self, **kwargs):
        return self._characters.resolve_lineup_portrait(**kwargs)

    def get_boss_image(self, boss_id=None, icon_id=None, monster_model_id=None, boss_name=None):
        return self._characters.get_boss_image(boss_id, icon_id, monster_model_id, boss_name)

    def resolve_boss_asset(self, **kwargs):
        return self._characters.resolve_boss_asset(**kwargs)

    def enqueue_experimental_spine(self, resource_id, costume_id=None) -> bool:
        return self._spine.enqueue_experimental(resource_id, costume_id)

    def get_equipment_icon(self, slot, equipment_id):
        return self._icons.get_equipment_icon(slot, equipment_id)

    def _icon(self, kind, key, fallback, url="", *, allow_source=True):
        return self._icons.icon(kind, key, fallback, url, allow_source=allow_source)

    def get_skill_icon(self, resource_id, slot, variant="normal"):
        return self._icons.get_skill_icon(resource_id, slot, variant)

    def get_character_asset(self, resource_id, costume_id=None, kind="fullbody"):
        return self._characters.get_character_asset(resource_id, costume_id, kind)

    def get_character_icon(self, resource_id, costume_id=None):
        return self._characters.get_character_icon(resource_id, costume_id)

    def get_character_fullbody(self, resource_id, costume_id=None):
        return self._characters.get_character_fullbody(resource_id, costume_id)

    def get_character_spine(self, resource_id, costume_id=None):
        return self._characters.get_character_spine(resource_id, costume_id)

    def get_character_placement(self, resource_id, costume_id=None):
        return self._characters.get_character_placement(resource_id, costume_id)

    def get_costume_portrait(self, resource_id, costume_id=None):
        return self._characters.get_costume_portrait(resource_id, costume_id)

    def get_favorite_item_icon(self, tid):
        return self._icons.get_favorite_item_icon(tid)

    def get_cube_icon(self, tid):
        return self._icons.get_cube_icon(tid)

    def get_class_icon(self, class_name):
        return self._icons.get_class_icon(class_name)

    def get_manufacturer_icon(self, manufacturer):
        return self._icons.get_manufacturer_icon(manufacturer)

    def get_rarity_icon(self, rarity):
        return self._icons.get_rarity_icon(rarity)

    def get_currency_icon(self, currency_type):
        return self._icons.get_currency_icon(currency_type)

    def get_element_icon(self, element):
        return self._icons.get_element_icon(element)

    def get_corporation_icon(self, corporation):
        return self._icons.get_corporation_icon(corporation)

    def get_weapon_icon(self, weapon):
        return self._icons.get_weapon_icon(weapon)

    def get_burst_icon(self, burst):
        return self._icons.get_burst_icon(burst)

    @property
    def _executor(self):
        return self._prefetcher.executor

    @_executor.setter
    def _executor(self, executor):
        self._prefetcher.executor = executor

    @property
    def _prefetch_slots(self):
        return self._prefetcher.slots

    def _submit_prefetch(self, func):
        return self._prefetcher.submit(func)

    def resolve_character_assets(self, data: CharacterCardData, timeout: float = 6.0) -> CharacterCardAssets:
        return self._prefetcher.resolve_character_assets(data, timeout)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._prefetcher.close()
        try:
            self.spine_renderer.close(wait=False)
        except Exception:
            pass
