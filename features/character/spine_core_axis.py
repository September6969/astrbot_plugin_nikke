"""离线 Spine 骨骼与表面候选的保守选择器。"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable


@dataclass(frozen=True)
class SelectedPoint:
    point: tuple[float, float]
    source: str


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
        ), "ok"
    if len(complete_pairs) > 1:
        return None, "ambiguous_breast_pairs"

    for accepted in _SINGLE_PRIORITIES:
        hits = [bone for bone in bones if bone["name"] in accepted]
        if len(hits) == 1:
            hit = hits[0]
            return SelectedPoint((hit["x"], hit["y"]), f"single:{hit['raw_name']}"), "ok"
        if len(hits) > 1:
            return None, "ambiguous_breast_single"

    return None, "breast_unavailable"


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


def validate_axis_order(*, head_top_y: float, eye_y: float, breast_y: float) -> bool:
    """验证头顶不高于眼睛，眼睛严格位于胸部之上。"""
    return (
        _finite(head_top_y)
        and _finite(eye_y)
        and _finite(breast_y)
        and head_top_y <= eye_y < breast_y
    )
