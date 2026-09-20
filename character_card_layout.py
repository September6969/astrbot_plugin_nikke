"""Shared 1600x2400 Character Card geometry and safe framing helpers.

This module contains only deterministic card-space math. It does not parse
Spine data or inspect runtime images.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

# Fixed card geometry inherited from the current Character Card template.
HEADER_BOTTOM = 370.0
EQUIPMENT_AREA_TOP = 1340.0
SUMMARY_BOTTOM_LOCAL = 475.0
EQUIPMENT_GRID_TOP_LOCAL = 519.0

# Dynamic summary geometry. With four rows this evaluates to 423 px, which is
# intentionally within 2 px of the old fixed 425 px panel.
SUMMARY_ROW_HEIGHT = 79.0
SUMMARY_ROW_GAP = 17.0
SUMMARY_PADDING_TOP = 28.0
SUMMARY_PADDING_BOTTOM = 28.0

# Safe corridor margins in card-space px.
FACE_TOP_MARGIN = 24.0
FACE_BOTTOM_MARGIN = 28.0
MIN_AUTO_SCALE_RATIO = 0.94


@dataclass(frozen=True)
class SummaryLayout:
    count: int
    visible: bool
    height: float
    local_top: float | None
    card_top: float | None
    card_bottom: float
    gear_top: float
    safe_top: float
    safe_bottom: float


@dataclass(frozen=True)
class CoreAxisInterval:
    valid: bool
    min_top: float | None
    max_top: float | None
    protected_span: float | None
    available_height: float
    reason: str


def _finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def normalize_summary_count(value) -> int | None:
    """Return an explicit 0..4 count; unknown input stays unknown.

    Unknown must never be silently interpreted as zero because that would
    enlarge the character safe area when the final template might still render
    a summary panel.
    """
    if type(value) is not int:
        return None
    return value if 0 <= value <= 4 else None


def summary_panel_height(count: int) -> float:
    n = normalize_summary_count(count)
    if n is None:
        raise ValueError("summary count must be an explicit integer in [0, 4]")
    if n == 0:
        return 0.0
    return (
        SUMMARY_PADDING_TOP
        + SUMMARY_PADDING_BOTTOM
        + n * SUMMARY_ROW_HEIGHT
        + (n - 1) * SUMMARY_ROW_GAP
    )


def summary_layout(count: int) -> SummaryLayout:
    n = normalize_summary_count(count)
    if n is None:
        raise ValueError("summary count must be an explicit integer in [0, 4]")

    height = summary_panel_height(n)
    card_bottom = EQUIPMENT_AREA_TOP + SUMMARY_BOTTOM_LOCAL
    gear_top = EQUIPMENT_AREA_TOP + EQUIPMENT_GRID_TOP_LOCAL
    safe_top = HEADER_BOTTOM + FACE_TOP_MARGIN

    if n:
        local_top = SUMMARY_BOTTOM_LOCAL - height
        card_top = EQUIPMENT_AREA_TOP + local_top
        safe_bottom = card_top - FACE_BOTTOM_MARGIN
    else:
        local_top = None
        card_top = None
        safe_bottom = gear_top - FACE_BOTTOM_MARGIN

    return SummaryLayout(
        count=n,
        visible=bool(n),
        height=height,
        local_top=local_top,
        card_top=card_top,
        card_bottom=card_bottom,
        gear_top=gear_top,
        safe_top=safe_top,
        safe_bottom=safe_bottom,
    )


def core_axis_interval(
    *,
    scale: float,
    head_top_y: float,
    eye_y: float,
    breast_y: float,
    safe_top: float,
    safe_bottom: float,
) -> CoreAxisInterval:
    """Return the legal `top` range for the verified head→eye→breast axis.

    The safety contract is stronger than an eye-only clamp:

        safe_top <= head_top_card <= eye_card <= breast_card <= safe_bottom

    `head_top_y`, `eye_y` and `breast_y` are portrait-space coordinates.
    """
    values = (scale, head_top_y, eye_y, breast_y, safe_top, safe_bottom)
    if not all(_finite_number(v) for v in values):
        return CoreAxisInterval(False, None, None, None, 0.0, "invalid_axis")
    if (
        scale <= 0
        or not (head_top_y <= eye_y < breast_y)
        or safe_bottom <= safe_top
    ):
        return CoreAxisInterval(
            False,
            None,
            None,
            None,
            max(0.0, safe_bottom - safe_top),
            "invalid_axis",
        )

    protected_span = (breast_y - head_top_y) * scale
    available = safe_bottom - safe_top
    min_top = safe_top - head_top_y * scale
    max_top = safe_bottom - breast_y * scale
    reason = "ok" if min_top <= max_top else "corridor_too_small"
    return CoreAxisInterval(
        True,
        min_top,
        max_top,
        protected_span,
        available,
        reason,
    )


def clamp_top(desired_top: float, interval: CoreAxisInterval) -> tuple[float, str]:
    """Clamp to a feasible interval without inventing behavior for no-solution cases."""
    if not _finite_number(desired_top) or not interval.valid:
        return desired_top, "invalid_axis"
    if interval.min_top is None or interval.max_top is None:
        return desired_top, "invalid_axis"
    if interval.min_top > interval.max_top:
        return desired_top, "corridor_too_small"
    if desired_top < interval.min_top:
        return interval.min_top, "head_above_safe_area"
    if desired_top > interval.max_top:
        return interval.max_top, "breast_below_safe_area"
    return desired_top, "already_safe"


def fitted_scale(
    *,
    original_scale: float,
    head_top_y: float,
    breast_y: float,
    safe_top: float,
    safe_bottom: float,
    min_ratio: float = MIN_AUTO_SCALE_RATIO,
) -> tuple[float | None, str]:
    """Find a scale that makes the protected head→breast span fit.

    Automatic scale-down is allowed only when the required scale is within the
    configured ratio (0.94 by default). Returning None means the caller must
    preserve the existing transform and require manual/render-specific tuning.
    """
    values = (original_scale, head_top_y, breast_y, safe_top, safe_bottom, min_ratio)
    if not all(_finite_number(v) for v in values):
        return None, "invalid_axis"
    if (
        original_scale <= 0
        or breast_y <= head_top_y
        or safe_bottom <= safe_top
        or not 0 < min_ratio <= 1
    ):
        return None, "invalid_axis"

    available = safe_bottom - safe_top
    portrait_span = breast_y - head_top_y
    required = available / portrait_span

    if required >= original_scale:
        return original_scale, "already_fits"

    lower_bound = original_scale * min_ratio
    if required < lower_bound:
        return None, "scale_limited"
    return required, "scaled_for_fit"
