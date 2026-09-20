"""只消费预计算的角色／皮肤锚点；不导入任何 Spine 解析器。"""
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path

from .character_card_layout import (
    MIN_AUTO_SCALE_RATIO,
    clamp_top,
    core_axis_interval,
    fitted_scale,
    normalize_summary_count,
    summary_layout,
)


_TRUTHY = {"1", "true", "yes", "on", "preview"}


def body_centering_requested(explicit):
    if explicit is not None:
        return bool(explicit)
    return os.getenv("NIKKE_FACE_GUIDED_CENTERING", "").strip().lower() in _TRUTHY


@lru_cache(maxsize=1)
def metadata():
    try:
        data = json.loads((Path(__file__).parent / "assets/face_anchors.json").read_text(encoding="utf-8"))
        return data.get("records", {}) if data.get("schema") == 1 else {}
    except (OSError, ValueError, AttributeError):
        return {}


DEFAULT_FACE_Y_OFFSET: float = 16.0
FACE_Y_OFFSET_OVERRIDES: dict[str, float | dict[str, float]] = {}


def resolve_face_y_offset(
    render_id: str | None = None,
    char_id: str | None = None,
    row: dict | None = None,
) -> float:
    """Resolve card-space vertical offset after the base Face Anchor transform.

    Priority:
      1. render/costume metadata
      2. render/costume explicit map
      3. character explicit map
      4. character metadata
      5. global default
    """
    def _extract_offset(val):
        if val is None or isinstance(val, bool):
            return None
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
        if isinstance(val, dict):
            inner = val.get("face_y_offset_px")
            if (
                isinstance(inner, (int, float))
                and not isinstance(inner, bool)
                and math.isfinite(inner)
            ):
                return float(inner)
        return None

    if isinstance(row, dict):
        framing_cfg = row.get("framing")
        if isinstance(framing_cfg, dict):
            v = _extract_offset(framing_cfg.get("face_y_offset_px"))
            if v is not None:
                return v
        v = _extract_offset(row.get("face_y_offset_px"))
        if v is not None:
            return v

    if render_id and render_id != "missing":
        v = _extract_offset(FACE_Y_OFFSET_OVERRIDES.get(render_id))
        if v is not None:
            return v

    if char_id and char_id != "missing":
        v = _extract_offset(FACE_Y_OFFSET_OVERRIDES.get(char_id))
        if v is not None:
            return v
        if char_id != render_id:
            base_row = metadata().get(char_id)
            if isinstance(base_row, dict):
                framing_cfg = base_row.get("framing")
                if isinstance(framing_cfg, dict):
                    v = _extract_offset(framing_cfg.get("face_y_offset_px"))
                    if v is not None:
                        return v
                v = _extract_offset(base_row.get("face_y_offset_px"))
                if v is not None:
                    return v

    return float(DEFAULT_FACE_Y_OFFSET)


def _finite_point(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and math.isfinite(x)
            for x in value
        )
    )


def _validated_core_axis(row: dict, portrait, point: list[float]):
    """Validate prepared metadata without guessing missing anatomy."""
    axis = row.get("core_axis")
    if not isinstance(axis, dict):
        return None, "core_axis_unavailable"

    eye = axis.get("eye_point")
    breast = axis.get("breast_point")
    head_top_y = axis.get("head_top_y")
    if not _finite_point(eye) or not _finite_point(breast):
        return None, "invalid_axis"
    if (
        not isinstance(head_top_y, (int, float))
        or isinstance(head_top_y, bool)
        or not math.isfinite(head_top_y)
    ):
        return None, "head_top_unavailable"

    # The prepared core axis must belong to the exact face anchor row. A stale
    # axis from another crop/variant is rejected rather than shifted onto it.
    if abs(float(eye[0]) - float(point[0])) > 1e-3 or abs(float(eye[1]) - float(point[1])) > 1e-3:
        return None, "axis_eye_mismatch"

    if not (
        0 <= head_top_y <= portrait.height
        and 0 <= breast[0] <= portrait.width
        and 0 <= breast[1] <= portrait.height
        and head_top_y <= point[1] < breast[1]
    ):
        return None, "invalid_axis"

    return {
        "eye_point": [float(point[0]), float(point[1])],
        "head_top_y": float(head_top_y),
        "breast_point": [float(breast[0]), float(breast[1])],
        "head_top_source": axis.get("head_top_source", "unknown"),
        "breast_source": axis.get("breast_source", "unknown"),
    }, "ok"


def framing(data, portrait, *, body_centering=None, summary_count=None):
    from PIL import Image

    if not isinstance(portrait, Image.Image):
        return {"style": "", "source": "unavailable"}

    # 通过正式身份映射得到包含皮肤的键；不能回退到默认皮肤锚点。
    if data.costume_selection and data.costume_selection.kind == "unknown":
        return {"style": "object-fit:contain", "source": "identity_unknown"}

    key = identity_resolver().resolve_render_id(data.resource_id, data.costume_id)
    row = metadata().get(key)
    digest = hashlib.sha256(portrait.convert("RGBA").tobytes()).hexdigest()
    if isinstance(row, dict):
        row = next((
            candidate
            for candidate in [row, *row.get("variants", [])]
            if isinstance(candidate, dict)
            and candidate.get("pixel_sha256") == digest
            and candidate.get("image_size", list(portrait.size)) == list(portrait.size)
        ), None)
    if not isinstance(row, dict):
        return {
            "style": "object-fit:contain;object-position:50% 35%",
            "source": "anchor_unavailable",
        }

    point, extent = row.get("point"), row.get("extent")
    if not _finite_point(point):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    if not (0 <= point[0] <= portrait.width and 0 <= point[1] <= portrait.height):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}

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
        or not all(type(x) in (int, float) and math.isfinite(x) for x in target)
    ):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    if type(desired) not in (int, float) or not math.isfinite(desired) or not 0 < desired <= 1600:
        return {"style": "object-fit:contain", "source": "anchor_invalid"}

    valid_extent = (
        isinstance(extent, list)
        and len(extent) == 2
        and all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and math.isfinite(x)
            and x > 0
            for x in extent
        )
    )
    initial_scale = desired / extent[0] if valid_extent else 2400 / portrait.height
    initial_scale = min(initial_scale, 7200 / max(portrait.size))
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

    scale = initial_scale
    width, height, left, top, diagnostics = _place(scale)

    char_id = identity_resolver().resolve_character_id(data.resource_id)
    y_offset = resolve_face_y_offset(render_id=key, char_id=char_id, row=row)
    desired_top = top + y_offset
    final_top = desired_top

    core, core_reason = _validated_core_axis(row, portrait, point)
    normalized_count = normalize_summary_count(summary_count)
    core_diag = None

    if core is not None:
        core_diag = {
            "available": True,
            "reason": core_reason,
            "summary_count": normalized_count,
            "head_top_portrait_y": core["head_top_y"],
            "eye_portrait": core["eye_point"],
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

        # New geometry is applied only when the final payload explicitly tells
        # us how many summary rows it will render. Unknown is never treated as 0.
        if normalized_count is None:
            core_diag["reason"] = "summary_count_unknown"
        else:
            layout = summary_layout(normalized_count)
            core_diag.update({
                "safe_top": layout.safe_top,
                "safe_bottom": layout.safe_bottom,
                "summary_visible": layout.visible,
                "summary_top": layout.card_top,
                "gear_top": layout.gear_top,
            })

            interval = core_axis_interval(
                scale=scale,
                head_top_y=core["head_top_y"],
                eye_y=core["eye_point"][1],
                breast_y=core["breast_point"][1],
                safe_top=layout.safe_top,
                safe_bottom=layout.safe_bottom,
            )
            core_diag.update({
                "min_top": interval.min_top,
                "max_top": interval.max_top,
                "protected_span": interval.protected_span,
                "available_height": interval.available_height,
            })

            if interval.valid and interval.min_top is not None and interval.max_top is not None:
                if interval.min_top > interval.max_top:
                    candidate_scale, fit_reason = fitted_scale(
                        original_scale=scale,
                        head_top_y=core["head_top_y"],
                        breast_y=core["breast_point"][1],
                        safe_top=layout.safe_top,
                        safe_bottom=layout.safe_bottom,
                        min_ratio=MIN_AUTO_SCALE_RATIO,
                    )
                    if candidate_scale is not None and candidate_scale < scale:
                        scale = candidate_scale
                        width, height, left, top, diagnostics = _place(scale)
                        desired_top = top + y_offset
                        interval = core_axis_interval(
                            scale=scale,
                            head_top_y=core["head_top_y"],
                            eye_y=core["eye_point"][1],
                            breast_y=core["breast_point"][1],
                            safe_top=layout.safe_top,
                            safe_bottom=layout.safe_bottom,
                        )
                        core_diag.update({
                            "scaled_for_fit": True,
                            "scale_after": scale,
                            "reason": fit_reason,
                            "min_top": interval.min_top,
                            "max_top": interval.max_top,
                            "protected_span": interval.protected_span,
                            "desired_top": desired_top,
                        })
                    else:
                        # Beyond the 6% budget: preserve the old transform.
                        # Do not partially satisfy one boundary at the cost of
                        # silently violating the other.
                        core_diag["reason"] = fit_reason

                if interval.min_top is not None and interval.max_top is not None and interval.min_top <= interval.max_top:
                    final_top, clamp_reason = clamp_top(desired_top, interval)
                    if core_diag.get("reason") in {"ok", "scaled_for_fit"}:
                        core_diag["reason"] = (
                            clamp_reason
                            if not core_diag["scaled_for_fit"]
                            else f"scaled_for_fit+{clamp_reason}"
                        )
                elif core_diag.get("reason") != "scale_limited":
                    core_diag["reason"] = interval.reason
            else:
                core_diag["reason"] = interval.reason

            core_diag.update({
                "final_top": final_top,
                "correction_y": final_top - desired_top,
                "head_top_card_before": desired_top + core["head_top_y"] * scale,
                "eye_card_before": desired_top + core["eye_point"][1] * scale,
                "breast_card_before": desired_top + core["breast_point"][1] * scale,
                "head_top_card_after": final_top + core["head_top_y"] * scale,
                "eye_card_after": final_top + core["eye_point"][1] * scale,
                "breast_card_after": final_top + core["breast_point"][1] * scale,
            })
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

    top = final_top
    ret = {
        "style": (
            f"width:{width:.3f}px;height:{height:.3f}px;"
            f"left:{left:.3f}px;top:{top:.3f}px;object-fit:contain"
        ),
        "source": row["anchor_kind"],
        "render_id": key,
    }
    if diagnostics is not None:
        ret["body_centering"] = diagnostics
    if core_diag is not None:
        ret["core_axis"] = core_diag
    return ret


@lru_cache(maxsize=1)
def identity_resolver():
    from .nikke_db_provider import NikkeDbProvider

    assets = Path(__file__).parent / "assets"
    return NikkeDbProvider(assets, assets, remote=False)
