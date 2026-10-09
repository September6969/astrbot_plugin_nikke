"""将 worker 同帧几何变换为裁切图锚点，并随 PNG 原子保存。"""
import hashlib
import json
import math
import re

from PIL.PngImagePlugin import PngInfo

from ...features.character.portrait_anchor import ANCHOR_KEY, ANCHOR_SCHEMA
from ...features.character.spine_core_axis import select_upper_torso_anchor, select_head_top, validate_axis_order


def _box(value):
    return (isinstance(value, list) and len(value) == 4
            and all(type(x) in (int, float) and math.isfinite(x) for x in value)
            and value[2] > value[0] and value[3] > value[1])


def _surface_kind(slot, name):
    """只接受明确的脸或头表面，编号后缀不改变表面语义。"""
    token = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not token or re.search(r"hair|headwear|headset|helmet|hat|accessory|_acc|patch|mask|brow|borw|blow|lash|lahs|light|spark", token):
        return None
    if re.fullmatch(r"face(?:_(?:main|base|all|\d+))?", token) or slot.lower() == "face":
        return "face_attachment"
    if re.fullmatch(r"head(?:_(?:main|base|\d+))?", token):
        return "head_attachment"
    return None


def _anchor_priority(slot, name, surface):
    """眼罩、眉毛和反光不能因名字含 eye 就成为眼睛锚点。"""
    lower = re.sub(r"[^a-z0-9]+", "_", (slot + "/" + name).lower())
    excluded = re.search(r"patch|mask|brow|borw|blow|lash|lahs|highlight|light|spark", lower)
    excluded = excluded or re.search(r"(?:^|_)(?:lit|hi|hig|high|sky|cover)(?:_|\d|$)", lower)
    if not excluded and re.search(r"(?:^|_)eye(?:s|ball|white|w|skin)?(?:_|\d|$)", lower):
        return 0
    return {"face_attachment": 1, "head_attachment": 2}.get(surface, -1)


def attach_anchor(image, geometry, crop):
    """坐标直接来自正在绘制的骨架，不按图片轮廓猜头胸。"""
    record = {"schema": ANCHOR_SCHEMA, "image_size": list(image.size),
              "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
              "status": "unavailable", "reason": "worker_geometry_unavailable"}
    if isinstance(geometry, dict) and geometry.get("schema") == 1:
        record["reason"] = "face_unavailable"
        candidates, surfaces, attachments = [], [], []
        raw_attachments = geometry.get("attachments")
        for item in raw_attachments if isinstance(raw_attachments, list) else []:
            if not isinstance(item, dict) or not _box(item.get("box")):
                continue
            box = [v - crop[i % 2] for i, v in enumerate(item["box"])]
            slot, name = str(item.get("slot", "")), str(item.get("attachment", ""))
            lower = (slot + "/" + name).lower()
            surface = _surface_kind(slot, name)
            priority = _anchor_priority(slot, name, surface)
            if priority >= 0:
                candidates.append((priority, box))
            if surface:
                surfaces.append({"name": lower, "kind": surface, "box": box})
            attachments.append({**item, "box": box, "point": [(box[0]+box[2])/2, (box[1]+box[3])/2], "surface": surface})
        if candidates:
            priority = min(p for p, _ in candidates)
            boxes = [b for p, b in candidates if p == priority]
            box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
            point = [(box[0]+box[2])/2, (box[1]+box[3])/2]
            if 0 <= point[0] < image.width and 0 <= point[1] < image.height:
                record.update(status="ready", reason="ok", point=point, extent=[box[2]-box[0], box[3]-box[1]],
                              anchor_kind=["eye_attachment", "face_attachment", "head_attachment"][priority])
                raw_bones = geometry.get("bones")
                bones = [{**b, "x": b["x"]-crop[0], "y": b["y"]-crop[1]}
                         for b in (raw_bones if isinstance(raw_bones, list) else []) if isinstance(b, dict)
                         and all(type(b.get(k)) in (int, float) and math.isfinite(b[k]) for k in ("x", "y"))]
                torso, reason = select_upper_torso_anchor(bones, attachment_candidates=attachments)
                head, head_reason = select_head_top(surfaces)
                record["core_axis_reason"] = reason if torso is None else head_reason
                if torso and head and validate_axis_order(head_top_y=head.y, eye_y=point[1], torso_y=torso.point[1]):
                    record["core_axis"] = {"eye_point": point, "head_top_y": head.y,
                                           "torso_point": list(torso.point), "torso_source": torso.source,
                                           "torso_confidence": torso.confidence, "head_top_source": head.source}
    image.info.pop("spine_geometry", None)
    image.info[ANCHOR_KEY] = json.dumps(record, ensure_ascii=False, allow_nan=False)
    return image


def save_portrait(image, path):
    """将像素和锚点写进同一个 PNG，避免双文件版本不一致。"""
    info = PngInfo()
    value = image.info.get(ANCHOR_KEY)
    if isinstance(value, str):
        info.add_text(ANCHOR_KEY, value)
    image.save(path, format="PNG", pnginfo=info)
