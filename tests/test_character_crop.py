# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for 3-tier character portrait cropping and safe-zone containment."""

import pytest
from PIL import Image

from astrbot_plugin_nikke.character_crop import (
    CROP_OVERRIDES,
    CropConfig,
    calculate_head_center_of_mass,
    crop_and_fit_character_portrait,
    get_alpha_bbox,
    infer_crop_policy,
    resolve_crop_config,
    resolve_crop_key,
)


def test_alpha_threshold_eliminates_faint_fringe():
    """Alpha threshold > 12 filters out low-alpha fringe/glow pixels."""
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    # Low-alpha wisp / glow (alpha = 10, <= 12)
    img.putpixel((5, 5), (255, 255, 255, 10))
    img.putpixel((95, 95), (255, 255, 255, 12))
    # Solid pixels (alpha = 13 and 255)
    img.putpixel((20, 20), (255, 0, 0, 13))
    img.putpixel((80, 80), (255, 0, 0, 255))

    bbox = get_alpha_bbox(img, threshold=12)
    assert bbox == (20, 20, 81, 81)


def test_head_center_of_mass_calculation():
    """Head center of mass calculation weights upper silhouette pixels."""
    mask = Image.new("L", (100, 200), 0)
    # Put head mass on the right side of upper 35% (x in [60, 80], y in [0, 40])
    for x in range(60, 80):
        for y in range(0, 40):
            mask.putpixel((x, y), 255)

    head_cx = calculate_head_center_of_mass(mask, (0, 0, 100, 200), upper_ratio=0.35)
    assert 69.0 <= head_cx <= 70.0


def test_infer_crop_policy():
    """Aspect ratio and head offset correctly infer crop policy."""
    # Narrow aspect ratio (< 0.55) -> tall_silhouette
    assert infer_crop_policy(393, 859, 198.0) == "tall_silhouette"
    # Wide aspect ratio with asymmetrical head offset -> large_weapon
    assert infer_crop_policy(761, 853, 478.7) == "large_weapon"
    # Wide aspect ratio (> 0.68) -> wide_silhouette
    assert infer_crop_policy(586, 842, 231.4) == "wide_silhouette"
    # Balanced aspect ratio -> standard
    assert infer_crop_policy(500, 800, 250.0) == "standard"


def test_crop_overrides_manifest():
    """Representative characters are registered in CROP_OVERRIDES."""
    for key in ("c010", "c010_02", "c010_03", "c330", "c471"):
        assert key in CROP_OVERRIDES
        config = CROP_OVERRIDES[key]
        assert isinstance(config, CropConfig)
        assert config.offset_y >= 12
        assert config.crop_policy in ("tall_silhouette", "large_weapon", "wide_silhouette", "standard")


def test_resolve_crop_key():
    """Crop key resolution handles costumes, resource_ids, name_codes, and spine IDs."""
    assert resolve_crop_key(costume_id=20001) == "c010_02"
    assert resolve_crop_key(costume_id="10005") == "c010_03"
    assert resolve_crop_key(resource_id=10) == "c010"
    assert resolve_crop_key(resource_id=330) == "c330"
    assert resolve_crop_key(resource_id=471) == "c471"
    assert resolve_crop_key(name_code=3001) == "c010"
    assert resolve_crop_key(name_code=5065) == "c330"
    assert resolve_crop_key(name_code=5161) == "c471"
    assert resolve_crop_key(spine_asset_id="c330") == "c330"


def test_character_safe_zone_containment_and_dimensions():
    """Cropped output strictly conforms to 700x744 and stays within bounds."""
    for policy, size in (
        ("tall_silhouette", (400, 900)),
        ("large_weapon", (800, 900)),
        ("wide_silhouette", (700, 850)),
        ("standard", (500, 800)),
    ):
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        # Draw a solid rectangle representing the character
        for x in range(20, size[0] - 20):
            for y in range(20, size[1] - 20):
                img.putpixel((x, y), (100, 150, 200, 255))

        composited = crop_and_fit_character_portrait(img, canvas_size=(700, 744))
        assert composited.size == (700, 744)

        # Check non-transparent pixel boundaries
        alpha = composited.getchannel("A")
        bbox = alpha.point(lambda p: 255 if p > 0 else 0).getbbox()
        assert bbox is not None
        assert bbox[0] >= 0  # Left boundary >= 0
        assert bbox[2] <= 700  # Right boundary NEVER exceeds 700 (data safe zone)
        assert bbox[1] >= 14  # Top breathing room preserved


def test_edge_cases():
    """All-transparent, invalid, or empty images fall back gracefully."""
    transparent = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    res = crop_and_fit_character_portrait(transparent)
    assert res.size == (700, 744)
    assert res.getchannel("A").getbbox() is None

    # None / non-image input
    fallback = crop_and_fit_character_portrait(None)
    assert fallback.size == (700, 744)
