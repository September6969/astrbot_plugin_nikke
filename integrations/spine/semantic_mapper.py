# SPDX-License-Identifier: GPL-3.0-or-later
"""骨骼语义映射层。

从任意命名风格的原始 Spine 骨骼树中保守推断出标准语义目标：
root, head, neck, chest, pelvis, left_shoulder, right_shoulder, left_hand, right_hand, left_foot, right_foot。

严格合同：
1. 支持 spine_bone_overrides.json 手工覆盖，优先级绝对最高；
2. 自动推断综合考虑名称 Token、拓扑层级与归一化位置，绝不凭序号硬猜；
3. 输出包含 confidence 置信度与 source 追踪标记。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    from .runtime import ParsedSkeleton
except ImportError:
    from astrbot_plugin_nikke.integrations.spine.runtime import ParsedSkeleton

logger = logging.getLogger("nikke.spine.semantics")

SEMANTIC_ROLES = (
    "root",
    "head",
    "neck",
    "chest",
    "pelvis",
    "left_shoulder",
    "right_shoulder",
    "left_hand",
    "right_hand",
    "left_foot",
    "right_foot",
)


@dataclass(frozen=True, slots=True)
class SemanticBoneMatch:
    semantic: str
    bone_name: str
    confidence: float
    source: str  # "manual" | "auto-name" | "auto-topology" | "auto-position"


class SpineSemanticMapper:
    """骨骼语义映射与推断器。"""

    def __init__(
        self,
        semantics_catalog_path: Path | str | None = None,
        overrides_path: Path | str | None = None,
    ) -> None:
        self.semantics_path = Path(semantics_catalog_path) if semantics_catalog_path else None
        self.overrides_path = Path(overrides_path) if overrides_path else None
        self._cached_semantics: dict[str, dict[str, dict]] = self._load_json(self.semantics_path)
        self._cached_overrides: dict[str, dict[str, str]] = self._load_json(self.overrides_path)

    @staticmethod
    def _load_json(path: Path | None) -> dict:
        if path and path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw.get("entries", raw)
            except Exception as exc:
                logger.warning("Failed to load semantics/overrides from %s: %s", path, exc)
        return {}

    def get_semantic_mapping(
        self,
        character_key: str,
        skeleton: ParsedSkeleton | None = None,
    ) -> dict[str, SemanticBoneMatch]:
        """获取特定角色的全部语义骨骼匹配。

        优先顺序：manual override > cached semantic > runtime auto-inference
        """
        results: dict[str, SemanticBoneMatch] = {}

        # 1. 静态缓存
        if character_key in self._cached_semantics:
            entry = self._cached_semantics[character_key]
            for sem, data in entry.items():
                if isinstance(data, dict):
                    results[sem] = SemanticBoneMatch(
                        semantic=sem,
                        bone_name=str(data.get("bone", "")),
                        confidence=float(data.get("confidence", 0.9)),
                        source=str(data.get("source", "cached")),
                    )
                elif isinstance(data, str):
                    results[sem] = SemanticBoneMatch(
                        semantic=sem,
                        bone_name=data,
                        confidence=0.9,
                        source="cached",
                    )

        # 2. 运行时骨骼自动推断（若未完全匹配且提供了 skeleton）
        if skeleton is not None:
            inferred = self.infer_semantics(skeleton)
            for sem, match in inferred.items():
                if sem not in results or results[sem].confidence < match.confidence:
                    results[sem] = match

        # 3. 手工覆盖（最高绝对优先级）
        if character_key in self._cached_overrides:
            for sem, b_name in self._cached_overrides[character_key].items():
                if b_name:
                    results[sem] = SemanticBoneMatch(
                        semantic=sem,
                        bone_name=b_name,
                        confidence=1.0,
                        source="manual",
                    )

        return results

    @classmethod
    def infer_semantics(cls, skeleton: ParsedSkeleton) -> dict[str, SemanticBoneMatch]:
        """对解析出的骨骼结构进行保守自动语义推断。"""
        norm_pts = skeleton.compute_normalized_points()
        matches: dict[str, SemanticBoneMatch] = {}

        for role in SEMANTIC_ROLES:
            match = cls._find_candidate_for_role(role, skeleton, norm_pts)
            if match is not None:
                matches[role] = match

        return matches

    @classmethod
    def _find_candidate_for_role(
        cls,
        role: str,
        skeleton: ParsedSkeleton,
        norm_pts: dict[str, tuple[float, float]],
    ) -> SemanticBoneMatch | None:
        bones = skeleton.bones
        names = [b.name for b in bones]

        # 1. Root
        if role == "root":
            for target in ("root", "all", "base"):
                if target in skeleton.bone_name_map:
                    return SemanticBoneMatch("root", target, 0.98, "auto-name")
            return SemanticBoneMatch("root", bones[0].name, 0.80, "auto-topology") if bones else None

        # 2. Head
        if role == "head":
            # 精确/前缀优先
            for n in names:
                ln = n.lower()
                if ln in ("c_head", "head", "face", "c_face", "at_head") or re.search(r"(?:^|_)head(?:_|$)", ln):
                    pt = norm_pts.get(n)
                    # 头部通常处于骨骼上部 (y < 0.45)
                    conf = 0.96 if pt and pt[1] < 0.45 else 0.88
                    return SemanticBoneMatch("head", n, conf, "auto-name")
            # 拓扑/位置次级候选
            upper_candidates = [n for n, pt in norm_pts.items() if pt[1] < 0.35 and 0.25 < pt[0] < 0.75]
            if upper_candidates:
                # 选最高的骨骼
                best = min(upper_candidates, key=lambda n: norm_pts[n][1])
                return SemanticBoneMatch("head", best, 0.65, "auto-position")

        # 3. Neck
        if role == "neck":
            for n in names:
                ln = n.lower()
                if ln in ("c_neck", "neck") or re.search(r"(?:^|_)neck(?:_|$)", ln):
                    return SemanticBoneMatch("neck", n, 0.95, "auto-name")

        # 4. Chest
        if role == "chest":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("c_breast_belt", "c_breast", "breast", "chest", "c_chest", "upper_boddy", "upper_body")):
                    pt = norm_pts.get(n)
                    conf = 0.94 if pt and 0.15 < pt[1] < 0.55 else 0.85
                    return SemanticBoneMatch("chest", n, conf, "auto-name")
            for n in names:
                ln = n.lower()
                if re.search(r"(?:^|_)spine[2-4]?(?:_|$)", ln):
                    return SemanticBoneMatch("chest", n, 0.82, "auto-name")

        # 5. Pelvis / Hip / Lower Body
        if role == "pelvis":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("lower_boddy", "lower_body", "pelvis", "c_pelvis", "hip", "c_hip", "waist")):
                    pt = norm_pts.get(n)
                    conf = 0.94 if pt and 0.30 < pt[1] < 0.70 else 0.86
                    return SemanticBoneMatch("pelvis", n, conf, "auto-name")

        # 6. Left Foot & Right Foot
        if role == "left_foot":
            for n in names:
                ln = n.lower()
                if (
                    any(kw in ln for kw in ("c_foot_l", "foot_l", "c_ankle_l", "leg_l", "c_calf_l"))
                    and not any(neg in ln for neg in ("r2", "weapon", "shadow"))
                ):
                    pt = norm_pts.get(n)
                    conf = 0.93 if pt and pt[1] > 0.60 else 0.80
                    return SemanticBoneMatch("left_foot", n, conf, "auto-name")

        if role == "right_foot":
            for n in names:
                ln = n.lower()
                if (
                    any(kw in ln for kw in ("c_foot_r", "foot_r", "c_ankle_r", "leg_r", "c_calf_r"))
                    and not any(neg in ln for neg in ("l2", "weapon", "shadow"))
                ):
                    pt = norm_pts.get(n)
                    conf = 0.93 if pt and pt[1] > 0.60 else 0.80
                    return SemanticBoneMatch("right_foot", n, conf, "auto-name")

        # 7. Shoulders & Hands
        if role == "left_shoulder":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("c_shoulder_l", "shoulder_l", "c_arm_up_l", "arm_up_l")):
                    return SemanticBoneMatch("left_shoulder", n, 0.90, "auto-name")

        if role == "right_shoulder":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("c_shoulder_r", "shoulder_r", "c_arm_up_r", "arm_up_r")):
                    return SemanticBoneMatch("right_shoulder", n, 0.90, "auto-name")

        if role == "left_hand":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("c_hand_l", "hand_l")):
                    return SemanticBoneMatch("left_hand", n, 0.90, "auto-name")

        if role == "right_hand":
            for n in names:
                ln = n.lower()
                if any(kw in ln for kw in ("c_hand_r", "hand_r")):
                    return SemanticBoneMatch("right_hand", n, 0.90, "auto-name")

        return None
