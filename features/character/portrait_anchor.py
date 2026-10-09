"""图片随附锚点的版本与指纹校验；不依赖骨架解析器。"""
import hashlib
import json

ANCHOR_KEY = "nikke_portrait_anchor"
ANCHOR_SCHEMA = 2


def read_anchor(image):
    """拒绝损坏、陈旧或属于其他像素的锚点。"""
    try:
        raw = getattr(image, "info", {}).get(ANCHOR_KEY)
        data = json.loads(raw) if isinstance(raw, str) else None
        if not isinstance(data, dict) or data.get("schema") != ANCHOR_SCHEMA:
            return None
        if data.get("status") not in {"ready", "unavailable"}:
            return None
        if data.get("image_size") != list(image.size):
            return None
        if data.get("pixel_sha256") != hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest():
            return None
        return data
    except (TypeError, ValueError):
        return None
