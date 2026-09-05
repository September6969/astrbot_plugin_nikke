# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile dashboard data model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProfileDashboardData:
    commander_name: str
    area_id: str
    synchro_level: int | None
    outpost_battle_level: int | None
    normal_campaign: str | None
    hard_campaign: str | None
    character_count: int
    max_level: int
    max_combat: int
    fetched_at: str
    plugin_version: str
    commander_level: int | None = None
    team_combat: int | None = None
    icon_id: str | None = None
    created_at: str | None = None
    character_costume_count: int | None = None
    progress_tribe_tower: str | None = None
    sim_room_overclock_score: str | None = None
    infra_core_level: str | None = None
    tactic_academy_class: str | None = None
    tactic_academy_lesson: str | None = None
    jukebox_count: str | None = None
    recycle_room_summary: str | None = None
    memorial_summary: str | None = None
