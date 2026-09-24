# SPDX-License-Identifier: GPL-3.0-or-later
"""静态 Spine portrait 命中、canonical cache key 与受控预渲染入口。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ...integrations.spine.idle_resolver import IdleAnimationResolver
from ...integrations.spine.prerenderer import SpineBundleFetcher
from .environment import AssetEnvironment
from .image_codec import AssetImageCodec
from .models import AssetResult
from .resource_url import game_resource_url

logger = logging.getLogger("nikke.asset_manager")


class SpineAssetService:
    def __init__(self, environment: AssetEnvironment) -> None:
        self.env = environment

    def cache_key(self, char_id: str, costume_id, runtime_version, animation: str | None = None) -> str:
        if animation is None:
            animation = IdleAnimationResolver.resolve_for_asset(char_id) or "idle"
        return self.env.nikke_db.compute_cache_key(
            char_id,
            costume_id,
            source_version=str(runtime_version),
            runtime_version=str(runtime_version),
            renderer_version=self.env.spine_renderer.RENDERER_VERSION,
            animation=animation,
        )

    def get_static_portrait(
        self,
        char_id: str,
        costume_id,
        *,
        wait_seconds: float = 0.0,
    ) -> Image.Image | None:
        del wait_seconds
        manifest = self.env.spine_manifest
        if manifest.is_declared(char_id):
            image = manifest.load_png(char_id)
            if image is not None:
                return image
            logger.warning("STATIC_SPINE_ASSET_INVALID: %s (costume: %s)", char_id, costume_id)
            return None

        manifest_loaded = manifest.source is not None
        candidate_paths: list[Path] = []
        if not manifest_loaded:
            candidate_paths.append(self.env.asset_dir / "spine-rendered" / f"{char_id}.png")
        if self.env.spine_manifest.rendered_dir is not None and not manifest_loaded:
            candidate_paths.append(self.env.spine_manifest.rendered_dir / f"{char_id}.png")
        candidate_paths.extend(
            [
                self.env.cache_dir / "spine-rendered" / f"{char_id}.png",
                self.env.cache_dir / "portraits" / f"{char_id}.png",
            ]
        )
        seen: set[Path] = set()
        for path in candidate_paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            image = AssetImageCodec.load_file(resolved)
            if image is not None:
                return image

        runtime_version = self.env.nikke_db.resolve_spine_version(char_id, allow_remote=False)
        if runtime_version is not None and runtime_version != "SPINE_VERSION_UNKNOWN":
            animation = IdleAnimationResolver.resolve_for_asset(char_id)
            if animation:
                cache_key = self.cache_key(char_id, costume_id, runtime_version, animation=animation)
                try:
                    cached_path = self.env.spine_renderer.prerender_dir / f"{SpineBundleFetcher._safe_key(cache_key)}.png"
                except (AttributeError, OSError, ValueError):
                    cached_path = None
                if cached_path is not None:
                    cached = AssetImageCodec.load_file(cached_path)
                    if cached is not None:
                        return cached
        return None

    def get_character_portrait(self, name_code, resource_id, costume_id: int | str | None = None) -> Image.Image:
        """仅读静态或版本化本地 Spine 资源；不在查询热路径启动网络/Worker。"""
        char_id = self.env.nikke_db.resolve_render_id(resource_id, costume_id) if resource_id else "missing"
        if char_id != "missing":
            image = self.get_static_portrait(char_id, costume_id)
            if image is not None:
                return image
            logger.warning("STATIC_SPINE_ASSET_MISSING: %s (costume: %s)", char_id, costume_id)
        return self.env.fallback("portrait")

class CharacterAssetService:
    def __init__(
        self,
        environment: AssetEnvironment,
        spine: SpineAssetService,
        *,
        lineup_lookup: Callable[..., Any] | None = None,
        boss_lookup: Callable[..., Any] | None = None,
    ) -> None:
        self.env = environment
        self.spine = spine
        self.lineup_lookup = lineup_lookup or self.resolve_lineup_portrait
        self.boss_lookup = boss_lookup or self.resolve_boss_asset

    def get_character_portrait(self, name_code, resource_id, costume_id: int | str | None = None) -> Image.Image:
        return self.spine.get_character_portrait(name_code, resource_id, costume_id)

    def get_lineup_portrait(
        self,
        tid: int | str | None = None,
        costume_id: int | str | None = None,
        character_id: int | str | None = None,
        avatar_id: int | str | None = None,
    ) -> Image.Image | None:
        member = tid if hasattr(tid, "tid") else None
        if member is not None:
            canonical = self.env.character_master.resolve_battle_tid(member.tid)
            if canonical is None or str(canonical.resource_id) != str(member.resource_id):
                return None
            member_costume = getattr(member, "costume_id", None)
            if self.env.character_master.is_default_costume(canonical.resource_id, member_costume):
                member_costume = None
            result = self.lineup_lookup(character_id=canonical.id, costume_id=member_costume)
            if result.is_fallback or str(result.resource_id) != str(canonical.resource_id):
                return None
        else:
            result = self.lineup_lookup(
                tid=tid, costume_id=costume_id, character_id=character_id, avatar_id=avatar_id
            )
        try:
            with Image.open(result.local_path) as image:
                return image.convert("RGBA")
        except Exception:
            return None

    def resolve_lineup_portrait(self, **kwargs):
        return self.env.lineup_resolver.resolve(**kwargs)

    def get_boss_image(self, boss_id=None, icon_id=None, monster_model_id=None, boss_name=None) -> Image.Image:
        result = self.boss_lookup(
            boss_id=boss_id, icon_id=icon_id, monster_model_id=monster_model_id, boss_name=boss_name
        )
        try:
            with Image.open(result.local_path) as image:
                return image.convert("RGBA")
        except Exception:
            return self.env.fallback("portrait")

    def resolve_boss_asset(self, **kwargs):
        return self.env.boss_resolver.resolve(**kwargs)

    def get_character_asset(self, resource_id, costume_id=None, kind: str = "fullbody") -> AssetResult:
        canonical_kind = str(kind or "").strip().lower()
        if canonical_kind not in ("icon", "portrait", "fullbody", "spine"):
            canonical_kind = "fullbody"
        resolution = self.env.visual_resolver.resolve(resource_id, costume_id=costume_id, kind=canonical_kind)
        rid_str = str(resource_id) if resource_id is not None else None
        cid_str = str(costume_id) if costume_id is not None and str(costume_id).lower() not in ("0", "default", "none", "默认", "原皮", "") else None

        if canonical_kind == "spine":
            bundle = resolution.spine_bundle
            if bundle is not None:
                return AssetResult(
                    image=None, exact_match=resolution.exact_match, fallback_reason=resolution.fallback_reason,
                    asset_key=resolution.asset_id, resource_id=rid_str, costume_id=cid_str,
                    requested_kind="spine", resolved_kind=resolution.resolved_kind,
                    source="local" if resolution.exact_match else "fallback",
                    logical_key=resolution.logical_key, bundle=bundle,
                )
            return AssetResult(
                image=None, exact_match=False, fallback_reason=resolution.fallback_reason or "spine_missing",
                asset_key=resolution.asset_id, resource_id=rid_str, costume_id=cid_str,
                requested_kind="spine", resolved_kind="spine", source="fallback", logical_key=None,
            )

        image = None
        source = "fallback"
        if resolution.logical_key:
            image = self.env.load_cached(resolution.logical_key)
            if image is not None:
                source = "cache"
            elif self.env.remote:
                if resolution.logical_key.startswith("FB/"):
                    image = self.env.load_path(
                        resolution.logical_key,
                        [f"{NIKKE_DB_IMAGES_CDN}/{resolution.logical_key.split('/')[-1]}"],
                    )
                    if image is not None:
                        source = "remote"
                elif "character/si/" in resolution.logical_key:
                    si_name = resolution.logical_key.split("/")[-1]
                    image = self.env.load_path(
                        f"character/si/{si_name}", [game_resource_url(f"character/si/{si_name}")]
                    )
                    if image is not None:
                        source = "remote"

        if image is None and canonical_kind in ("fullbody", "portrait"):
            image = self.get_character_portrait("", resource_id, costume_id)
            source = "fallback_portrait"
        elif image is None and canonical_kind == "icon":
            image = self.get_lineup_portrait(tid=resource_id, costume_id=costume_id)
            if image is not None:
                source = "fallback_icon"
        if image is None:
            image = self.env.fallback("portrait" if canonical_kind in ("fullbody", "portrait") else "slots")
            source = "fallback_placeholder"

        if not resolution.exact_match or source not in ("cache", "local", "remote"):
            logger.warning(
                "[asset][visual] resource=%s costume=%s kind=%s fallback=%s reason=%s",
                rid_str, cid_str or "default", canonical_kind, resolution.resolved_kind, resolution.fallback_reason,
            )
        else:
            logger.debug(
                "[asset][visual] resource=%s costume=%s kind=%s cache=%s",
                rid_str, cid_str or "default", canonical_kind, "hit" if source == "cache" else source,
            )
        return AssetResult(
            image=image,
            exact_match=resolution.exact_match and source in ("cache", "local", "remote"),
            fallback_reason=resolution.fallback_reason, asset_key=resolution.asset_id,
            resource_id=rid_str, costume_id=cid_str, requested_kind=canonical_kind,
            resolved_kind=resolution.resolved_kind, source=source,
            logical_key=resolution.logical_key, bundle=resolution.spine_bundle,
        )

    def get_character_icon(self, resource_id, costume_id=None) -> Image.Image:
        result = self.get_character_asset(resource_id, costume_id=costume_id, kind="icon")
        return result.image if result.image is not None else self.env.fallback("slots")

    def get_character_fullbody(self, resource_id, costume_id=None) -> Image.Image:
        result = self.get_character_asset(resource_id, costume_id=costume_id, kind="fullbody")
        return result.image if result.image is not None else self.env.fallback("portrait")

    def get_character_spine(self, resource_id, costume_id=None):
        return self.get_character_asset(resource_id, costume_id=costume_id, kind="spine").bundle

    def get_character_placement(self, resource_id, costume_id=None):
        return self.env.visual_resolver.get_character_placement(resource_id, costume_id)

    def get_costume_portrait(self, resource_id, costume_id=None) -> AssetResult:
        resolution = self.env.costume_resolver.resolve(resource_id, costume_id)
        image = self.get_character_portrait("", resource_id, costume_id)
        return AssetResult(
            image=image, exact_match=resolution.exact_match, fallback_reason=resolution.fallback_reason,
            asset_key=resolution.spine_asset_id,
            resource_id=str(resource_id) if resource_id is not None else None,
            costume_id=str(costume_id) if costume_id is not None else None,
            requested_kind="portrait", resolved_kind="portrait" if resolution.exact_match else "fallback",
        )


NIKKE_DB_IMAGES_CDN = "https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images"
