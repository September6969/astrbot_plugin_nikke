"""Regression tests for face-guided body-centering candidate v5."""
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw, ImageOps

from astrbot_plugin_nikke.face_guided_centering import (
    CenteringConfig,
    FrameTransform,
    _safe_delta_bounds,
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
        min_confidence_for_shift=0.25,
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


def test_detached_side_weapon_does_not_drag_body_axis():
    image = _portrait((35, 35, 65, 185), weapon_box=(86, 65, 98, 170))
    analysis = analyze_face_guided_silhouette(image, face_point=(50, 30), config=_config())

    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 4
    assert abs(analysis.visual_center_x - 50) < 4


def test_detached_long_weapon_below_body_stops_tracking_instead_of_takeover():
    image = Image.new("RGBA", (150, 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((38, 35, 62, 132), fill="white")  # body ends early
    draw.rectangle((108, 70, 124, 215), fill="white")  # detached weapon continues below body

    config = _config(max_shift_x=140)
    analysis = analyze_face_guided_silhouette(image, face_point=(50, 28), config=config)
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 4
    assert analysis.terminated_early is True
    assert analysis.confidence < 1.0

    base = FrameTransform(scale=4.0, left=800 - 50 * 4, top=500 - 28 * 4)
    result = center_after_face_anchor(image, face_point=(50, 28), base=base, config=config)
    assert abs(result.applied_shift[0]) < 20
    assert abs(result.applied_shift[0]) < config.max_shift_x


def test_symmetric_split_legs_keep_shared_midline():
    image = Image.new("RGBA", (100, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 105), fill="white")
    draw.rectangle((28, 105, 43, 195), fill="white")
    draw.rectangle((57, 105, 72, 195), fill="white")

    analysis = analyze_face_guided_silhouette(image, face_point=(50, 28), config=_config())
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 2.0

    base = FrameTransform(scale=4.0, left=800 - 50 * 4, top=500 - 28 * 4)
    result = center_after_face_anchor(image, face_point=(50, 28), base=base, config=_config())
    assert abs(result.applied_shift[0]) < 5


def test_mirror_consistency_and_symmetric_zero():
    image = Image.new("RGBA", (120, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((34, 10, 54, 40), fill="white")
    draw.rectangle((36, 35, 62, 110), fill="white")
    draw.rectangle((28, 110, 44, 195), fill="white")
    draw.rectangle((53, 110, 68, 195), fill="white")

    mirrored = ImageOps.mirror(image)
    face = (44, 28)
    mirror_face = (image.width - 1 - face[0], face[1])
    cfg = _config(body_target_x=800)
    scale = 4.0
    base_a = FrameTransform(scale=scale, left=800 - face[0] * scale, top=500 - face[1] * scale)
    base_b = FrameTransform(scale=scale, left=800 - mirror_face[0] * scale, top=500 - mirror_face[1] * scale)

    a = center_after_face_anchor(image, face_point=face, base=base_a, config=cfg)
    b = center_after_face_anchor(mirrored, face_point=mirror_face, base=base_b, config=cfg)

    assert a.reason == b.reason == "ok"
    assert a.applied_shift[0] == pytest.approx(-b.applied_shift[0], abs=2.0)


def test_connected_weapon_width_growth_does_not_recenter_on_run_midpoint():
    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 195), fill="white")
    # Connected right-side attachment: rows 70..145 become one huge interval.
    draw.rectangle((60, 70, 118, 145), fill="white")

    analysis = analyze_face_guided_silhouette(image, face_point=(50, 28), config=_config())
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 6
    assert analysis.width_reliability < 1.0

    base = FrameTransform(scale=4.0, left=800 - 50 * 4, top=500 - 28 * 4)
    result = center_after_face_anchor(image, face_point=(50, 28), base=base, config=_config())
    assert abs(result.applied_shift[0]) < 30


def test_default_phase_one_disables_vertical_correction():
    image = _portrait((35, 20, 65, 195))
    face = (50, 30)
    base = FrameTransform(scale=6, left=500, top=300)

    result = center_after_face_anchor(image, face_point=face, base=base, config=_config())

    assert result.reason == "ok"
    assert result.applied_shift[1] == pytest.approx(0.0)
    assert result.transform.top == pytest.approx(base.top)


def test_vertical_correction_can_still_be_opted_in_and_is_bounded():
    image = _portrait((35, 20, 65, 195))
    face = (50, 30)
    base = FrameTransform(scale=6, left=500, top=300)
    config = _config(vertical_gain=0.5, max_shift_y=40)

    result = center_after_face_anchor(image, face_point=face, base=base, config=config)

    assert result.reason == "ok"
    assert abs(result.applied_shift[1]) <= 40 + 1e-6
    assert config.face_safe_top <= result.face_after[1] <= config.face_safe_bottom


@pytest.mark.parametrize(
    "current,safe_min,safe_max,max_shift,expected",
    [
        (525, 520, 1080, 200, (-5, 200)),      # near left edge
        (1075, 520, 1080, 200, (-200, 5)),     # near right edge
        (325, 320, 760, 80, (-5, 80)),         # near top edge
        (755, 320, 760, 80, (-80, 5)),         # near bottom edge
        (500, 520, 1080, 200, (0, 200)),       # already outside left
        (1100, 520, 1080, 200, (-200, 0)),     # already outside right
        (300, 320, 760, 80, (0, 80)),          # already outside top
        (780, 320, 760, 80, (-80, 0)),         # already outside bottom
    ],
)
def test_face_safety_delta_bounds_cover_all_edges_and_outside_cases(
    current, safe_min, safe_max, max_shift, expected
):
    assert _safe_delta_bounds(current, safe_min, safe_max, max_shift) == expected


def test_face_safety_functionally_clamps_leftward_correction():
    image = _portrait((50, 35, 82, 185))
    face = (61, 30)
    scale = 4.0
    base = FrameTransform(scale=scale, left=525 - face[0] * scale, top=500 - face[1] * scale)
    config = _config(body_target_x=0, face_safe_left=520, max_shift_x=200)

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


def test_algorithm_is_deterministic():
    image = _portrait((42, 35, 72, 185), weapon_box=(87, 90, 97, 175))
    face = (56, 30)
    base = FrameTransform(scale=4.2, left=580, top=380)
    config = _config(horizontal_gain=0.72)

    a = center_after_face_anchor(image, face_point=face, base=base, config=config)
    b = center_after_face_anchor(image, face_point=face, base=base, config=config)

    assert a == b


def test_default_config_long_connected_attachment_cannot_accumulate_drift():
    """A long connected prop must not turn many clipped rows into a large shift."""
    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 195), fill="white")
    # Same connected-weapon shape as the v2 test, extended through y=195.
    draw.rectangle((60, 70, 118, 195), fill="white")

    config = CenteringConfig()  # IMPORTANT: production/default threshold (0.45)
    analysis = analyze_face_guided_silhouette(image, face_point=(50, 28), config=config)
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 3
    assert analysis.max_untrusted_span > 0
    assert analysis.terminated_early is True

    base = FrameTransform(scale=4.0, left=800 - 50 * 4, top=500 - 28 * 4)
    result = center_after_face_anchor(image, face_point=(50, 28), base=base, config=config)
    assert abs(result.applied_shift[0]) < 5
    # This adversarial case is intentionally allowed to fail closed.
    assert result.reason in {"ok", "low_confidence"}


def test_default_config_is_invariant_to_transparent_canvas_padding():
    """Transparent export padding must be a coordinate translation, nothing more."""
    image = Image.new("RGBA", (120, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((46, 10, 66, 40), fill="white")
    draw.rectangle((44, 35, 72, 195), fill="white")
    draw.rectangle((72, 75, 104, 130), fill="white")

    face = (56, 28)
    scale = 4.0
    base = FrameTransform(scale=scale, left=840 - face[0] * scale, top=500 - face[1] * scale)
    original = center_after_face_anchor(image, face_point=face, base=base, config=CenteringConfig())

    # Add 100px transparent padding on all four sides.  Adjust source face and
    # base offset so the initial final-card rendering is pixel-identical.
    padded = Image.new("RGBA", (320, 410), (0, 0, 0, 0))
    padded.alpha_composite(image, (100, 100))
    padded_face = (face[0] + 100, face[1] + 100)
    padded_base = FrameTransform(
        scale=scale,
        left=base.left - 100 * scale,
        top=base.top - 100 * scale,
    )
    expanded = center_after_face_anchor(
        padded, face_point=padded_face, base=padded_base, config=CenteringConfig()
    )

    assert original.reason == expanded.reason
    assert original.applied_shift == pytest.approx(expanded.applied_shift, abs=1e-6)
    assert original.analysis is not None and expanded.analysis is not None
    assert original.analysis.bootstrap_width == pytest.approx(expanded.analysis.bootstrap_width)
    assert expanded.analysis.body_axis_x - original.analysis.body_axis_x == pytest.approx(100.0)
    assert expanded.analysis.confidence == pytest.approx(original.analysis.confidence, abs=1e-12)


def test_default_config_long_transparent_vertical_gap_terminates_subject_path():
    """A lower detached prop after a large empty gap cannot restart the body path."""
    image = Image.new("RGBA", (130, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((38, 35, 62, 105), fill="white")
    # >100 transparent rows before a later, horizontally-near detached object.
    draw.rectangle((68, 210, 88, 290), fill="white")

    config = CenteringConfig()  # no relaxed test threshold
    analysis = analyze_face_guided_silhouette(image, face_point=(50, 28), config=config)
    assert analysis is not None
    assert abs(analysis.body_axis_x - 50) < 3
    assert analysis.terminated_early is True
    assert analysis.max_vertical_gap > 0
    assert analysis.path_coverage < 0.9

    base = FrameTransform(scale=4.0, left=800 - 50 * 4, top=500 - 28 * 4)
    result = center_after_face_anchor(image, face_point=(50, 28), base=base, config=config)
    assert abs(result.applied_shift[0]) < 5


def _connected_attachment_case(start_y: int | None):
    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 195), fill="white")
    if start_y is not None:
        draw.rectangle((60, start_y, 118, 195), fill="white")
    return image


@pytest.mark.parametrize("start_y", [20, 40, 70])
def test_default_config_bootstrap_resists_connected_attachment_start_position(start_y):
    """Attachment timing around the bootstrap band must not redefine body scale."""
    image = _connected_attachment_case(start_y)
    face = (50, 28)
    config = CenteringConfig()
    analysis = analyze_face_guided_silhouette(image, face_point=face, config=config)

    assert analysis is not None
    # If the attachment already occupies the face-local bootstrap band there is
    # no independent clean scale evidence; v5 deliberately fails closed.  Later
    # attachment starts still retain the clean face/neck seed.
    assert analysis.bootstrap_reliable is (start_y != 20)
    assert analysis.bootstrap_width == pytest.approx(21.0, abs=3.0)
    assert abs(analysis.body_axis_x - 50.0) < 5.0

    base = FrameTransform(
        scale=4.0,
        left=config.body_target_x - face[0] * 4.0,
        top=500 - face[1] * 4.0,
    )
    result = center_after_face_anchor(image, face_point=face, base=base, config=config)
    # Whether it passes confidence or falls back, it must preserve the already
    # centered face-first composition rather than follow the connected prop.
    assert abs(result.applied_shift[0]) < 20.0


def test_default_config_bootstrap_matches_clean_body_scale_with_early_attachment():
    clean = _connected_attachment_case(None)
    early = _connected_attachment_case(40)
    face = (50, 28)
    cfg = CenteringConfig()

    a = analyze_face_guided_silhouette(clean, face_point=face, config=cfg)
    b = analyze_face_guided_silhouette(early, face_point=face, config=cfg)

    assert a is not None and b is not None
    assert a.bootstrap_width == pytest.approx(b.bootstrap_width, abs=2.0)
    assert a.body_axis_x == pytest.approx(b.body_axis_x, abs=4.0)


def test_default_config_ambiguous_bootstrap_width_groups_fall_back():
    """Two incompatible face-local width groups must not produce a trusted shift."""
    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Stable body below the bootstrap area.
    draw.rectangle((40, 50, 60, 195), fill="white")
    # Around the face, alternate two symmetric width groups.  Because both are
    # centred on the face, one-sided-core protection cannot decide which width
    # is anatomy; bootstrap should therefore declare the seed ambiguous.
    for y in range(20, 45):
        if y % 2:
            draw.line((40, y, 60, y), fill="white")
        else:
            draw.line((20, y, 80, y), fill="white")

    face = (50, 28)
    cfg = CenteringConfig()
    analysis = analyze_face_guided_silhouette(image, face_point=face, config=cfg)

    assert analysis is not None
    assert analysis.bootstrap_reliable is False
    assert analysis.confidence < cfg.min_confidence_for_shift

    base = FrameTransform(scale=4.0, left=800 - 50 * 4.0, top=500 - 28 * 4.0)
    result = center_after_face_anchor(image, face_point=face, base=base, config=cfg)
    assert result.reason == "low_confidence"
    assert result.applied_shift == (0.0, 0.0)


def _early_connected_attachment_width_case(end_x: int, *, start_y: int = 20):
    image = Image.new("RGBA", (140, 210), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 10, 60, 40), fill="white")
    draw.rectangle((40, 35, 60, 195), fill="white")
    draw.rectangle((60, start_y, end_x, 195), fill="white")
    return image


@pytest.mark.parametrize("end_x", [72, 73, 75, 80, 118])
def test_default_config_medium_early_one_sided_growth_fails_closed(end_x):
    """Width below the old 2.25x cutoff must not receive full bootstrap trust.

    These cases reproduce the fourth Astra review: the attachment begins before
    the face-local seed is established.  There is no independent clean neck/face
    evidence, so the safe behaviour is to preserve the existing face framing.
    """
    image = _early_connected_attachment_width_case(end_x)
    face = (50, 28)
    cfg = CenteringConfig()  # IMPORTANT: default production candidate config
    analysis = analyze_face_guided_silhouette(image, face_point=face, config=cfg)

    assert analysis is not None
    assert analysis.bootstrap_reliable is False
    assert analysis.bootstrap_clean_rows < cfg.bootstrap_min_clean_rows
    assert analysis.bootstrap_half_balance < cfg.bootstrap_min_half_balance
    assert analysis.confidence < cfg.min_confidence_for_shift

    base = FrameTransform(scale=4.0, left=cfg.body_target_x - 50 * 4.0, top=500 - 28 * 4.0)
    result = center_after_face_anchor(image, face_point=face, base=base, config=cfg)
    assert result.reason == "low_confidence"
    assert result.applied_shift == (0.0, 0.0)


@pytest.mark.parametrize("end_x", [68, 70, 71])
@pytest.mark.parametrize("scale", [4.0, 8.0, 12.0])
def test_default_config_borderline_one_sided_growth_obeys_only_global_card_safety(end_x, scale):
    """Document the remaining ambiguity without inventing a scale-independent cap.

    Astra round 5 showed that the x=68..71 ambiguity band can keep high
    confidence while the final-card correction grows with portrait scale.  The
    candidate currently promises only the existing global shift clamp and face
    safety box here.  Real-art preview evidence must decide whether a dedicated
    final-card ambiguity cap is useful before default enablement.
    """
    image = _early_connected_attachment_width_case(end_x)
    face = (50, 28)
    cfg = CenteringConfig()
    face_card_x = 800.0
    face_card_y = 500.0
    base = FrameTransform(
        scale=scale,
        left=face_card_x - face[0] * scale,
        top=face_card_y - face[1] * scale,
    )
    result = center_after_face_anchor(image, face_point=face, base=base, config=cfg)

    assert abs(result.applied_shift[0]) <= cfg.max_shift_x + 1e-6
    assert result.applied_shift[1] == 0.0
    assert cfg.face_safe_left <= result.face_after[0] <= cfg.face_safe_right


def test_default_config_offcentre_face_anchor_can_use_lower_clean_neck_evidence():
    """Half-width balance must not reject every legitimate off-centre face anchor."""
    image = _portrait((50, 35, 82, 185))
    face = (61, 30)  # deliberately left of the silhouette midpoint
    cfg = CenteringConfig()
    analysis = analyze_face_guided_silhouette(image, face_point=face, config=cfg)

    assert analysis is not None
    assert analysis.bootstrap_reliable is True
    assert analysis.bootstrap_clean_rows >= cfg.bootstrap_min_clean_rows
    assert analysis.bootstrap_width == pytest.approx(33.0, abs=2.0)


def test_default_config_early_one_sided_growth_is_mirror_safe():
    """Fail-closed bootstrap must not prefer left- versus right-side attachments."""
    image = _early_connected_attachment_width_case(75)
    mirrored = ImageOps.mirror(image)
    cfg = CenteringConfig()
    face = (50, 28)
    mirror_face = (image.width - 1 - face[0], face[1])

    a = analyze_face_guided_silhouette(image, face_point=face, config=cfg)
    b = analyze_face_guided_silhouette(mirrored, face_point=mirror_face, config=cfg)
    assert a is not None and b is not None
    assert a.bootstrap_reliable is b.bootstrap_reliable is False

    base_a = FrameTransform(scale=4.0, left=cfg.body_target_x - face[0] * 4.0, top=500 - 28 * 4.0)
    base_b = FrameTransform(scale=4.0, left=cfg.body_target_x - mirror_face[0] * 4.0, top=500 - 28 * 4.0)
    ra = center_after_face_anchor(image, face_point=face, base=base_a, config=cfg)
    rb = center_after_face_anchor(mirrored, face_point=mirror_face, base=base_b, config=cfg)
    assert ra.applied_shift == rb.applied_shift == (0.0, 0.0)

