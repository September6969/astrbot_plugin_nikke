# SPDX-License-Identifier: GPL-3.0-or-later
"""Character portrait cropping and framing system for Character Card T2I.

Three-tier cropping pipeline:
1. Base transparent cropping: filters low-alpha fringe/glow (alpha > 12) to obtain tight bbox.
2. Subject focusing: horizontal center-of-mass detection of upper body / head region.
3. Safe zone mapping & overflow handling: fits into 700x744 safe zone, ensures head breathing
   room (offset_y >= 14), subject prominence, and strict containment (zero rightward intrusion).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from PIL import Image

CropPolicy = Literal["standard", "large_weapon", "wide_silhouette", "tall_silhouette"]


@dataclass(frozen=True, slots=True)
class CropConfig:
    scale: float = 1.0
    offset_x: int = 0
    offset_y: int = 14
    focus_bias: float = 0.0
    crop_policy: CropPolicy = "standard"


# Presentation overrides for representative characters
CROP_OVERRIDES: dict[str, CropConfig] = {
    "c010": CropConfig(scale=1.0, offset_x=0, offset_y=14, focus_bias=0.0, crop_policy="tall_silhouette"),
    "c010_02": CropConfig(scale=1.0, offset_x=0, offset_y=14, focus_bias=0.0, crop_policy="tall_silhouette"),
    "c010_03": CropConfig(scale=1.0, offset_x=0, offset_y=14, focus_bias=0.0, crop_policy="tall_silhouette"),
    "c330": CropConfig(scale=1.0, offset_x=0, offset_y=14, focus_bias=0.2, crop_policy="large_weapon"),
    "c471": CropConfig(scale=1.0, offset_x=0, offset_y=14, focus_bias=-0.3, crop_policy="wide_silhouette"),
}


def get_alpha_bbox(image: Image.Image, threshold: int = 12) -> tuple[int, int, int, int] | None:
    """Tier 1: Extract non-transparent bounding box with an alpha threshold."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > threshold else 0)
    return mask.getbbox()


def calculate_head_center_of_mass(
    mask: Image.Image,
    bbox: tuple[int, int, int, int],
    upper_ratio: float = 0.35,
) -> float:
    """Tier 2: Calculate horizontal center of mass for the upper region (head/neck/chest)."""
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return 0.0
    head_h = max(1, int(h * upper_ratio))
    head_mask = mask.crop((bbox[0], bbox[1], bbox[2], bbox[1] + head_h))
    col_proj = head_mask.resize((w, 1), Image.Resampling.BOX).tobytes()
    total = sum(col_proj)
    if total > 0:
        return sum(x * v for x, v in enumerate(col_proj)) / total
    return w / 2.0


def infer_crop_policy(w: int, h: int, head_cx: float) -> CropPolicy:
    """Infer optimal crop policy based on silhouette aspect ratio and head offset."""
    if h <= 0:
        return "standard"
    aspect = w / h
    if aspect < 0.55:
        return "tall_silhouette"
    if aspect >= 0.80:
        if abs(head_cx / max(1, w) - 0.5) > 0.08:
            return "large_weapon"
        return "wide_silhouette"
    if aspect >= 0.68:
        return "wide_silhouette"
    return "standard"


def resolve_crop_key(
    name_code: int | str | None = None,
    resource_id: int | str | None = None,
    costume_id: int | str | None = None,
    spine_asset_id: str | None = None,
) -> str | None:
    """Resolve character / costume identifier to match CROP_OVERRIDES."""
    cid_str = str(costume_id or "")
    if cid_str in ("20001", "c010_02"):
        return "c010_02"
    if cid_str in ("10005", "c010_03"):
        return "c010_03"
    if spine_asset_id and spine_asset_id in CROP_OVERRIDES:
        return spine_asset_id

    rid_str = str(resource_id or "")
    rid_map = {"10": "c010", "330": "c330", "471": "c471"}
    if rid_str in rid_map:
        return rid_map[rid_str]

    nc_str = str(name_code or "")
    nc_map = {"3001": "c010", "5065": "c330", "5161": "c471"}
    if nc_str in nc_map:
        return nc_map[nc_str]

    try:
        from astrbot_plugin_nikke.features.character.master_resolver import CharacterMasterResolver
        cmr = CharacterMasterResolver()
        if resource_id:
            try:
                res = cmr.resolve_resource_id(int(resource_id))
                if res and res.spine_asset_id in CROP_OVERRIDES:
                    return res.spine_asset_id
            except (ValueError, TypeError):
                pass
        if name_code:
            try:
                res = cmr._by_name_code.get(int(name_code))
                if res and res.spine_asset_id in CROP_OVERRIDES:
                    return res.spine_asset_id
            except (ValueError, TypeError):
                pass
    except Exception:
        pass

    return spine_asset_id or rid_str or nc_str or None


def resolve_crop_config(
    crop_key: str | None,
    w: int,
    h: int,
    head_cx: float,
) -> CropConfig:
    """Look up crop config in manifest overrides, or infer automatically."""
    if crop_key and crop_key in CROP_OVERRIDES:
        return CROP_OVERRIDES[crop_key]
    inferred_policy = infer_crop_policy(w, h, head_cx)
    return CropConfig(crop_policy=inferred_policy)


def crop_and_fit_character_portrait(
    portrait: Image.Image,
    crop_key: str | None = None,
    canvas_size: tuple[int, int] = (700, 744),
    threshold: int = 12,
) -> Image.Image:
    """Execute full 3-tier crop pipeline and return 700x744 transparent composited portrait.

    Tier 1: Alpha threshold (> 12) bounding box crop.
    Tier 2: Calculate head / upper body center of mass.
    Tier 3: Apply crop policy, scale, head breathing room, and strict safe-zone clamping.
    """
    canvas_w, canvas_h = canvas_size
    if not isinstance(portrait, Image.Image):
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    if portrait.mode != "RGBA":
        portrait = portrait.convert("RGBA")

    # Tier 1: Base Transparent Cropping
    alpha = portrait.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    cropped = portrait.crop(bbox)
    w, h = cropped.size
    if w <= 0 or h <= 0:
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Tier 2: Subject Focusing
    head_cx = calculate_head_center_of_mass(mask, bbox)

    # Tier 3: Safe Zone Mapping & Overflow Clamping
    config = resolve_crop_config(crop_key, w, h, head_cx)
    target_top = max(0, config.offset_y)

    if config.crop_policy == "tall_silhouette":
        base_scale = ((canvas_h - target_top) / h) * 1.12
        base_focal_x = canvas_w / 2.0
    elif config.crop_policy == "large_weapon":
        base_scale = min((canvas_h - target_top) / h, (canvas_w - 20) / w) * 1.02
        base_focal_x = 370.0 if head_cx > (w * 0.5) else 330.0
    elif config.crop_policy == "wide_silhouette":
        base_scale = min((canvas_h - target_top) / h, (canvas_w - 20) / w) * 1.05
        base_focal_x = 320.0 if head_cx < (w * 0.5) else 360.0
    else:  # standard
        base_scale = min((canvas_h - target_top) / h, (canvas_w - 20) / w)
        base_focal_x = canvas_w / 2.0

    scale = max(0.01, base_scale * max(0.1, config.scale))
    scaled_w = max(1, int(round(w * scale)))
    scaled_h = max(1, int(round(h * scale)))
    scaled = cropped.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

    scaled_head_cx = head_cx * scale
    desired_focal_x = base_focal_x + (config.focus_bias * 100.0) + config.offset_x
    pos_x = int(round(desired_focal_x - scaled_head_cx))

    # Strict boundary safety: Never exceed canvas width (right safe zone barrier)
    if scaled_w <= canvas_w:
        pos_x = max(0, min(canvas_w - scaled_w, pos_x))
    else:
        pos_x = min(0, max(canvas_w - scaled_w, pos_x))

    pos_y = target_top

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    canvas.paste(scaled, (pos_x, pos_y), scaled)
    return canvas
