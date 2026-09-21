"""离线 Spine 骨骼与表面候选的保守选择器。"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class SelectedPoint:
    point: tuple[float, float]
    source: str
    confidence: float = 0.0


@dataclass(frozen=True)
class SelectedHeadTop:
    y: float
    source: str


def _finite(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _norm(name: object) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _clean_bones(candidates: Iterable[dict]) -> list[dict]:
    cleaned = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        if not (_finite(item.get("x")) and _finite(item.get("y"))):
            continue
        name = _norm(item.get("name"))
        if not name:
            continue
        cleaned.append(
            {
                "name": name,
                "raw_name": str(item.get("name")),
                "parent": _norm(item.get("parent")),
                "x": float(item["x"]),
                "y": float(item["y"]),
            }
        )
    return cleaned


_PAIR_RE = re.compile(r"^(breast|bust|boob)_(l|left|r|right)$")
_PAIR_SIDE = {"l": "left", "left": "left", "r": "right", "right": "right"}
_SINGLE_PRIORITIES = (
    {"breast", "bust", "boob"},
    {"chest", "pectoral"},
    {"upper_body", "upperbody", "upper_torso"},
    {"torso"},
)


def select_breast_anchor(candidates: Iterable[dict]) -> tuple[SelectedPoint | None, str]:
    """选择明确的胸部参考点，拒绝任意辅助骨骼平均。"""
    bones = _clean_bones(candidates)
    pair_groups: dict[str, dict[str, list[dict]]] = {}
    for bone in bones:
        match = _PAIR_RE.fullmatch(bone["name"])
        if not match:
            continue
        stem, side_raw = match.groups()
        side = _PAIR_SIDE[side_raw]
        pair_groups.setdefault(stem, {"left": [], "right": []})[side].append(bone)

    complete_pairs: list[tuple[str, dict, dict]] = []
    for stem, sides in pair_groups.items():
        if len(sides["left"]) != 1 or len(sides["right"]) != 1:
            continue
        left, right = sides["left"][0], sides["right"][0]
        if not left["parent"] or left["parent"] != right["parent"]:
            continue
        complete_pairs.append((stem, left, right))

    if len(complete_pairs) == 1:
        _, left, right = complete_pairs[0]
        return SelectedPoint(
            point=((left["x"] + right["x"]) / 2.0, (left["y"] + right["y"]) / 2.0),
            source=f"pair:{left['raw_name']}+{right['raw_name']}",
            confidence=0.72,
        ), "ok"
    if len(complete_pairs) > 1:
        return None, "ambiguous_breast_pairs"

    for accepted in _SINGLE_PRIORITIES:
        hits = [bone for bone in bones if bone["name"] in accepted]
        if len(hits) == 1:
            hit = hits[0]
            return SelectedPoint(
                (hit["x"], hit["y"]),
                f"single:{hit['raw_name']}",
                0.64,
            ), "ok"
        if len(hits) > 1:
            return None, "ambiguous_breast_single"

    return None, "breast_unavailable"


_TORSO_PAIR_RE = re.compile(
    r"^(upper_torso|upperbody|upper_body|torso|chest|breast|bust|boob)_(l|left|r|right)$"
)
def _confidence(value: Any, default: float) -> float:
    if _finite(value):
        return max(0.0, min(1.0, float(value)))
    return default


def _spec_kind(spec: Any) -> str | None:
    if isinstance(spec, str):
        return "bone"
    if not isinstance(spec, dict):
        return None
    kind = spec.get("kind")
    if isinstance(kind, str) and kind.strip():
        return _norm(kind)
    if isinstance(spec.get("bones"), list) or isinstance(spec.get("pair"), list):
        return "bone_pair"
    if isinstance(spec.get("attachments"), list) or isinstance(spec.get("items"), list):
        return "attachment_pair"
    if isinstance(spec.get("bone"), str) or isinstance(spec.get("name"), str):
        return "bone"
    if isinstance(spec.get("slot"), str) and isinstance(spec.get("attachment"), str):
        return "attachment"
    return None


def _normalized_spec(spec: Any, *, default_confidence: float) -> dict[str, Any] | None:
    if isinstance(spec, str):
        return {
            "kind": "bone",
            "bone": spec,
            "confidence": default_confidence,
        }
    if not isinstance(spec, dict):
        return None
    kind = _spec_kind(spec)
    if kind not in {"bone", "bone_pair", "attachment", "attachment_pair", "surface"}:
        return None
    normalized = dict(spec)
    normalized["kind"] = kind
    normalized["confidence"] = _confidence(
        spec.get("confidence"), default_confidence
    )
    return normalized


def _select_bone_spec(
    bones: list[dict],
    spec: dict[str, Any],
    *,
    source_prefix: str,
    default_confidence: float,
) -> tuple[SelectedPoint | None, str]:
    kind = spec["kind"]
    if kind == "bone":
        name = spec.get("bone", spec.get("name"))
        if not isinstance(name, str) or not _norm(name):
            return None, "invalid"
        target = _norm(name)
        parent = _norm(spec.get("parent"))
        all_hits = [item for item in bones if item["name"] == target]
        if len(all_hits) != 1:
            return None, "ambiguous" if len(all_hits) > 1 else "missing"
        hits = [item for item in all_hits if not parent or item["parent"] == parent]
        if len(hits) != 1:
            return None, "missing"
        hit = hits[0]
        return SelectedPoint(
            (hit["x"], hit["y"]),
            f"{source_prefix}:{hit['raw_name']}",
            _confidence(spec.get("confidence"), default_confidence),
        ), "ok"

    names = spec.get("bones", spec.get("pair"))
    if kind != "bone_pair" or not isinstance(names, list) or len(names) != 2:
        return None, "invalid"
    normalized_names = [_norm(value) for value in names]
    if not all(normalized_names) or normalized_names[0] == normalized_names[1]:
        return None, "invalid"
    parent = _norm(spec.get("parent"))
    selected = []
    for target in normalized_names:
        all_hits = [item for item in bones if item["name"] == target]
        if len(all_hits) != 1:
            return None, "ambiguous" if len(all_hits) > 1 else "missing"
        hits = [item for item in all_hits if not parent or item["parent"] == parent]
        if len(hits) != 1:
            return None, "missing"
        selected.append(hits[0])
    if (
        not selected[0]["parent"]
        or selected[0]["parent"] != selected[1]["parent"]
    ):
        return None, "missing"
    return SelectedPoint(
        (
            (selected[0]["x"] + selected[1]["x"]) / 2.0,
            (selected[0]["y"] + selected[1]["y"]) / 2.0,
        ),
        f"{source_prefix}:{selected[0]['raw_name']}+{selected[1]['raw_name']}",
        _confidence(spec.get("confidence"), default_confidence),
    ), "ok"


def _clean_attachment_candidates(candidates: Iterable[dict]) -> list[dict]:
    cleaned = []
    for item in candidates or []:
        if not isinstance(item, dict) or item.get("visible") is False:
            continue
        slot = str(item.get("slot") or "").strip()
        attachment = str(item.get("attachment") or "").strip()
        bone = str(item.get("bone") or "").strip()
        if not slot or not attachment:
            continue
        point = item.get("point")
        if not (
            isinstance(point, (list, tuple))
            and len(point) == 2
            and all(_finite(value) for value in point)
        ):
            box = item.get("box")
            if (
                not isinstance(box, (list, tuple))
                or len(box) != 4
                or not all(_finite(value) for value in box)
                or box[2] <= box[0]
                or box[3] <= box[1]
            ):
                continue
            point = [(float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0]
        cleaned.append(
            {
                "slot": _norm(slot),
                "attachment": _norm(attachment),
                "raw_slot": slot,
                "raw_attachment": attachment,
                "bone": _norm(bone),
                "parent": _norm(item.get("parent")),
                "point": (float(point[0]), float(point[1])),
                "verified": item.get("verified") is True,
                "surface": _norm(item.get("surface") or item.get("surface_kind")),
            }
        )
    return cleaned


def _attachment_selector_item(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    slot = item.get("slot")
    attachment = item.get("attachment")
    if not isinstance(slot, str) or not isinstance(attachment, str):
        return None
    return {
        "slot": _norm(slot),
        "attachment": _norm(attachment),
        "bone": _norm(item.get("bone")),
        "parent": _norm(item.get("parent")),
        "surface": _norm(item.get("surface") or item.get("surface_kind")),
    }


def _select_attachment_spec(
    candidates: list[dict],
    spec: dict[str, Any],
    *,
    source_prefix: str,
    default_confidence: float,
) -> tuple[SelectedPoint | None, str]:
    kind = spec["kind"]
    if kind in {"attachment", "surface"}:
        selector = _attachment_selector_item(spec)
        if selector is None:
            return None, "invalid"
        hits = [
            item
            for item in candidates
            if item["slot"] == selector["slot"]
            and item["attachment"] == selector["attachment"]
            and (not selector["bone"] or item["bone"] == selector["bone"])
            and (not selector["parent"] or item["parent"] == selector["parent"])
            and (not selector["surface"] or item["surface"] == selector["surface"])
        ]
        if len(hits) != 1:
            return None, "ambiguous" if len(hits) > 1 else "missing"
        hit = hits[0]
        return SelectedPoint(
            hit["point"],
            f"{source_prefix}:{hit['raw_slot']}/{hit['raw_attachment']}",
            _confidence(spec.get("confidence"), default_confidence),
        ), "ok"

    items = spec.get("attachments", spec.get("items"))
    if kind != "attachment_pair" or not isinstance(items, list) or len(items) != 2:
        return None, "invalid"
    selectors = [_attachment_selector_item(item) for item in items]
    if any(selector is None for selector in selectors):
        return None, "invalid"
    hits = []
    for selector in selectors:
        matching = [
            item
            for item in candidates
            if item["slot"] == selector["slot"]
            and item["attachment"] == selector["attachment"]
            and (not selector["bone"] or item["bone"] == selector["bone"])
            and (not selector["parent"] or item["parent"] == selector["parent"])
            and (not selector["surface"] or item["surface"] == selector["surface"])
        ]
        if len(matching) != 1:
            return None, "ambiguous" if len(matching) > 1 else "missing"
        hits.append(matching[0])
    parent = _norm(spec.get("parent"))
    if parent and any(item["parent"] != parent for item in hits):
        return None, "missing"
    if not hits[0]["parent"] or hits[0]["parent"] != hits[1]["parent"]:
        return None, "missing"
    return SelectedPoint(
        (
            (hits[0]["point"][0] + hits[1]["point"][0]) / 2.0,
            (hits[0]["point"][1] + hits[1]["point"][1]) / 2.0,
        ),
        f"{source_prefix}:{hits[0]['raw_slot']}/{hits[0]['raw_attachment']}+"
        f"{hits[1]['raw_slot']}/{hits[1]['raw_attachment']}",
        _confidence(spec.get("confidence"), default_confidence),
    ), "ok"


def _select_spec(
    bones: list[dict],
    attachments: list[dict],
    raw_spec: Any,
    *,
    source_prefix: str,
    default_confidence: float,
) -> tuple[SelectedPoint | None, str]:
    spec = _normalized_spec(raw_spec, default_confidence=default_confidence)
    if spec is None:
        return None, "invalid"
    if spec["kind"] in {"bone", "bone_pair"}:
        return _select_bone_spec(
            bones,
            spec,
            source_prefix=source_prefix,
            default_confidence=default_confidence,
        )
    return _select_attachment_spec(
        attachments,
        spec,
        source_prefix=source_prefix,
        default_confidence=default_confidence,
    )


def _semantic_spec(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    for role in ("upper_torso", "chest"):
        value = entry.get(role)
        if isinstance(value, (str, dict)):
            return value
    return None


def _select_generic_upper_torso(
    bones: list[dict],
) -> tuple[SelectedPoint | None, str]:
    pair_groups: dict[str, dict[str, list[dict]]] = {}
    for bone in bones:
        match = _TORSO_PAIR_RE.fullmatch(bone["name"])
        if not match:
            continue
        stem, side_raw = match.groups()
        side = _PAIR_SIDE[side_raw]
        pair_groups.setdefault(stem, {"left": [], "right": []})[side].append(bone)

    complete_pairs: list[tuple[str, dict, dict]] = []
    for stem, sides in pair_groups.items():
        if len(sides["left"]) != 1 or len(sides["right"]) != 1:
            continue
        left, right = sides["left"][0], sides["right"][0]
        if not left["parent"] or left["parent"] != right["parent"]:
            continue
        complete_pairs.append((stem, left, right))
    if any(
        len(sides["left"]) > 1 or len(sides["right"]) > 1
        for sides in pair_groups.values()
    ):
        return None, "ambiguous_upper_torso_pairs"
    if len(complete_pairs) == 1:
        _, left, right = complete_pairs[0]
        return SelectedPoint(
            (
                (left["x"] + right["x"]) / 2.0,
                (left["y"] + right["y"]) / 2.0,
            ),
            f"generic:{left['raw_name']}+{right['raw_name']}",
            0.68,
        ), "ok"
    if len(complete_pairs) > 1:
        return None, "ambiguous_upper_torso_pairs"

    for accepted in (
        {"upper_torso", "upperbody", "upper_body"},
        {"torso"},
        {"chest", "pectoral"},
        {"breast", "bust", "boob"},
    ):
        hits = [bone for bone in bones if bone["name"] in accepted]
        if len(hits) == 1:
            hit = hits[0]
            return SelectedPoint(
                (hit["x"], hit["y"]),
                f"generic:{hit['raw_name']}",
                0.62,
            ), "ok"
        if len(hits) > 1:
            return None, "ambiguous_upper_torso_single"
    return None, "upper_torso_unavailable"


def select_upper_torso_anchor(
    candidates: Iterable[dict],
    *,
    manual_override: Any = None,
    existing_override: Any = None,
    semantic_entry: Any = None,
    attachment_candidates: Iterable[dict] = (),
    verified_attachment_mapping: Any = None,
) -> tuple[SelectedPoint | None, str]:
    """按证据优先级选择上躯干锚点；没有证据时严格失败关闭。

    ``manual_override`` 是单次渲染覆盖；``existing_override`` 来自人工覆盖表；
    ``semantic_entry`` 来自语义 registry；``verified_attachment_mapping`` 必须由
    已核验的 attachment 证据提供。普通候选不会因位置、序号或 ``op*`` 名称被猜成躯干。
    """
    bones = _clean_bones(candidates)
    attachments = _clean_attachment_candidates(attachment_candidates)

    if manual_override is not None:
        selected, _ = _select_spec(
            bones,
            attachments,
            manual_override,
            source_prefix="manual",
            default_confidence=1.0,
        )
        if selected is not None:
            return selected, "ok"
        return None, "manual_override_unavailable"

    if existing_override is not None:
        selected, _ = _select_spec(
            bones,
            attachments,
            existing_override,
            source_prefix="override",
            default_confidence=0.98,
        )
        if selected is not None:
            return selected, "ok"
        return None, "existing_override_unavailable"

    semantic = _semantic_spec(semantic_entry)
    if semantic is not None:
        selected, status = _select_spec(
            bones,
            attachments,
            semantic,
            source_prefix="semantic",
            default_confidence=0.9,
        )
        if selected is not None:
            return selected, "ok"
        if status == "ambiguous":
            return None, "ambiguous_semantic_upper_torso"

    if verified_attachment_mapping is not None:
        if not isinstance(verified_attachment_mapping, dict) or verified_attachment_mapping.get("verified") is not True:
            return None, "verified_attachment_unavailable"
        selected, status = _select_spec(
            bones,
            attachments,
            verified_attachment_mapping,
            source_prefix="verified-attachment",
            default_confidence=0.86,
        )
        if selected is not None:
            return selected, "ok"
        return None, "verified_attachment_unavailable"

    return _select_generic_upper_torso(bones)


def _clean_head_candidates(candidates: Iterable[dict]) -> list[dict]:
    cleaned = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        box = item.get("box")
        if kind not in {"head_attachment", "face_attachment"}:
            continue
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(_finite(value) for value in box)
            or box[2] <= box[0]
            or box[3] <= box[1]
        ):
            continue
        cleaned.append(
            {
                "kind": kind,
                "box": [float(value) for value in box],
                "name": str(item.get("name") or ""),
            }
        )
    return cleaned


def select_head_top(candidates: Iterable[dict]) -> tuple[SelectedHeadTop | None, str]:
    """优先选择唯一 head surface；缺失时才使用唯一 face surface。"""
    items = _clean_head_candidates(candidates)
    for kind in ("head_attachment", "face_attachment"):
        hits = [item for item in items if item["kind"] == kind]
        if len(hits) == 1:
            hit = hits[0]
            return SelectedHeadTop(hit["box"][1], f"{kind}:{hit['name']}"), "ok"
        if len(hits) > 1:
            return None, f"ambiguous_{kind}"
    return None, "head_top_unavailable"


def validate_axis_order(
    *,
    head_top_y: float,
    eye_y: float,
    torso_y: float | None = None,
    breast_y: float | None = None,
) -> bool:
    """验证 head → eye → upper torso 顺序，并兼容旧的 ``breast_y`` 调用。"""
    if torso_y is None:
        torso_y = breast_y
    elif breast_y is not None:
        return False
    return (
        _finite(head_top_y)
        and _finite(eye_y)
        and _finite(torso_y)
        and head_top_y <= eye_y < torso_y
    )
