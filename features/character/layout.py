"""角色练度卡的确定性布局与安全构图计算。"""
from __future__ import annotations

from dataclasses import dataclass
import math


# 沿用当前 1600×2400 角色卡模板的固定几何边界。
HEADER_BOTTOM = 370.0
EQUIPMENT_AREA_TOP = 1340.0
SUMMARY_BOTTOM_LOCAL = 475.0
EQUIPMENT_GRID_TOP_LOCAL = 519.0

# 摘要行的动态布局参数；四行时约为旧版固定 425px 的面板高度。
SUMMARY_ROW_HEIGHT = 79.0
SUMMARY_ROW_GAP = 17.0
SUMMARY_PADDING_TOP = 28.0
SUMMARY_PADDING_BOTTOM = 28.0

# 头顶到胸部的安全走廊边距。
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
    """只接受明确的 0～4 行；未知值不能静默当作零行。"""
    if type(value) is not int:
        return None
    return value if 0 <= value <= 4 else None


def summary_panel_height(count: int) -> float:
    """按实际摘要行数计算面板高度。"""
    normalized = normalize_summary_count(count)
    if normalized is None:
        raise ValueError("summary count must be an explicit integer in [0, 4]")
    if normalized == 0:
        return 0.0
    return (
        SUMMARY_PADDING_TOP
        + SUMMARY_PADDING_BOTTOM
        + normalized * SUMMARY_ROW_HEIGHT
        + (normalized - 1) * SUMMARY_ROW_GAP
    )


def summary_layout(count: int) -> SummaryLayout:
    """返回摘要面板、装备区和角色安全走廊的卡面坐标。"""
    normalized = normalize_summary_count(count)
    if normalized is None:
        raise ValueError("summary count must be an explicit integer in [0, 4]")

    height = summary_panel_height(normalized)
    card_bottom = EQUIPMENT_AREA_TOP + SUMMARY_BOTTOM_LOCAL
    gear_top = EQUIPMENT_AREA_TOP + EQUIPMENT_GRID_TOP_LOCAL
    safe_top = HEADER_BOTTOM + FACE_TOP_MARGIN

    if normalized:
        local_top = SUMMARY_BOTTOM_LOCAL - height
        card_top = EQUIPMENT_AREA_TOP + local_top
        safe_bottom = card_top - FACE_BOTTOM_MARGIN
    else:
        local_top = None
        card_top = None
        safe_bottom = gear_top - FACE_BOTTOM_MARGIN

    return SummaryLayout(
        count=normalized,
        visible=bool(normalized),
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
    """计算头顶→眼睛→胸部轴在卡面中的合法 top 区间。"""
    values = (scale, head_top_y, eye_y, breast_y, safe_top, safe_bottom)
    if not all(_finite_number(value) for value in values):
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
    """在可行区间内夹紧 top；无解时不伪造新的变换。"""
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
    """在不超过 6% 自动缩放预算的范围内寻找可行比例。"""
    values = (original_scale, head_top_y, breast_y, safe_top, safe_bottom, min_ratio)
    if not all(_finite_number(value) for value in values):
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
