# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile dashboard data model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RecycleResearchData:
    tid: str | None
    level: int | None
    exp: int | None
    display_name: str | None = None
    category: str | None = None


@dataclass(slots=True)
class MemorialCountData:
    category: str | None
    count: int | None


@dataclass(slots=True)
class ProfileDashboardData:
    commander_name: str
    area_id: str
    synchro_level: int | None
    outpost_battle_level: int | None
    normal_campaign: str | None
    hard_campaign: str | None
    character_count: int | None
    max_level: int | None
    max_combat: int | None
    fetched_at: str
    plugin_version: str
    commander_level: int | None = None
    team_combat: int | None = None
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
    recycle_room_researches: list[RecycleResearchData] | None = None
    memorial_counts: list[MemorialCountData] | None = None
    # None 表示调用方没有提供可选接口状态；False 表示请求或响应不可用。
    outpost_available: bool | None = None
    roster_available: bool | None = None
    roster_partial: bool = False
    research_partial: bool = False
    memorial_partial: bool = False
