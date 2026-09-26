"""只消费预计算的角色／皮肤锚点；不导入任何 Spine 解析器。"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
from typing import TypeGuard

from .layout import (
    CARD_HEIGHT,
    CARD_WIDTH,
    FACE_SAFE_TOP,
    MAX_HERO_SCALE,
    HEAD_ONLY_SCALE_BREATHING_FACTOR,
    MIN_HERO_SCALE,
    MIN_AUTO_SCALE_RATIO,
    CoreAxisInterval,
    clamp_top,
    core_axis_interval,
    fitted_scale,
    normalize_summary_count,
    portrait_safe_rect,
    summary_layout,
)
from .face_guided_centering import robust_alpha_bounds
from .ports import CharacterRenderIdentity


_TRUTHY = {"1", "true", "yes", "on", "preview"}


def body_centering_requested(explicit):
    if explicit is not None:
        return bool(explicit)
    return os.getenv("NIKKE_FACE_GUIDED_CENTERING", "").strip().lower() in _TRUTHY


@lru_cache(maxsize=1)
def metadata() -> dict[str, object]:
    try:
        assets_root = Path(__file__).resolve().parents[2] / "assets"
        candidate = assets_root / "data" / "face_anchors.json"
        if not candidate.is_file():
            candidate = assets_root / "face_anchors.json"
        data = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema") != 1:
            return {}
        records = data.get("records")
        if not isinstance(records, dict):
            return {}
        return {key: value for key, value in records.items() if isinstance(key, str)}
    except (OSError, ValueError, AttributeError):
        return {}


DEFAULT_FACE_Y_OFFSET: float = 16.0
FACE_Y_OFFSET_OVERRIDES: dict[str, float | dict[str, float]] = {}
_SUBJECT_ALPHA_THRESHOLD = 24
# 横向分位忽略低质量边缘装饰；纵向仅采样脸部保护区到上半身窗口。
_HERO_X_QUANTILES = (0.10, 0.90)
_HERO_SOURCE_DEPTH_EXTENTS = 1.5
# Pillow 的 BOX 重采样枚举值；通过图像结构接口调用，避免领域层直接导入 PIL。
_BOX_RESAMPLING_FILTER = 4


def resolve_face_y_offset(
    render_id: str | None = None,
    char_id: str | None = None,
    row: dict[str, object] | None = None,
) -> float:
    """解析 Face Anchor 后应用到卡面的垂直偏移。"""
    def _extract_offset(value: object) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
        if isinstance(value, dict):
            inner = value.get("face_y_offset_px")
            if (
                isinstance(inner, (int, float))
                and not isinstance(inner, bool)
                and math.isfinite(inner)
            ):
                return float(inner)
        return None

    # 角色／服装行的显式配置优先。
    if isinstance(row, dict):
        framing_cfg = row.get("framing")
        if isinstance(framing_cfg, dict):
            value = _extract_offset(framing_cfg.get("face_y_offset_px"))
            if value is not None:
                return value
        value = _extract_offset(row.get("face_y_offset_px"))
        if value is not None:
            return value

    if render_id and render_id != "missing":
        value = _extract_offset(FACE_Y_OFFSET_OVERRIDES.get(render_id))
        if value is not None:
            return value

    # 角色级覆盖只在没有服装级覆盖时使用。
    if char_id and char_id != "missing":
        value = _extract_offset(FACE_Y_OFFSET_OVERRIDES.get(char_id))
        if value is not None:
            return value
        if char_id != render_id:
            base_row = metadata().get(char_id)
            if isinstance(base_row, dict):
                framing_cfg = base_row.get("framing")
                if isinstance(framing_cfg, dict):
                    value = _extract_offset(framing_cfg.get("face_y_offset_px"))
                    if value is not None:
                        return value
                value = _extract_offset(base_row.get("face_y_offset_px"))
                if value is not None:
                    return value

    return float(DEFAULT_FACE_Y_OFFSET)


def _finite_point(value: object) -> TypeGuard[list[int | float]]:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
            for item in value
        )
    )


def _finite_extent(value: object) -> TypeGuard[list[int | float]]:
    return (
        _finite_point(value)
        and all(item > 0 for item in value)
    )


def _face_safe_top_y(face_point, extent) -> float | None:
    """从已验证的眼/脸附件锚点构造面部保护上界，不扫描头饰轮廓。"""
    if not _finite_point(face_point) or not _finite_extent(extent):
        return None
    # 元数据 extent 是已验证眼/脸附件的宽高；在锚点上方留一个完整高度，
    # 形成面部保护带，不把帽子、耳朵、角或机械饰件的 alpha 当作头顶。
    return max(0.0, float(face_point[1]) - float(extent[1]))


def _alpha_mass_quantile(projection, quantile: float) -> int | None:
    total = sum(projection)
    if total <= 0:
        return None
    threshold = total * quantile
    accumulated = 0
    for index, mass in enumerate(projection):
        accumulated += mass
        if accumulated >= threshold:
            return index
    return len(projection) - 1


def _hero_subject_bounds(portrait, *, face_safe_source_y, point, extent):
    """只在脸部保护带至上半身范围内估算稳健水平主体边界。"""
    alpha = portrait.convert("RGBA").getchannel("A")
    if face_safe_source_y is None or not _finite_point(point) or not _finite_extent(extent):
        return None
    width, height = alpha.size
    hero_top = max(0, math.floor(float(face_safe_source_y)))
    hero_bottom = min(
        height,
        math.ceil(float(point[1]) + _HERO_SOURCE_DEPTH_EXTENTS * float(extent[1])),
    )
    if hero_bottom <= hero_top:
        return None
    hero_alpha = alpha.crop((0, hero_top, width, hero_bottom))
    thresholded = hero_alpha.point(
        [0 if value < _SUBJECT_ALPHA_THRESHOLD else value for value in range(256)]
    )
    horizontal = thresholded.resize((width, 1), resample=_BOX_RESAMPLING_FILTER)
    x_mass = [horizontal.getpixel((x, 0)) for x in range(width)]
    x0 = _alpha_mass_quantile(x_mass, _HERO_X_QUANTILES[0])
    x_last = _alpha_mass_quantile(x_mass, _HERO_X_QUANTILES[1])
    if x0 is None or x_last is None or x_last < x0:
        return None
    return (x0, hero_top, x_last + 1, hero_bottom)


def _constrain_head_only_scale(
    *,
    base_face_scale: float,
    point: list[int | float],
    extent: list[int | float],
    target_face: list[float],
    face_safe_source_y: float | None,
    hero_bbox,
    safe_rect,
):
    safe_rect_data = {
        "left": safe_rect.left,
        "top": safe_rect.top,
        "right": safe_rect.right,
        "bottom": safe_rect.bottom,
    }
    diagnostics = {
        "framing_mode": "head_only_anchor",
        "face_anchor": [float(point[0]), float(point[1])],
        "face_extent": [float(extent[0]), float(extent[1])],
        "target_face": target_face,
        "hero_bbox": None if hero_bbox is None else list(hero_bbox),
        "safe_rect": safe_rect_data,
        "face_safe_source_y": face_safe_source_y,
        "scale_top_source": "face_safe_top" if face_safe_source_y is not None else "unavailable",
        "scale_top": None,
        "scale_left": None,
        "scale_right": None,
        "base_face_scale": base_face_scale,
        "min_hero_scale": MIN_HERO_SCALE,
        "max_hero_scale": MAX_HERO_SCALE,
        "selected_scale_limit": min(base_face_scale, MAX_HERO_SCALE),
        "selected_constraint": "base_face_scale",
        "breathing_factor": HEAD_ONLY_SCALE_BREATHING_FACTOR,
        "final_scale": min(base_face_scale, MAX_HERO_SCALE),
    }
    if hero_bbox is None:
        diagnostics["scale_limit_reason"] = "hero_bounds_unavailable"
        selected_constraint = (
            "base_face_scale" if base_face_scale <= MAX_HERO_SCALE else "max_hero_scale"
        )
        selected_limit = min(base_face_scale, MAX_HERO_SCALE)
        final_scale = max(
            MIN_HERO_SCALE,
            selected_limit * HEAD_ONLY_SCALE_BREATHING_FACTOR,
        )
        diagnostics.update(
            {
                "selected_constraint": selected_constraint,
                "selected_scale_limit": selected_limit,
                "final_scale": final_scale,
            }
        )
        return final_scale, diagnostics

    x0, _y0, x1, _y1 = (float(value) for value in hero_bbox)
    face_x, face_y = float(point[0]), float(point[1])
    target_x, target_y = target_face
    epsilon = 1.0
    constraints = {
        "base_face_scale": base_face_scale,
        "top": (
            (target_y - safe_rect.top) / max(face_y - face_safe_source_y, epsilon)
            if face_safe_source_y is not None
            else MAX_HERO_SCALE
        ),
        "left": (target_x - safe_rect.left) / max(face_x - x0, epsilon),
        "right": (safe_rect.right - target_x) / max(x1 - face_x, epsilon),
        "max_hero_scale": MAX_HERO_SCALE,
    }
    diagnostics.update(
        {
            "scale_top": constraints["top"],
            "scale_left": constraints["left"],
            "scale_right": constraints["right"],
        }
    )
    selected_constraint = min(constraints, key=lambda name: constraints[name])
    selected_limit = constraints[selected_constraint]
    if not math.isfinite(selected_limit) or selected_limit <= 0:
        diagnostics["scale_limit_reason"] = "no_positive_safe_scale"
        return min(base_face_scale, MAX_HERO_SCALE), diagnostics

    final_scale = max(
        MIN_HERO_SCALE,
        selected_limit * HEAD_ONLY_SCALE_BREATHING_FACTOR,
    )
    diagnostics.update(
        {
            "selected_scale_limit": selected_limit,
            "selected_constraint": selected_constraint,
            "final_scale": final_scale,
        }
    )
    return final_scale, diagnostics


def _fallback_framing(portrait, source: str, render_id: str | None = None):
    """按原 35% contain 位置起步，并对可见轮廓应用统一顶部安全线。"""
    width, height = portrait.size
    scale = min(CARD_WIDTH / width, CARD_HEIGHT / height)
    rendered_width = width * scale
    rendered_height = height * scale
    left = (CARD_WIDTH - rendered_width) / 2.0
    top_before = (CARD_HEIGHT - rendered_height) * 0.35
    bounds = robust_alpha_bounds(portrait)
    guard_y = float(bounds[1]) if bounds is not None else 0.0
    top_after = max(top_before, FACE_SAFE_TOP - guard_y * scale)
    guard = {
        "vertical_guard_source": "robust_alpha_top",
        "safe_top": FACE_SAFE_TOP,
        "guard_top_source_y": guard_y,
        "guard_top_card_before": top_before + guard_y * scale,
        "guard_top_card_after": top_after + guard_y * scale,
        "vertical_correction_y": top_after - top_before,
    }
    result = {
        "style": (
            f"width:{rendered_width:.3f}px;height:{rendered_height:.3f}px;"
            f"left:{left:.3f}px;top:{top_after:.3f}px;object-fit:contain"
        ),
        "source": source,
        **guard,
    }
    if render_id is not None:
        result["render_id"] = render_id
    return result


def _validated_core_axis(row: dict[str, object], portrait, point: list[int | float]):
    """严格校验离线生成的头顶、眼睛、上躯干轴，不猜测缺失坐标。"""
    axis = row.get("core_axis")
    if not isinstance(axis, dict):
        return None, "core_axis_unavailable"

    eye = axis.get("eye_point")
    torso = axis.get("torso_point") or axis.get("breast_point")
    head_top_y = axis.get("head_top_y")
    if not _finite_point(eye) or not _finite_point(torso):
        return None, "invalid_axis"
    if (
        not isinstance(head_top_y, (int, float))
        or isinstance(head_top_y, bool)
        or not math.isfinite(head_top_y)
    ):
        return None, "head_top_unavailable"

    # 核心轴必须属于同一张已校验的脸部裁切图，拒绝陈旧 sidecar。
    if (
        abs(float(eye[0]) - float(point[0])) > 1e-3
        or abs(float(eye[1]) - float(point[1])) > 1e-3
    ):
        return None, "axis_eye_mismatch"

    if not (
        0 <= head_top_y <= portrait.height
        and 0 <= torso[0] <= portrait.width
        and 0 <= torso[1] <= portrait.height
        and head_top_y <= point[1] < torso[1]
    ):
        return None, "invalid_axis"

    return {
        "eye_point": [float(point[0]), float(point[1])],
        "head_top_y": float(head_top_y),
        "torso_point": [float(torso[0]), float(torso[1])],
        "torso_source": axis.get("torso_source", axis.get("breast_source", "unknown")),
        "torso_confidence": axis.get("torso_confidence"),
        # 兼容旧 metadata 与旧诊断消费者。
        "breast_point": [float(torso[0]), float(torso[1])],
        "head_top_source": axis.get("head_top_source", "unknown"),
        "breast_source": axis.get("breast_source", axis.get("torso_source", "unknown")),
    }, "ok"


def framing(
    data,
    portrait,
    *,
    body_centering=None,
    summary_count=None,
    identity_resolver: CharacterRenderIdentity | None = None,
):
    if not all(
        callable(getattr(portrait, name, None))
        for name in ("convert", "tobytes")
    ) or not all(hasattr(portrait, name) for name in ("size", "width", "height")):
        return {"style": "", "source": "unavailable"}

    if data.costume_selection and data.costume_selection.kind == "unknown":
        return _fallback_framing(portrait, "identity_unknown")

    if identity_resolver is None:
        return _fallback_framing(portrait, "identity_unavailable")

    key = identity_resolver.resolve_render_id(data.resource_id, data.costume_id)
    row = metadata().get(key)
    digest = hashlib.sha256(portrait.convert("RGBA").tobytes()).hexdigest()
    if isinstance(row, dict):
        row = next(
            (
                candidate
                for candidate in [row, *row.get("variants", [])]
                if isinstance(candidate, dict)
                and candidate.get("pixel_sha256") == digest
                and candidate.get("image_size", list(portrait.size)) == list(portrait.size)
            ),
            None,
        )
    if not isinstance(row, dict):
        return _fallback_framing(portrait, "anchor_unavailable", key)

    point, extent = row.get("point"), row.get("extent")
    if not _finite_point(point):
        return _fallback_framing(portrait, "anchor_invalid", key)
    if not (0 <= point[0] < portrait.width and 0 <= point[1] < portrait.height):
        return _fallback_framing(portrait, "anchor_invalid", key)

    config = row.get("framing", {})
    target = config.get("target", [760, 550]) if isinstance(config, dict) else [760, 550]
    desired = (
        config.get(
            "extent_width",
            256 if row.get("anchor_kind") == "eye_attachment" else 430,
        )
        if isinstance(config, dict)
        else 256
    )
    if (
        not isinstance(target, list)
        or len(target) != 2
        or not all(type(item) in (int, float) and math.isfinite(item) for item in target)
    ):
        return _fallback_framing(portrait, "anchor_invalid", key)
    if (
        type(desired) not in (int, float)
        or not math.isfinite(desired)
        or not 0 < desired <= CARD_WIDTH
    ):
        return _fallback_framing(portrait, "anchor_invalid", key)

    initial_scale = (
        desired / extent[0]
        if _finite_extent(extent)
        else 2400 / portrait.height
    )
    initial_scale = min(initial_scale, 7200 / max(portrait.size))
    core, core_reason = _validated_core_axis(row, portrait, point)
    normalized_count = normalize_summary_count(summary_count)
    char_id = identity_resolver.resolve_character_id(data.resource_id)
    y_offset = resolve_face_y_offset(render_id=key, char_id=char_id, row=row)
    head_scale_diagnostics = None
    scale = initial_scale
    if core is not None:
        guard_y, guard_source = float(core["head_top_y"]), "core_head_top"
    else:
        face_safe_top_y = _face_safe_top_y(point, extent)
        if face_safe_top_y is not None:
            guard_y, guard_source = face_safe_top_y, "face_safe_top"
        else:
            alpha_bounds = robust_alpha_bounds(portrait)
            guard_y = float(alpha_bounds[1]) if alpha_bounds is not None else 0.0
            guard_source = "robust_alpha_top"
        base_face_scale = initial_scale
        if _finite_extent(extent):
            base_face_scale = min(
                desired / float(extent[0]),
                7200 / max(portrait.size),
            )
        hero_bbox = _hero_subject_bounds(
            portrait,
            face_safe_source_y=face_safe_top_y,
            point=point,
            extent=extent if _finite_extent(extent) else [1.0, 1.0],
        )
        target_face = [float(target[0]), float(target[1]) + y_offset]
        scale, head_scale_diagnostics = _constrain_head_only_scale(
            base_face_scale=base_face_scale,
            point=point,
            extent=extent if _finite_extent(extent) else [1.0, 1.0],
            target_face=target_face,
            face_safe_source_y=face_safe_top_y,
            hero_bbox=hero_bbox,
            safe_rect=portrait_safe_rect(normalized_count),
        )

    requested = body_centering_requested(body_centering)

    def _place(scale):
        width, height = portrait.width * scale, portrait.height * scale
        left = target[0] - point[0] * scale
        top = target[1] - point[1] * scale
        diagnostics = None

        if requested:
            from .face_guided_centering import FrameTransform, center_after_face_anchor

            base = FrameTransform(scale=scale, left=left, top=top)
            result = center_after_face_anchor(portrait, face_point=point, base=base)
            left = result.transform.left
            top = result.transform.top
            analysis = result.analysis
            diagnostics = {
                "mode": "face_guided_v5",
                "reason": result.reason,
                "confidence": None if analysis is None else analysis.confidence,
                "shift_x": result.applied_shift[0],
                "shift_y": result.applied_shift[1],
                "raw_shift_x": result.raw_shift[0],
                "raw_shift_y": result.raw_shift[1],
                "applied_shift_x": result.applied_shift[0],
                "applied_shift_y": result.applied_shift[1],
                "clamped": result.clamped,
                "face_before": list(result.face_before),
                "face_after": list(result.face_after),
                "body_axis_x": None if analysis is None else analysis.body_axis_x,
                "visual_center_x": None if analysis is None else analysis.visual_center_x,
                "bootstrap_width": None if analysis is None else analysis.bootstrap_width,
                "trusted_width": None if analysis is None else analysis.trusted_width,
                "bootstrap_reliable": None if analysis is None else analysis.bootstrap_reliable,
                "bootstrap_support_rows": None if analysis is None else analysis.bootstrap_support_rows,
                "bootstrap_clean_rows": None if analysis is None else analysis.bootstrap_clean_rows,
                "bootstrap_clean_fraction": None if analysis is None else analysis.bootstrap_clean_fraction,
                "bootstrap_half_balance": None if analysis is None else analysis.bootstrap_half_balance,
                "bootstrap_contaminated_rows": None if analysis is None else analysis.bootstrap_contaminated_rows,
                "path_coverage": None if analysis is None else analysis.path_coverage,
                "path_continuity": None if analysis is None else analysis.path_continuity,
                "path_ambiguity": None if analysis is None else analysis.path_ambiguity,
                "width_reliability": None if analysis is None else analysis.width_reliability,
                "terminated_early": None if analysis is None else analysis.terminated_early,
                "max_vertical_gap": None if analysis is None else analysis.max_vertical_gap,
                "max_untrusted_span": None if analysis is None else analysis.max_untrusted_span,
            }
        return width, height, left, top, diagnostics

    width, height, left, top, diagnostics = _place(scale)
    desired_top = top + y_offset
    face_min_top = FACE_SAFE_TOP - guard_y * scale
    final_top = max(desired_top, face_min_top)
    core_diag = None

    if core is not None:
        core_diag = {
            "available": True,
            "reason": core_reason,
            "summary_count": normalized_count,
            "head_top_portrait_y": core["head_top_y"],
            "eye_portrait": core["eye_point"],
            "torso_portrait": core["torso_point"],
            "torso_source": core["torso_source"],
            "torso_confidence": core["torso_confidence"],
            "breast_portrait": core["breast_point"],
            "head_top_source": core["head_top_source"],
            "breast_source": core["breast_source"],
            "scale_before": scale,
            "scale_after": scale,
            "scaled_for_fit": False,
            "desired_top": desired_top,
            "final_top": desired_top,
            "correction_y": 0.0,
        }

        # 只有 payload 明确给出摘要行数时才启用新的安全走廊。
        if normalized_count is None:
            core_diag["reason"] = "summary_count_unknown"
        else:
            layout = summary_layout(normalized_count)
            core_diag.update(
                {
                    "safe_top": layout.safe_top,
                    "safe_bottom": layout.safe_bottom,
                    "summary_visible": layout.visible,
                    "summary_top": layout.card_top,
                    "gear_top": layout.gear_top,
                }
            )
            interval = core_axis_interval(
                scale=scale,
                head_top_y=core["head_top_y"],
                eye_y=core["eye_point"][1],
                torso_y=core["torso_point"][1],
                safe_top=layout.safe_top,
                safe_bottom=layout.safe_bottom,
            )
            combined_min_top = (
                max(interval.min_top, face_min_top)
                if interval.min_top is not None
                else None
            )
            core_diag.update(
                {
                    "min_top": interval.min_top,
                    "face_min_top": face_min_top,
                    "combined_min_top": combined_min_top,
                    "max_top": interval.max_top,
                    "protected_span": interval.protected_span,
                    "available_height": interval.available_height,
                }
            )

            if interval.valid and combined_min_top is not None and interval.max_top is not None:
                if combined_min_top > interval.max_top:
                    fit_head_top = min(float(core["head_top_y"]), guard_y)
                    candidate_scale, fit_reason = fitted_scale(
                        original_scale=scale,
                        head_top_y=fit_head_top,
                        torso_y=core["torso_point"][1],
                        safe_top=layout.safe_top,
                        safe_bottom=layout.safe_bottom,
                        min_ratio=MIN_AUTO_SCALE_RATIO,
                    )
                    if candidate_scale is not None and candidate_scale < scale:
                        scale = candidate_scale
                        width, height, left, top, diagnostics = _place(scale)
                        desired_top = top + y_offset
                        face_min_top = FACE_SAFE_TOP - guard_y * scale
                        interval = core_axis_interval(
                            scale=scale,
                            head_top_y=core["head_top_y"],
                            eye_y=core["eye_point"][1],
                            torso_y=core["torso_point"][1],
                            safe_top=layout.safe_top,
                            safe_bottom=layout.safe_bottom,
                        )
                        combined_min_top = (
                            max(interval.min_top, face_min_top)
                            if interval.min_top is not None
                            else None
                        )
                        core_diag.update(
                            {
                                "scaled_for_fit": True,
                                "scale_after": scale,
                                "reason": fit_reason,
                                "min_top": interval.min_top,
                                "face_min_top": face_min_top,
                                "combined_min_top": combined_min_top,
                                "max_top": interval.max_top,
                                "protected_span": interval.protected_span,
                                "desired_top": desired_top,
                            }
                        )
                    else:
                        core_diag["reason"] = fit_reason

                if (
                    combined_min_top is not None
                    and interval.max_top is not None
                    and combined_min_top <= interval.max_top
                ):
                    combined_interval = CoreAxisInterval(
                        valid=interval.valid,
                        min_top=combined_min_top,
                        max_top=interval.max_top,
                        protected_span=interval.protected_span,
                        available_height=interval.available_height,
                        reason=interval.reason,
                    )
                    final_top, clamp_reason = clamp_top(desired_top, combined_interval)
                    if core_diag.get("reason") in {"ok", "scaled_for_fit"}:
                        core_diag["reason"] = (
                            clamp_reason
                            if not core_diag["scaled_for_fit"]
                            else f"scaled_for_fit+{clamp_reason}"
                        )
                else:
                    final_top = max(desired_top, FACE_SAFE_TOP - guard_y * scale)
                    if core_diag.get("reason") != "scale_limited":
                        core_diag["reason"] = (
                            "face_safety_priority"
                            if combined_min_top is not None
                            and interval.max_top is not None
                            and combined_min_top > interval.max_top
                            else interval.reason
                        )
            else:
                core_diag["reason"] = interval.reason

    elif normalized_count is not None:
        core_diag = {
            "available": False,
            "reason": core_reason,
            "summary_count": normalized_count,
            "scale_before": scale,
            "scale_after": scale,
            "scaled_for_fit": False,
            "desired_top": desired_top,
            "final_top": desired_top,
            "correction_y": 0.0,
        }

    final_top = max(final_top, FACE_SAFE_TOP - guard_y * scale)
    top = final_top
    if core_diag is not None:
        core_diag.update(
            {
                "desired_top": desired_top,
                "final_top": final_top,
                "correction_y": final_top - desired_top,
                "scale_after": scale,
            }
        )
        if core is not None:
            core_diag.update(
                {
                    "head_top_card_before": desired_top + core["head_top_y"] * scale,
                    "eye_card_before": desired_top + core["eye_point"][1] * scale,
                    "torso_card_before": desired_top + core["torso_point"][1] * scale,
                    "breast_card_before": desired_top + core["breast_point"][1] * scale,
                    "head_top_card_after": final_top + core["head_top_y"] * scale,
                    "eye_card_after": final_top + core["eye_point"][1] * scale,
                    "torso_card_after": final_top + core["torso_point"][1] * scale,
                    "breast_card_after": final_top + core["breast_point"][1] * scale,
                }
            )
    ret = {
        "style": (
            f"width:{width:.3f}px;height:{height:.3f}px;"
            f"left:{left:.3f}px;top:{top:.3f}px;object-fit:contain"
        ),
        "source": row["anchor_kind"],
        "render_id": key,
        "vertical_guard_source": guard_source,
        "safe_top": FACE_SAFE_TOP,
        "guard_top_source_y": guard_y,
        "guard_top_card_before": desired_top + guard_y * scale,
        "guard_top_card_after": final_top + guard_y * scale,
        "vertical_correction_y": final_top - desired_top,
    }
    if diagnostics is not None:
        ret["body_centering"] = diagnostics
    if core_diag is not None:
        ret["core_axis"] = core_diag
    if head_scale_diagnostics is not None:
        head_scale_diagnostics.update(
            {
                "translate_x": left,
                "translate_y": top,
                "face_after": [
                    left + float(point[0]) * scale,
                    top + float(point[1]) * scale,
                ],
            }
        )
        ret.update(head_scale_diagnostics)
    return ret
