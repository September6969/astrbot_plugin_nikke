# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 统一角色视觉资产解析器 (CharacterVisualAssetResolver)。

实现全量视觉资源分类：
- icon: 小尺寸正方形头像 (si_cXXX_YY_s.webp)
- portrait: 半身像 / 预渲染头像
- fullbody: 站姿大立绘 (Nikke-db FB / 预渲染大图)
- spine: 骨骼动画组合包 (skeleton + atlas + textures)

遵循严格语义契约：
- 显式区分 exact_match 与 fallback
- 记录 requested_kind 与 resolved_kind
- 精确区分 unknown_costume, costume_owner_mismatch, costume_fullbody_missing 等降级状态
- 绝不因默认角色有资源而将皮肤降级谎报为 exact match
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any

try:
    from .card_models import SpineBundle
except ImportError:
    from card_models import SpineBundle

logger = logging.getLogger("nikke.visual_resolver")


@dataclass(slots=True)
class VisualAssetResolution:
    """角色视觉资产解析结果契约。"""

    resource_id: str | None
    character_id: str | None
    costume_id: str | None
    character_name: str
    costume_name: str | None

    requested_kind: str
    resolved_kind: str
    exact_match: bool
    fallback_reason: str | None

    logical_key: str | None = None
    asset_id: str | None = None
    spine_bundle: SpineBundle | None = None
    is_default: bool = False


class CharacterVisualAssetResolver:
    """角色视觉资产逻辑解析器。"""

    RESET_TERMS = {"默认", "default", "原皮", "0", "none", "null", ""}
    SUPPORTED_KINDS = {"icon", "portrait", "fullbody", "spine"}

    def __init__(
        self,
        visual_catalog_path: str | Path | None = None,
        spine_metadata_path: str | Path | None = None,
        placement_meta_path: str | Path | None = None,
    ):
        base = Path(__file__).resolve().parent
        if visual_catalog_path is None:
            self.visual_catalog_path = base / "assets" / "mappings" / "costume_visual_assets.json"
        else:
            self.visual_catalog_path = Path(visual_catalog_path).resolve()

        if spine_metadata_path is None:
            self.spine_metadata_path = base / "assets" / "mappings" / "spine_metadata.json"
        else:
            self.spine_metadata_path = Path(spine_metadata_path).resolve()

        if placement_meta_path is None:
            self.placement_meta_path = base / "assets" / "mappings" / "character_placement_meta.json"
        else:
            self.placement_meta_path = Path(placement_meta_path).resolve()

        self._characters: dict[str, dict[str, Any]] = {}
        self._all_costumes: dict[str, tuple[str, dict[str, Any]]] = {}  # costume_id -> (owner_rid, costume_data)
        self._spine_entries: dict[str, dict[str, Any]] = {}
        self._placement_entries: dict[str, dict[str, Any]] = {}

        self._load()

    def _load(self) -> None:
        # 1. 加载角色与服装视觉 catalog
        if self.visual_catalog_path.is_file():
            try:
                data = json.loads(self.visual_catalog_path.read_text(encoding="utf-8"))
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
                logger.warning("Failed to load visual catalog from %s: %s", self.visual_catalog_path, exc)

        # 2. 加载 Spine 元数据
        if self.spine_metadata_path.is_file():
            try:
                s_data = json.loads(self.spine_metadata_path.read_text(encoding="utf-8"))
                if isinstance(s_data, dict):
                    entries = s_data.get("entries", {})
                    if isinstance(entries, dict):
                        self._spine_entries = entries
            except Exception as exc:
                logger.warning("Failed to load spine metadata from %s: %s", self.spine_metadata_path, exc)

        # 3. 加载角色 Placement 元数据
        if self.placement_meta_path.is_file():
            try:
                p_data = json.loads(self.placement_meta_path.read_text(encoding="utf-8"))
                if isinstance(p_data, dict):
                    p_entries = p_data.get("entries", {})
                    if isinstance(p_entries, dict):
                        self._placement_entries = p_entries
            except Exception as exc:
                logger.warning("Failed to load placement metadata from %s: %s", self.placement_meta_path, exc)

    @property
    def total_characters(self) -> int:
        return len(self._characters)

    @property
    def total_costumes(self) -> int:
        return len(self._all_costumes)

    def _build_spine_bundle(self, spine_dict: dict | None, entry_key: str | None = None) -> SpineBundle | None:
        if not spine_dict:
            return None
        skel = spine_dict.get("skeleton")
        atlas = spine_dict.get("atlas")
        textures = spine_dict.get("textures", [])
        fmt = "skel" if (skel and str(skel).endswith(".skel")) else ("json" if (skel and str(skel).endswith(".json")) else None)

        bones = None
        slots = None
        if entry_key and entry_key in self._spine_entries:
            s_entry = self._spine_entries[entry_key]
            bones = s_entry.get("bones")
            slots = s_entry.get("slots")

        return SpineBundle(
            skeleton=skel,
            atlas=atlas,
            textures=textures,
            format=fmt,
            bone_names=bones,
            slot_names=slots,
        )

    def resolve(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
        kind: str = "fullbody",
    ) -> VisualAssetResolution:
        """根据角色 resource_id、costume_id 与期望类型解析视觉资源。"""
        canonical_kind = str(kind or "").strip().lower()
        if canonical_kind not in self.SUPPORTED_KINDS:
            canonical_kind = "fullbody"

        rid_str = str(resource_id).strip() if (resource_id is not None and not isinstance(resource_id, bool)) else None
        char_entry = self._characters.get(rid_str or "") if rid_str else None

        # 归一化 costume_id
        if costume_id is None or isinstance(costume_id, bool):
            is_default = True
            cid_str = None
        else:
            cid_str = str(costume_id).strip()
            is_default = cid_str.lower() in self.RESET_TERMS

        char_name = char_entry.get("name_cn") or char_entry.get("name_en") or "" if char_entry else ""
        cid_resolved = str(char_entry.get("character_id", "")) if char_entry else None

        # 1. 角色未登记
        if char_entry is None:
            return VisualAssetResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=cid_str if not is_default else None,
                character_name=char_name,
                costume_name=None,
                requested_kind=canonical_kind,
                resolved_kind=canonical_kind,
                exact_match=False,
                fallback_reason="unknown_character",
                logical_key=None,
                asset_id=None,
                spine_bundle=None,
                is_default=is_default,
            )

        default_assets = char_entry.get("default", {})
        default_spine_id = default_assets.get("spine_asset_id", f"c{int(rid_str):03d}" if (rid_str and rid_str.isdigit()) else None)

        # 2. 请求皮肤 (非默认)
        if not is_default:
            costumes_map = char_entry.get("costumes", {})

            # 2a. 该皮肤不存在于任何角色 -> unknown_costume
            if cid_str not in self._all_costumes:
                res = self.resolve(resource_id, costume_id=None, kind=canonical_kind)
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=None,
                    requested_kind=canonical_kind,
                    resolved_kind=res.resolved_kind,
                    exact_match=False,
                    fallback_reason="unknown_costume",
                    logical_key=res.logical_key,
                    asset_id=res.asset_id,
                    spine_bundle=res.spine_bundle,
                    is_default=False,
                )

            # 2b. 该皮肤属于其他角色 -> costume_owner_mismatch
            if cid_str not in costumes_map:
                res = self.resolve(resource_id, costume_id=None, kind=canonical_kind)
                other_owner, other_info = self._all_costumes[cid_str]
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=other_info.get("costume_name"),
                    requested_kind=canonical_kind,
                    resolved_kind=res.resolved_kind,
                    exact_match=False,
                    fallback_reason="costume_owner_mismatch",
                    logical_key=res.logical_key,
                    asset_id=res.asset_id,
                    spine_bundle=res.spine_bundle,
                    is_default=False,
                )

            # 2c. 皮肤正确匹配该角色
            costume_info = costumes_map[cid_str]
            c_name = costume_info.get("costume_name")
            c_spine_aid = costume_info.get("spine_asset_id")

            if canonical_kind == "fullbody":
                # 优先级：costume FB -> costume 预渲染 -> costume Spine -> 角色默认 FB -> 角色默认 portrait -> 角色 icon -> 通用占位
                if costume_info.get("fullbody"):
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="fullbody",
                        resolved_kind="fullbody",
                        exact_match=True,
                        fallback_reason=None,
                        logical_key=costume_info.get("fullbody"),
                        asset_id=c_spine_aid,
                        spine_bundle=None,
                        is_default=False,
                    )
                # 缺失 costume fullbody，执行降级但绝不标为 exact match
                if costume_info.get("portrait"):
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="fullbody",
                        resolved_kind="portrait",
                        exact_match=False,
                        fallback_reason="costume_fullbody_missing",
                        logical_key=costume_info.get("portrait"),
                        asset_id=c_spine_aid,
                        spine_bundle=None,
                        is_default=False,
                    )
                if costume_info.get("spine"):
                    bundle = self._build_spine_bundle(costume_info.get("spine"), f"{rid_str}:{cid_str}")
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="fullbody",
                        resolved_kind="spine",
                        exact_match=False,
                        fallback_reason="costume_fullbody_missing",
                        logical_key=costume_info["spine"].get("skeleton"),
                        asset_id=c_spine_aid,
                        spine_bundle=bundle,
                        is_default=False,
                    )
                # 降级到默认角色 fullbody
                def_res = self.resolve(resource_id, costume_id=None, kind="fullbody")
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=c_name,
                    requested_kind="fullbody",
                    resolved_kind=def_res.resolved_kind,
                    exact_match=False,
                    fallback_reason="costume_fullbody_missing",
                    logical_key=def_res.logical_key,
                    asset_id=def_res.asset_id,
                    spine_bundle=def_res.spine_bundle,
                    is_default=False,
                )

            elif canonical_kind == "portrait":
                if costume_info.get("portrait"):
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="portrait",
                        resolved_kind="portrait",
                        exact_match=True,
                        fallback_reason=None,
                        logical_key=costume_info.get("portrait"),
                        asset_id=c_spine_aid,
                        spine_bundle=None,
                        is_default=False,
                    )
                # 降级到默认 portrait
                def_res = self.resolve(resource_id, costume_id=None, kind="portrait")
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=c_name,
                    requested_kind="portrait",
                    resolved_kind=def_res.resolved_kind,
                    exact_match=False,
                    fallback_reason="costume_portrait_missing",
                    logical_key=def_res.logical_key,
                    asset_id=def_res.asset_id,
                    spine_bundle=def_res.spine_bundle,
                    is_default=False,
                )

            elif canonical_kind == "icon":
                if costume_info.get("icon"):
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="icon",
                        resolved_kind="icon",
                        exact_match=True,
                        fallback_reason=None,
                        logical_key=costume_info.get("icon"),
                        asset_id=c_spine_aid,
                        spine_bundle=None,
                        is_default=False,
                    )
                def_res = self.resolve(resource_id, costume_id=None, kind="icon")
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=c_name,
                    requested_kind="icon",
                    resolved_kind=def_res.resolved_kind,
                    exact_match=False,
                    fallback_reason="costume_icon_missing",
                    logical_key=def_res.logical_key,
                    asset_id=def_res.asset_id,
                    spine_bundle=def_res.spine_bundle,
                    is_default=False,
                )

            elif canonical_kind == "spine":
                if costume_info.get("spine"):
                    bundle = self._build_spine_bundle(costume_info.get("spine"), f"{rid_str}:{cid_str}")
                    return VisualAssetResolution(
                        resource_id=rid_str,
                        character_id=cid_resolved,
                        costume_id=cid_str,
                        character_name=char_name,
                        costume_name=c_name,
                        requested_kind="spine",
                        resolved_kind="spine",
                        exact_match=True,
                        fallback_reason=None,
                        logical_key=costume_info["spine"].get("skeleton"),
                        asset_id=c_spine_aid,
                        spine_bundle=bundle,
                        is_default=False,
                    )
                def_res = self.resolve(resource_id, costume_id=None, kind="spine")
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=cid_str,
                    character_name=char_name,
                    costume_name=c_name,
                    requested_kind="spine",
                    resolved_kind=def_res.resolved_kind,
                    exact_match=False,
                    fallback_reason="costume_spine_missing",
                    logical_key=def_res.logical_key,
                    asset_id=def_res.asset_id,
                    spine_bundle=def_res.spine_bundle,
                    is_default=False,
                )

        # 3. 请求默认原皮
        if canonical_kind == "fullbody":
            if default_assets.get("fullbody"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="fullbody",
                    resolved_kind="fullbody",
                    exact_match=True,
                    fallback_reason=None,
                    logical_key=default_assets.get("fullbody"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            # 默认角色无 fullbody，降级到 portrait -> icon -> fallback
            if default_assets.get("portrait"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="fullbody",
                    resolved_kind="portrait",
                    exact_match=False,
                    fallback_reason="fullbody_missing",
                    logical_key=default_assets.get("portrait"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            if default_assets.get("icon"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="fullbody",
                    resolved_kind="icon",
                    exact_match=False,
                    fallback_reason="fullbody_missing",
                    logical_key=default_assets.get("icon"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            return VisualAssetResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=None,
                character_name=char_name,
                costume_name="默认皮肤",
                requested_kind="fullbody",
                resolved_kind="generic",
                exact_match=False,
                fallback_reason="fullbody_missing",
                logical_key=None,
                asset_id=default_spine_id,
                spine_bundle=None,
                is_default=True,
            )

        elif canonical_kind == "portrait":
            if default_assets.get("portrait"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="portrait",
                    resolved_kind="portrait",
                    exact_match=True,
                    fallback_reason=None,
                    logical_key=default_assets.get("portrait"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            if default_assets.get("icon"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="portrait",
                    resolved_kind="icon",
                    exact_match=False,
                    fallback_reason="portrait_missing",
                    logical_key=default_assets.get("icon"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            return VisualAssetResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=None,
                character_name=char_name,
                costume_name="默认皮肤",
                requested_kind="portrait",
                resolved_kind="generic",
                exact_match=False,
                fallback_reason="portrait_missing",
                logical_key=None,
                asset_id=default_spine_id,
                spine_bundle=None,
                is_default=True,
            )

        elif canonical_kind == "icon":
            if default_assets.get("icon"):
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="icon",
                    resolved_kind="icon",
                    exact_match=True,
                    fallback_reason=None,
                    logical_key=default_assets.get("icon"),
                    asset_id=default_spine_id,
                    spine_bundle=None,
                    is_default=True,
                )
            return VisualAssetResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=None,
                character_name=char_name,
                costume_name="默认皮肤",
                requested_kind="icon",
                resolved_kind="generic",
                exact_match=False,
                fallback_reason="icon_missing",
                logical_key=None,
                asset_id=default_spine_id,
                spine_bundle=None,
                is_default=True,
            )

        elif canonical_kind == "spine":
            if default_assets.get("spine"):
                bundle = self._build_spine_bundle(default_assets.get("spine"), f"{rid_str}:default")
                return VisualAssetResolution(
                    resource_id=rid_str,
                    character_id=cid_resolved,
                    costume_id=None,
                    character_name=char_name,
                    costume_name="默认皮肤",
                    requested_kind="spine",
                    resolved_kind="spine",
                    exact_match=True,
                    fallback_reason=None,
                    logical_key=default_assets["spine"].get("skeleton"),
                    asset_id=default_spine_id,
                    spine_bundle=bundle,
                    is_default=True,
                )
            return VisualAssetResolution(
                resource_id=rid_str,
                character_id=cid_resolved,
                costume_id=None,
                character_name=char_name,
                costume_name="默认皮肤",
                requested_kind="spine",
                resolved_kind="spine",
                exact_match=False,
                fallback_reason="spine_missing",
                logical_key=None,
                asset_id=default_spine_id,
                spine_bundle=None,
                is_default=True,
            )

        return VisualAssetResolution(
            resource_id=rid_str,
            character_id=cid_resolved,
            costume_id=None,
            character_name=char_name,
            costume_name="默认皮肤",
            requested_kind=canonical_kind,
            resolved_kind="generic",
            exact_match=False,
            fallback_reason="unknown_kind",
            logical_key=None,
            asset_id=default_spine_id,
            spine_bundle=None,
            is_default=True,
        )

    def get_character_placement(
        self,
        resource_id: str | int | None,
        costume_id: str | int | None = None,
    ) -> dict[str, Any] | None:
        """查询角色或皮肤的标准 Placement Metadata (CharacterPlacementMeta)。"""
        if resource_id is None or isinstance(resource_id, bool):
            return None
        rid_str = str(resource_id).strip()
        if not rid_str:
            return None

        # 若指定了皮肤，优先查询皮肤的定位数据
        if costume_id is not None and not isinstance(costume_id, bool):
            cid_str = str(costume_id).strip()
            if cid_str and cid_str not in ("0", "default"):
                costume_key = f"{rid_str}:{cid_str}"
                if costume_key in self._placement_entries:
                    return self._placement_entries[costume_key]

        # 查询默认皮肤的定位数据
        default_key = f"{rid_str}:default"
        return self._placement_entries.get(default_key)

