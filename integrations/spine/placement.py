# SPDX-License-Identifier: GPL-3.0-or-later
"""角色定位锚点与加权钳位视觉校正 (CharacterPlacementMeta)。

核心算法：
1. 骨骼定位为主：body_anchor 首选 pelvis -> chest+pelvis 中点 -> root 兜底；
2. 视觉定位为辅：基于主体 alpha bounds 做保守的 clamped visual delta 修正；
3. 大武器/特效保护：通过 clamp 截断，绝不让外部大枪或披风严重拉偏角色视觉中心；
4. 全量坐标归一化到 [0.0, 1.0]；
5. 包含朝向 (facing: -1|0|1) 与身体主轴线 (body_axis)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("nikke.spine.placement")


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (round(self.x, 4), round(self.y, 4))


@dataclass(frozen=True, slots=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def center(self) -> Point:
        return Point((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (round(self.left, 4), round(self.top, 4), round(self.right, 4), round(self.bottom, 4))


@dataclass(slots=True)
class SkeletonAnchorSet:
    """标准骨骼锚点集合（坐标已归一化到 [0.0, 1.0]）。"""

    head: Point | None = None
    chest: Point | None = None
    pelvis: Point | None = None
    left_foot: Point | None = None
    right_foot: Point | None = None
    body_center: Point | None = None
    feet_center: Point | None = None

    def derive_feet_center(self, alpha_bottom: float | None = None) -> Point | None:
        if self.left_foot and self.right_foot:
            return Point(
                (self.left_foot.x + self.right_foot.x) / 2.0,
                (self.left_foot.y + self.right_foot.y) / 2.0,
            )
        if self.left_foot:
            return self.left_foot
        if self.right_foot:
            return self.right_foot
        if alpha_bottom is not None:
            # 兜底到 alpha bottom
            cx = self.body_center.x if self.body_center else 0.5
            return Point(cx, alpha_bottom)
        return None

    def derive_body_anchor(self, root: Point | None = None) -> Point | None:
        # pelvis 优先 -> chest + pelvis 中点 -> chest -> root 兜底
        if self.pelvis:
            return self.pelvis
        if self.chest and self.pelvis:
            return Point((self.chest.x + self.pelvis.x) / 2.0, (self.chest.y + self.pelvis.y) / 2.0)
        if self.chest:
            return self.chest
        if root:
            return root
        return None


@dataclass(slots=True)
class CharacterPlacementMeta:
    """角色最终归一化放置元数据。供后续练度卡布局与自动构图使用。"""

    resource_id: str
    costume_id: str | None = None

    head: tuple[float, float] | None = None
    chest: tuple[float, float] | None = None
    pelvis: tuple[float, float] | None = None
    feet_center: tuple[float, float] | None = None

    body_anchor: tuple[float, float] | None = None
    visual_anchor: tuple[float, float] | None = None

    alpha_bbox: tuple[float, float, float, float] | None = None
    body_bbox: tuple[float, float, float, float] | None = None

    facing: int = 0  # -1 偏左, 0 正面/居中, 1 偏右
    body_axis: tuple[tuple[float, float], tuple[float, float]] | None = None

    source: str = "cached-semantic"  # "cached-semantic" | "runtime-skeleton" | "alpha-fallback" | "center-fallback" | "manual-override"
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "costume_id": self.costume_id,
            "head": list(self.head) if self.head else None,
            "chest": list(self.chest) if self.chest else None,
            "pelvis": list(self.pelvis) if self.pelvis else None,
            "feet_center": list(self.feet_center) if self.feet_center else None,
            "body_anchor": list(self.body_anchor) if self.body_anchor else None,
            "visual_anchor": list(self.visual_anchor) if self.visual_anchor else None,
            "alpha_bbox": list(self.alpha_bbox) if self.alpha_bbox else None,
            "body_bbox": list(self.body_bbox) if self.body_bbox else None,
            "facing": self.facing,
            "body_axis": [list(self.body_axis[0]), list(self.body_axis[1])] if self.body_axis else None,
            "source": self.source,
            "confidence": round(self.confidence, 3),
        }


def compute_clamped_visual_anchor(
    body_anchor: Point,
    alpha_rect: Rect | None,
    *,
    weight_x: float = 0.30,
    weight_y: float = 0.15,
    max_offset_x: float = 0.15,
    max_offset_y: float = 0.10,
) -> Point:
    """骨骼主定位 + 钳位视觉修正算法。

    防止巨型武器或飘动披风将视觉中心过度拉偏。
    """
    if alpha_rect is None:
        return body_anchor

    alpha_center = alpha_rect.center
    delta_x = alpha_center.x - body_anchor.x
    delta_y = alpha_center.y - body_anchor.y

    # 钳位截断
    clamped_dx = max(-max_offset_x, min(max_offset_x, delta_x))
    clamped_dy = max(-max_offset_y, min(max_offset_y, delta_y))

    final_x = body_anchor.x + clamped_dx * weight_x
    final_y = body_anchor.y + clamped_dy * weight_y

    return Point(max(0.0, min(1.0, final_x)), max(0.0, min(1.0, final_y)))


def compute_placement_meta(
    resource_id: str,
    costume_id: str | None,
    semantic_bones: Mapping[str, tuple[float, float]],
    alpha_bbox_pixel: tuple[int, int, int, int] | None = None,
    viewport_size: tuple[int, int] = (1024, 1024),
    *,
    source_hint: str = "runtime-skeleton",
    confidence_base: float = 0.95,
) -> CharacterPlacementMeta:
    """计算单个角色/皮肤的标准放置元数据。"""
    vw, vh = viewport_size
    norm_alpha: Rect | None = None
    if alpha_bbox_pixel:
        l, t, r, b = alpha_bbox_pixel
        norm_alpha = Rect(
            max(0.0, min(1.0, l / vw)),
            max(0.0, min(1.0, t / vh)),
            max(0.0, min(1.0, r / vw)),
            max(0.0, min(1.0, b / vh)),
        )

    # 提取关键点
    def pt_or_none(k: str) -> Point | None:
        coords = semantic_bones.get(k)
        return Point(coords[0], coords[1]) if coords else None

    head_pt = pt_or_none("head")
    chest_pt = pt_or_none("chest")
    pelvis_pt = pt_or_none("pelvis")
    left_foot_pt = pt_or_none("left_foot")
    right_foot_pt = pt_or_none("right_foot")
    root_pt = pt_or_none("root")

    anchors = SkeletonAnchorSet(
        head=head_pt,
        chest=chest_pt,
        pelvis=pelvis_pt,
        left_foot=left_foot_pt,
        right_foot=right_foot_pt,
    )
    feet_center = anchors.derive_feet_center(norm_alpha.bottom if norm_alpha else None)
    body_anchor = anchors.derive_body_anchor(root_pt)

    source = source_hint
    confidence = confidence_base

    # 降级链：runtime-skeleton -> alpha-fallback -> center-fallback
    if body_anchor is None:
        if norm_alpha is not None:
            body_anchor = norm_alpha.center
            source = "alpha-fallback"
            confidence = 0.50
        else:
            body_anchor = Point(0.5, 0.5)
            source = "center-fallback"
            confidence = 0.20

    # 视觉校正锚点
    visual_anchor = compute_clamped_visual_anchor(body_anchor, norm_alpha)

    # 朝向推断 (facing)
    facing = 0
    if head_pt and pelvis_pt:
        dx = head_pt.x - pelvis_pt.x
        if dx < -0.05:
            facing = -1
        elif dx > 0.05:
            facing = 1

    # 身体轴线 (body_axis)
    body_axis = None
    if head_pt and pelvis_pt:
        body_axis = (head_pt.as_tuple(), pelvis_pt.as_tuple())
    elif chest_pt and pelvis_pt:
        body_axis = (chest_pt.as_tuple(), pelvis_pt.as_tuple())

    # 主体区域 bbox 估算
    body_bbox = None
    if head_pt and pelvis_pt and feet_center:
        min_x = min(head_pt.x, pelvis_pt.x, feet_center.x) - 0.15
        max_x = max(head_pt.x, pelvis_pt.x, feet_center.x) + 0.15
        min_y = head_pt.y - 0.10
        max_y = feet_center.y + 0.05
        body_bbox = Rect(max(0.0, min_x), max(0.0, min_y), min(1.0, max_x), min(1.0, max_y)).as_tuple()
    elif norm_alpha:
        body_bbox = norm_alpha.as_tuple()

    return CharacterPlacementMeta(
        resource_id=resource_id,
        costume_id=costume_id,
        head=head_pt.as_tuple() if head_pt else None,
        chest=chest_pt.as_tuple() if chest_pt else None,
        pelvis=pelvis_pt.as_tuple() if pelvis_pt else None,
        feet_center=feet_center.as_tuple() if feet_center else None,
        body_anchor=body_anchor.as_tuple() if body_anchor else None,
        visual_anchor=visual_anchor.as_tuple() if visual_anchor else None,
        alpha_bbox=norm_alpha.as_tuple() if norm_alpha else None,
        body_bbox=body_bbox,
        facing=facing,
        body_axis=body_axis,
        source=source,
        confidence=confidence,
    )
