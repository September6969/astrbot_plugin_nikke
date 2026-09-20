from astrbot_plugin_nikke.character_card_layout import (
    FACE_BOTTOM_MARGIN,
    HEADER_BOTTOM,
    MIN_AUTO_SCALE_RATIO,
    clamp_top,
    core_axis_interval,
    fitted_scale,
    summary_layout,
    summary_panel_height,
)


def test_summary_layout_0_to_4_rows_is_monotonic_and_bottom_anchored():
    heights = [summary_panel_height(i) for i in range(5)]
    assert heights[0] == 0
    assert heights[1] < heights[2] < heights[3] < heights[4]

    layouts = [summary_layout(i) for i in range(5)]
    assert layouts[0].visible is False
    assert all(item.visible for item in layouts[1:])
    assert len({item.card_bottom for item in layouts}) == 1
    assert layouts[1].card_top > layouts[2].card_top > layouts[3].card_top > layouts[4].card_top
    assert layouts[0].card_top is None
    assert layouts[0].safe_bottom == layouts[0].gear_top - FACE_BOTTOM_MARGIN
    assert layouts[4].safe_top == HEADER_BOTTOM + 24.0


def test_unknown_summary_count_is_not_treated_as_zero():
    import pytest
    with pytest.raises(ValueError):
        summary_layout(None)
    with pytest.raises(ValueError):
        summary_panel_height("0")


def test_core_axis_clamp_protects_head_top_not_only_eye():
    layout = summary_layout(4)
    interval = core_axis_interval(
        scale=4.0,
        head_top_y=0.0,
        eye_y=30.0,
        breast_y=100.0,
        safe_top=layout.safe_top,
        safe_bottom=layout.safe_bottom,
    )
    assert interval.valid
    top, reason = clamp_top(300.0, interval)
    assert reason == "head_above_safe_area"
    assert top + 0.0 * 4.0 == layout.safe_top
    assert top + 30.0 * 4.0 > layout.safe_top


def test_core_axis_clamp_protects_breast_from_summary():
    layout = summary_layout(4)
    interval = core_axis_interval(
        scale=4.0,
        head_top_y=0.0,
        eye_y=30.0,
        breast_y=100.0,
        safe_top=layout.safe_top,
        safe_bottom=layout.safe_bottom,
    )
    top, reason = clamp_top(1200.0, interval)
    assert reason == "breast_below_safe_area"
    assert top + 100.0 * 4.0 == layout.safe_bottom


def test_scale_fit_is_bounded_to_six_percent():
    scale, reason = fitted_scale(
        original_scale=10.0,
        head_top_y=0.0,
        breast_y=100.0,
        safe_top=0.0,
        safe_bottom=950.0,
    )
    assert reason == "scaled_for_fit"
    assert scale == 9.5
    assert scale >= 10.0 * MIN_AUTO_SCALE_RATIO

    scale2, reason2 = fitted_scale(
        original_scale=10.0,
        head_top_y=0.0,
        breast_y=100.0,
        safe_top=0.0,
        safe_bottom=900.0,
    )
    assert scale2 is None
    assert reason2 == "scale_limited"


def test_invalid_anatomical_order_fails_closed():
    layout = summary_layout(4)
    interval = core_axis_interval(
        scale=4.0,
        head_top_y=50.0,
        eye_y=40.0,
        breast_y=100.0,
        safe_top=layout.safe_top,
        safe_bottom=layout.safe_bottom,
    )
    assert interval.valid is False
    assert interval.reason == "invalid_axis"
