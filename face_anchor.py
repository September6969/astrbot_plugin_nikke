"""只消费预计算的角色／皮肤锚点；不导入任何 Spine 解析器。"""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path


@lru_cache(maxsize=1)
def metadata():
    try:
        data = json.loads((Path(__file__).parent / "assets/face_anchors.json").read_text(encoding="utf-8"))
        return data.get("records", {}) if data.get("schema") == 1 else {}
    except (OSError, ValueError, AttributeError):
        return {}


def framing(data, portrait):
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
    return {"style": f"width:{width:.3f}px;height:{height:.3f}px;left:{left:.3f}px;top:{top:.3f}px;object-fit:contain",
            "source": row["anchor_kind"], "render_id": key}


@lru_cache(maxsize=1)
def identity_resolver():
    from .nikke_db_provider import NikkeDbProvider
    assets = Path(__file__).parent / "assets"
    return NikkeDbProvider(assets, assets, remote=False)
