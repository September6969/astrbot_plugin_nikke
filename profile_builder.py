# SPDX-License-Identifier: GPL-3.0-or-later
"""Build ProfileDashboardData from raw API responses."""

from __future__ import annotations

from typing import Any

from .profile_models import ProfileDashboardData


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


class ProfileBuilder:
    def build(
        self,
        *,
        account: dict[str, Any],
        basic: dict[str, Any],
        outpost: dict[str, Any],
        roster: list[dict[str, Any]] | None,
        fetched_at: str,
        plugin_version: str,
    ) -> ProfileDashboardData:
        commander_name = str(
            basic.get("nickname")
            or account.get("nickname")
            or account.get("role_name")
            or "指挥官"
        )
        area_id = str(account.get("area_id", ""))

        synchro_raw = outpost.get("synchro_level")
        synchro_level = int(synchro_raw) if synchro_raw not in (None, "") else None

        outpost_raw = outpost.get("outpost_battle_level")
        outpost_battle_level = int(outpost_raw) if outpost_raw not in (None, "") else None

        normal_campaign = str(
            basic.get("progress_normal_campaign")
            or basic.get("progress_campaign_normal")
            or ""
        ).strip() or None

        hard_campaign = str(
            basic.get("progress_hard_campaign")
            or basic.get("progress_campaign_hard")
            or ""
        ).strip() or None

        basic_count = _optional_int(basic.get("character_count"))
        if basic_count is not None:
            character_count = basic_count
        elif roster is not None:
            character_count = len(roster)
        else:
            character_count = None

        if roster:
            max_level = max(int(c.get("lv", 0) or 0) for c in roster)
            max_combat = max(int(c.get("combat", 0) or 0) for c in roster)
        else:
            max_level = None
            max_combat = None

        commander_level = _optional_int(basic.get("lv"))
        team_combat_raw = basic.get("team_combat")
        team_combat = int(team_combat_raw) if team_combat_raw not in (None, "") else None
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

        recycle_room_summary = None
        researches = outpost.get("recycle_room_researches")
        if isinstance(researches, list):
            levels = [
                int(item.get("lv", 0) or 0)
                for item in researches
                if isinstance(item, dict)
            ]
            recycle_room_summary = f"{len(levels)} 项 · 等级合计 {sum(levels)}"

        memorial_summary = None
        memorials = outpost.get("memorial_counts")
        if isinstance(memorials, list):
            count = sum(
                int(item.get("count", 0) or 0)
                for item in memorials
                if isinstance(item, dict)
            )
            memorial_summary = str(count)

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
            recycle_room_summary=recycle_room_summary,
            memorial_summary=memorial_summary,
        )
