"""Spine 角色默认 Idle 动画解析器；严格解析站姿/待机动画，拒绝战斗/瞄准/受击并 fail-closed。"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger("astrbot_plugin_nikke.idle_animation_resolver")


class IdleAnimationResolver:
    """确定性解析 Spine 骨骼的待机/Idle 动画名。"""

    DEFAULT_IDLE_ANIMATION = "idle"

    # 优先匹配的待机/站立语义词（按优先级降序）
    STANDBY_TOKENS: tuple[str, ...] = (
        "idle",
        "standby",
        "standing",
        "wait",
        "stay",
    )

    # 严禁作为静态立绘的动作/战斗/过渡/受击/交互动画词
    REJECT_TOKENS: tuple[str, ...] = (
        "aim",
        "fire",
        "shoot",
        "attack",
        "reload",
        "skill",
        "burst",
        "hit",
        "damage",
        "die",
        "death",
        "faint",
        "walk",
        "run",
        "talk",
        "touch",
        "action",
        "enter",
        "exit",
        "end",
        "intro",
        "out",
        "event",
    )

    # 仅针对局部/面部的叠加轨道，不能作为全身主待机动画
    FACIAL_ONLY_TOKENS: frozenset[str] = frozenset(
        {
            "idle_mouth",
            "idle_mouthw",
            "idle_mouth_w",
            "mouth",
            "face",
            "eye",
            "eyes",
        }
    )

    # 权威资产已验证的默认 idle 动画名（优先于通用探测）
    VERIFIED_ASSET_IDLE_MAP: dict[str, str] = {
        "c010": "idle",
        "c010_01": "idle",
        "c010_02": "idle",
        "c010_03": "idle",
    }

    @classmethod
    def resolve_from_animation_list(cls, animations: Sequence[str]) -> str | None:
        """从骨骼实际包含的动画名列表中确定性筛选主 Idle 动画。

        规则：
        1. 存在完全匹配的 "idle" 时直接命中。
        2. 排除所有包含战斗、瞄准、装填、技能、受击、死亡、移动、说话、点击等动作词的条目。
        3. 排除仅控制面部/嘴型的子轨道（如 idle_mouth）。
        4. 必须包含或匹配待机语义词 (idle, standby, standing, wait, stay)。
        5. 按语义优先级、前缀匹配及字典序确定性决胜。
        6. 未发现任何合规待机动画时返回 None，严禁盲选首个动画或回退到战斗动作。
        """
        if not animations:
            return None

        normalized = [str(anim).strip() for anim in animations if isinstance(anim, str) and str(anim).strip()]
        if not normalized:
            return None

        # 1. 精确匹配最高优先级 "idle"
        for anim in normalized:
            if anim.lower() == "idle":
                return anim

        # 2. 候选过滤
        candidates: list[str] = []
        for anim in normalized:
            if not re.fullmatch(r"[a-zA-Z0-9_.-]+", anim):
                continue
            lower = anim.lower()
            if lower in cls.FACIAL_ONLY_TOKENS:
                continue
            if any(reject in lower for reject in cls.REJECT_TOKENS):
                continue
            if any(token in lower for token in cls.STANDBY_TOKENS):
                candidates.append(anim)

        if not candidates:
            logger.warning(
                "Spine 动画列表 %s 中未找到有效的待机/idle 动画，严禁静默盲选动作动画",
                normalized,
            )
            return None

        # 3. 确定性排序：优先完全匹配 STANDBY_TOKENS 顺位，其次前缀匹配，最后字母序
        def sort_key(name: str) -> tuple[int, int, str]:
            low = name.lower()
            # 顺位 1: 完全等于 STANDBY_TOKENS 中的某一项
            for idx, token in enumerate(cls.STANDBY_TOKENS):
                if low == token:
                    return (0, idx, low)
            # 顺位 2: 前缀匹配 STANDBY_TOKENS (例如 idle_01, standing_loop)
            for idx, token in enumerate(cls.STANDBY_TOKENS):
                if low.startswith(token):
                    return (1, idx, low)
            # 顺位 3: 包含 STANDBY_TOKENS
            for idx, token in enumerate(cls.STANDBY_TOKENS):
                if token in low:
                    return (2, idx, low)
            return (3, 99, low)

        candidates.sort(key=sort_key)
        return candidates[0]

    @classmethod
    def resolve_for_asset(
        cls,
        asset_id: str,
        available_animations: Sequence[str] | None = None,
    ) -> str | None:
        """为特定角色/资产解析 Idle 动画名。

        - 若提供了实际骨骼动画列表，必须由列表确定性检验。
        - 若未提供骨骼动画列表，优先查询已验证资产表。
        - 未在已验证表中的常规资产默认返回通用 "idle"。
        """
        if available_animations is not None:
            resolved = cls.resolve_from_animation_list(available_animations)
            if resolved is None:
                logger.warning(
                    "资产 [%s] 提供的骨骼动画未匹配到任何合规 idle 动画，返回 None 以触发中性占位图",
                    asset_id,
                )
            return resolved

        normalized_id = str(asset_id).strip().lower() if asset_id else ""
        if normalized_id in cls.VERIFIED_ASSET_IDLE_MAP:
            return cls.VERIFIED_ASSET_IDLE_MAP[normalized_id]

        return cls.DEFAULT_IDLE_ANIMATION

    @classmethod
    def inspect_skeleton_animations(cls, skeleton_path: Path) -> list[str] | None:
        """从本地 skeleton 文件解析动画列表（支持 JSON 与 skel 二进制嗅探）。"""
        if not skeleton_path.is_file():
            return None
        suffix = skeleton_path.suffix.lower()
        if suffix == ".json":
            try:
                data = json.loads(skeleton_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    anims = data.get("animations")
                    if isinstance(anims, dict):
                        return list(anims.keys())
            except (OSError, ValueError):
                return None
        elif suffix == ".skel":
            try:
                content = skeleton_path.read_bytes()
                strings = re.findall(rb"[a-zA-Z0-9_.-]{2,50}", content)
                decoded = [s.decode("ascii", errors="ignore") for s in strings]
                found = []
                seen = set()
                for s in decoded:
                    low = s.lower()
                    if (
                        any(token in low for token in cls.STANDBY_TOKENS)
                        or any(reject in low for reject in cls.REJECT_TOKENS)
                    ):
                        if s not in seen:
                            seen.add(s)
                            found.append(s)
                return found if found else None
            except OSError:
                return None
        return None
