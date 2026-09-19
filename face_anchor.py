"""只消费预计算的角色／皮肤锚点；不导入任何 Spine 解析器。"""
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path


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
    """Resolve card-space vertical offset (px) applied after Face Anchor framing.

    Priority:
      1. costume/render-specific override:
         - row metadata framing["face_y_offset_px"] or row["face_y_offset_px"]
         - FACE_Y_OFFSET_OVERRIDES.get(render_id)
      2. character-specific override:
         - FACE_Y_OFFSET_OVERRIDES.get(char_id)
         - character metadata in metadata().get(char_id) framing["face_y_offset_px"] or ["face_y_offset_px"]
      3. global default: DEFAULT_FACE_Y_OFFSET (16.0)
    """
    def _extract_offset(val):
        if val is None:
            return None
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
        if isinstance(val, dict):
            inner = val.get("face_y_offset_px")
            if isinstance(inner, (int, float)) and math.isfinite(inner):
                return float(inner)
        return None

    # 1. Render-specific override
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

    # 2. Character-specific override
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

    # 3. Global default
    return float(DEFAULT_FACE_Y_OFFSET)


def framing(data, portrait, *, body_centering=None):
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
        row = next((candidate for candidate in [row, *row.get("variants", [])]
                    if isinstance(candidate, dict) and candidate.get("pixel_sha256") == digest
                    and candidate.get("image_size", list(portrait.size)) == list(portrait.size)), None)
    if not isinstance(row, dict):
        return {"style": "object-fit:contain;object-position:50% 35%", "source": "anchor_unavailable"}
    point, extent = row.get("point"), row.get("extent")
    if not isinstance(point, list) or len(point) != 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in point):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    if not (0 <= point[0] <= portrait.width and 0 <= point[1] <= portrait.height):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    # 可按角色和皮肤离线校准目标位置／脸部尺寸，缺省采用案例布局。
    config = row.get("framing", {})
    target = config.get("target", [760, 550]) if isinstance(config, dict) else [760, 550]
    desired = config.get("extent_width", 256 if row.get("anchor_kind") == "eye_attachment" else 430) if isinstance(config, dict) else 256
    if not isinstance(target, list) or len(target) != 2 or not all(type(x) in (int, float) and math.isfinite(x) for x in target):
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    if type(desired) not in (int, float) or not math.isfinite(desired) or not 0 < desired <= 1600:
        return {"style": "object-fit:contain", "source": "anchor_invalid"}
    valid_extent = isinstance(extent, list) and len(extent) == 2 and all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in extent)
    scale = desired / extent[0] if valid_extent else 2400 / portrait.height
    scale = min(scale, 7200 / max(portrait.size))
    width, height = portrait.width * scale, portrait.height * scale
    left, top = target[0] - point[0] * scale, target[1] - point[1] * scale

    diagnostics = None
    if body_centering_requested(body_centering):
        from .face_guided_centering import (
            FrameTransform,
            center_after_face_anchor,
        )
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

    char_id = identity_resolver().resolve_character_id(data.resource_id)
    top += resolve_face_y_offset(render_id=key, char_id=char_id, row=row)

    ret = {
        "style": f"width:{width:.3f}px;height:{height:.3f}px;left:{left:.3f}px;top:{top:.3f}px;object-fit:contain",
        "source": row["anchor_kind"],
        "render_id": key,
    }
    if diagnostics is not None:
        ret["body_centering"] = diagnostics
    return ret


@lru_cache(maxsize=1)
def identity_resolver():
    from .nikke_db_provider import NikkeDbProvider
    assets = Path(__file__).parent / "assets"
    return NikkeDbProvider(assets, assets, remote=False)
