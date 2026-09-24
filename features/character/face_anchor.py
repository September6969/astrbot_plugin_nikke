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
    MIN_AUTO_SCALE_RATIO,
    clamp_top,
    core_axis_interval,
    fitted_scale,
    normalize_summary_count,
    summary_layout,
)
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

    # 通过正式身份映射得到包含皮肤的键；不能回退到默认皮肤锚点。
    if data.costume_selection and data.costume_selection.kind == "unknown":
        return {"style": "object-fit:contain", "source": "identity_unknown"}

    if identity_resolver is None:
        return {
            "style": "object-fit:contain;object-position:50% 35%",
            "source": "identity_unavailable",
        }
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
        or not all(type(item) in (int, float) and math.isfinite(item) for item in target)
    ):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    if (
        type(desired) not in (int, float)
        or not math.isfinite(desired)
        or not 0 < desired <= 1600
    ):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}

    initial_scale = (
        desired / extent[0]
        if _finite_extent(extent)
        else 2400 / portrait.height
    )
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

    char_id = identity_resolver.resolve_character_id(data.resource_id)
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
            core_diag.update(
                {
                    "min_top": interval.min_top,
                    "max_top": interval.max_top,
                    "protected_span": interval.protected_span,
                    "available_height": interval.available_height,
                }
            )

            if interval.valid and interval.min_top is not None and interval.max_top is not None:
                if interval.min_top > interval.max_top:
                    candidate_scale, fit_reason = fitted_scale(
                        original_scale=scale,
                        head_top_y=core["head_top_y"],
                        torso_y=core["torso_point"][1],
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
                            torso_y=core["torso_point"][1],
                            safe_top=layout.safe_top,
                            safe_bottom=layout.safe_bottom,
                        )
                        core_diag.update(
                            {
                                "scaled_for_fit": True,
                                "scale_after": scale,
                                "reason": fit_reason,
                                "min_top": interval.min_top,
                                "max_top": interval.max_top,
                                "protected_span": interval.protected_span,
                                "desired_top": desired_top,
                            }
                        )
                    else:
                        # 超过 6% 预算时保留旧变换，不只满足一侧边界。
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

            core_diag.update(
                {
                    "final_top": final_top,
                    "correction_y": final_top - desired_top,
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
