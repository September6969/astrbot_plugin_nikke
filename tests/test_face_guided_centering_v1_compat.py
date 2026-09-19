"""Compatibility copy of the original eight v1 review tests.

Kept verbatim in spirit so Astra can verify that the v2 tracker fixes the new
regressions without losing the behaviour already accepted by the first review.
"""
from dataclasses import replace

from PIL import Image, ImageDraw

from astrbot_plugin_nikke.face_guided_centering import (
    CenteringConfig,
    FrameTransform,
    analyze_face_guided_silhouette,
    center_after_face_anchor,
)


def _portrait(body_box, *, size=(100, 200), weapon_box=None):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(body_box, fill=(255, 255, 255, 255))
    cx = (body_box[0] + body_box[2]) // 2
    draw.ellipse((cx - 10, 15, cx + 10, 45), fill=(255, 255, 255, 255))
    if weapon_box:
        draw.rectangle(weapon_box, fill=(255, 255, 255, 255))
    return image


def _config(**overrides):
    base = CenteringConfig(
        body_target_x=800,
        body_target_y=850,
        face_safe_left=520,
        face_safe_right=1080,
        face_safe_top=320,
        face_safe_bottom=760,
        horizontal_gain=1.0,
        vertical_gain=0.0,
        max_shift_x=160,
        max_shift_y=80,
        min_row_samples=8,
    )
    return replace(base, **overrides)


def test_centered_character_has_near_zero_horizontal_adjustment():
    image = _portrait((35, 35, 65, 185))
    face = (50, 30)
    scale = 4.0
    base = FrameTransform(scale=scale, left=800 - face[0] * scale, top=500 - face[1] * scale)
    result = center_after_face_anchor(image, face_point=face, base=base, config=_config())
    assert result.reason == "ok"
    assert abs(result.applied_shift[0]) < 3
    assert result.face_after[0] == result.face_before[0] + result.applied_shift[0]


def test_right_shifted_body_moves_left_after_face_anchor():
    image = _portrait((50, 35, 82, 185))
    face = (61, 30)
    scale = 4.0
    base = FrameTransform(scale=scale, left=860 - face[0] * scale, top=500 - face[1] * scale)
    result = center_after_face_anchor(image, face_point=face, base=base, config=_config())
    assert result.reason == "ok"
    assert result.applied_shift[0] < 0
    assert result.body_after[0] < result.body_before[0]


def test_left_shifted_body_moves_right_after_face_anchor():
    image = _portrait((18, 35, 50, 185))
    face = (39, 30)
    scale = 4.0
    base = FrameTransform(scale=scale, left=740 - face[0] * scale, top=500 - face[1] * scale)
    result = center_after_face_anchor(image, face_point=face, base=base, config=_config())
    assert result.reason == "ok"
    assert result.applied_shift[0] > 0
    assert result.body_after[0] > result.body_before[0]


def test_detached_weapon_does_not_drag_body_axis_to_weapon():
    image = _portrait((35, 35, 65, 185), weapon_box=(86, 65, 98, 170))
    face = (50, 30)
    analysis = analyze_face_guided_silhouette(image, face_point=face, config=_config())
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 5
    assert analysis.visual_center_x < 57


def test_face_safety_box_clamps_body_correction():
    image = _portrait((50, 35, 82, 185))
    face = (61, 30)
    scale = 4.0
    base = FrameTransform(scale=scale, left=525 - face[0] * scale, top=500 - face[1] * scale)
    config = _config(face_safe_left=520, max_shift_x=200)
    result = center_after_face_anchor(image, face_point=face, base=base, config=config)
    assert result.reason == "ok"
    assert result.face_after[0] >= 520 - 1e-6
    assert result.applied_shift[0] >= -5 - 1e-6
    assert result.clamped is True


def test_blank_or_nearly_blank_portrait_is_noop():
    image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    face = (50, 30)
    base = FrameTransform(scale=4, left=600, top=380)
    result = center_after_face_anchor(image, face_point=face, base=base, config=_config())
    assert result.reason == "insufficient_silhouette"
    assert result.transform == base
    assert result.analysis is None


def test_vertical_correction_is_weaker_and_bounded():
    image = _portrait((35, 20, 65, 195))
    face = (50, 30)
    base = FrameTransform(scale=6, left=500, top=300)
    config = _config(vertical_gain=0.5, max_shift_y=40)
    result = center_after_face_anchor(image, face_point=face, base=base, config=config)
    assert result.reason == "ok"
    assert abs(result.applied_shift[1]) <= 40 + 1e-6
    assert config.face_safe_top <= result.face_after[1] <= config.face_safe_bottom


def test_algorithm_is_deterministic():
    image = _portrait((42, 35, 72, 185), weapon_box=(87, 90, 97, 175))
    face = (56, 30)
    base = FrameTransform(scale=4.2, left=580, top=380)
    config = _config(horizontal_gain=0.72, vertical_gain=0.18)
    a = center_after_face_anchor(image, face_point=face, base=base, config=config)
    b = center_after_face_anchor(image, face_point=face, base=base, config=config)
    assert a == b
