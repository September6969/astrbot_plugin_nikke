# SPDX-License-Identifier: GPL-3.0-or-later
"""从受控响应构建 ProfileDashboardData。"""

from __future__ import annotations

import re
from typing import Any

from .profile_models import MemorialCountData, ProfileDashboardData, RecycleResearchData
from .research_registry import research_labels


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_MAX_INTEGER_DIGITS = 12


def _optional_int(value: Any) -> int | None:
    """只接受整数或已确认的十进制整数字符串，不把浮点数截断。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or not _INTEGER_RE.fullmatch(text):
            return None
        if len(text.lstrip("+-")) > _MAX_INTEGER_DIGITS:
            return None
        try:
            candidate = int(text)
        except ValueError:
            return None
    else:
        return None
    if candidate < 0 or len(str(candidate)) > _MAX_INTEGER_DIGITS:
        return None
    return candidate


def _optional_str(value: Any, *, max_length: int = 200) -> str | None:
    """仅把标量转换为显示文本，拒绝容器 repr 和控制字符。"""
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    text = text.strip()
    return text[:max_length] or None


def _first_optional_str(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in source:
            value = _optional_str(source[key])
            if value is not None:
                return value
    return None


def _parse_researches(value: Any) -> tuple[list[RecycleResearchData] | None, bool]:
    if not isinstance(value, list):
        return None, False
    rows: list[RecycleResearchData] = []
    partial = False
    for item in value:
        if not isinstance(item, dict):
            # 保留列表位置，但不给坏条目补内部 ID 或数值。
            rows.append(RecycleResearchData(None, None, None))
            partial = True
            continue
        tid = _optional_str(item.get("tid"))
        level = _optional_int(item.get("lv"))
        exp = _optional_int(item.get("exp"))
        if any(key not in item for key in ("tid", "lv", "exp")):
            partial = True
        if "tid" in item and tid is None:
            partial = True
        if ("lv" in item and level is None) or ("exp" in item and exp is None):
            partial = True
        display_name, category = research_labels(tid)
        rows.append(RecycleResearchData(tid, level, exp, display_name, category))
    return rows, partial


def _parse_memorials(value: Any) -> tuple[list[MemorialCountData] | None, bool]:
    if not isinstance(value, list):
        return None, False
    rows: list[MemorialCountData] = []
    partial = False
    for item in value:
        if not isinstance(item, dict):
            rows.append(MemorialCountData(None, None))
            partial = True
            continue
        category = _optional_str(item.get("category"))
        count = _optional_int(item.get("count"))
        # category 不做未经证实的名称映射；缺失时由 renderer 使用中性名称。
        if "count" not in item or count is None:
            partial = True
        rows.append(MemorialCountData(category, count))
    return rows, partial


class ProfileBuilder:
    def build(
        self,
        *,
        account: dict[str, Any],
        basic: dict[str, Any],
        outpost: dict[str, Any],
        roster: list[Any] | None,
        fetched_at: str,
        plugin_version: str,
        outpost_available: bool | None = None,
        roster_available: bool | None = None,
    ) -> ProfileDashboardData:
        commander_name = (
            _optional_str(basic.get("nickname"))
            or _first_optional_str(account, "nickname", "role_name")
            or "指挥官"
        )
        area_id = _optional_str(account.get("area_id")) or ""

        synchro_level = _optional_int(outpost.get("synchro_level"))
        outpost_battle_level = _optional_int(outpost.get("outpost_battle_level"))

        normal_campaign = _first_optional_str(
            basic, "progress_normal_campaign", "progress_campaign_normal"
        )
        hard_campaign = _first_optional_str(
            basic, "progress_hard_campaign", "progress_campaign_hard"
        )

        basic_count = _optional_int(basic.get("character_count"))
        roster_partial = False
        valid_roster: list[tuple[int, int]] = []
        if roster is not None:
            for item in roster:
                if not isinstance(item, dict):
                    roster_partial = True
                    continue
                level = _optional_int(item.get("lv"))
                combat = _optional_int(item.get("combat"))
                if level is None or combat is None:
                    roster_partial = True
                    continue
                valid_roster.append((level, combat))

        if basic_count is not None:
            character_count = basic_count
        elif roster is not None and not roster_partial:
            character_count = len(roster)
        else:
            character_count = None

        if roster is not None and roster and not roster_partial and valid_roster:
            max_level = max(level for level, _ in valid_roster)
            max_combat = max(combat for _, combat in valid_roster)
        else:
            max_level = None
            max_combat = None

        commander_level = _optional_int(basic.get("lv"))
        team_combat = _optional_int(basic.get("team_combat"))
        created_at = _optional_str(basic.get("created_at"))
        character_costume_count = _optional_int(basic.get("character_costume_count"))
        progress_tribe_tower = _optional_str(basic.get("progress_tribe_tower"))
        sim_room_overclock_score = _optional_str(
            basic.get("sim_room_overclock_current_sub_season_high_score")
        )

        infra_core_level = _optional_str(outpost.get("infra_core_level"))
        tactic_academy_class = _optional_str(outpost.get("tactic_academy_class"))
        tactic_academy_lesson = _optional_str(outpost.get("tactic_academy_lesson"))
        jukebox_count = _optional_str(outpost.get("jukebox_count"))

        research_data, research_partial = _parse_researches(
            outpost.get("recycle_room_researches")
        )
        memorial_data, memorial_partial = _parse_memorials(outpost.get("memorial_counts"))

        return ProfileDashboardData(
            commander_name=commander_name,
            area_id=area_id,
            synchro_level=synchro_level,
            outpost_battle_level=outpost_battle_level,
            normal_campaign=normal_campaign,
            hard_campaign=hard_campaign,
            character_count=character_count,
            max_level=max_level,
            max_combat=max_combat,
            fetched_at=fetched_at,
            plugin_version=plugin_version,
            commander_level=commander_level,
            team_combat=team_combat,
            created_at=created_at,
            character_costume_count=character_costume_count,
            progress_tribe_tower=progress_tribe_tower,
            sim_room_overclock_score=sim_room_overclock_score,
            infra_core_level=infra_core_level,
            tactic_academy_class=tactic_academy_class,
            tactic_academy_lesson=tactic_academy_lesson,
            jukebox_count=jukebox_count,
            # 摘要字段保留兼容性，但不再从可能部分的明细推导总数。
            recycle_room_summary=None,
            memorial_summary=None,
            recycle_room_researches=research_data,
            memorial_counts=memorial_data,
            outpost_available=outpost_available,
            roster_available=roster_available,
            roster_partial=roster_partial,
            research_partial=research_partial,
            memorial_partial=memorial_partial,
        )
