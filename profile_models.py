# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile dashboard data model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CurrencyItem:
    """已解析的账号资源；value 保留底层整数，compact_value 只用于展示。"""

    type: int
    value: int | None
    display_name: str
    icon_key: str | None
    compact_value: str


@dataclass(slots=True)
class DailyTowerInfo:
    """每日塔记录的结构化包装，同时保留未知字段供离线审计。"""

    raw: dict[str, Any]
    display_name: str | None = None
    remaining: int | None = None
    tower_type: int | None = None
    is_opened: bool | None = None


@dataclass(slots=True)
class SimulationRoomDailyRecord:
    """模拟室每日最佳记录；chapter/difficulty 未确认时保持未知。"""

    chapter: int | None
    difficulty: int | None
    raw: dict[str, Any]
    score: int | None = None

    @property
    def display_label(self) -> str:
        if self.chapter is None or self.difficulty is None:
            return "—"
        chapter_label = {1: "A", 2: "B", 3: "C"}.get(self.chapter)
        return f"{self.difficulty}-{chapter_label}" if chapter_label else "—"


@dataclass(slots=True)
class RecycleResearchData:
    tid: str | None
    level: int | None
    exp: int | None
    display_name: str | None = None
    category: str | None = None
    presentation_name: str | None = None


@dataclass(slots=True)
class MemorialCountData:
    category: str | None
    count: int | None
    display_name: str | None = None
    group: str | None = None


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
    memorial_summary: list[MemorialCountData] | None = None
    recycle_room_researches: list[RecycleResearchData] | None = None
    memorial_counts: list[MemorialCountData] | None = None
    # None 表示调用方没有提供可选接口状态；False 表示请求或响应不可用。
    outpost_available: bool | None = None
    roster_available: bool | None = None
    roster_partial: bool = False
    research_partial: bool = False
    memorial_partial: bool = False
    daily_available: bool | None = None
    storage_fullness: float | None = None
    intercept_remaining: int | None = None
    rookie_arena_remaining: int | None = None
    special_arena_remaining: int | None = None
    counsel_remaining: int | None = None
    dispatch_completed: int | None = None
    dispatch_in_progress: int | None = None
    tower_daily_info: list[DailyTowerInfo] | None = None
    sim_room_daily_record: SimulationRoomDailyRecord | None = None
    sim_room_overclock_subseason: str | None = None
    sim_room_overclock_season: str | None = None
    currencies: list[CurrencyItem] | None = None
    currencies_partial: bool = False
    daily_partial: bool = False
