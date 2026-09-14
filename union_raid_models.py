# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid data models and status definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RaidState(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLEMENT = "SETTLEMENT"
    OFFSEASON = "OFFSEASON"
    UNKNOWN = "UNKNOWN"


class BossStatus(str, Enum):
    DEFEATED = "DEFEATED"
    CURRENT = "CURRENT"
    NEXT = "NEXT"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class RaidResponseCoverage(str, Enum):
    """区分请求上下文与当前响应实际覆盖的记录范围。"""

    CURRENT_RESPONSE = "CURRENT_RESPONSE"
    PARTIAL_RANGE = "PARTIAL_RANGE"
    CONFIRMED_COMPLETE_RANGE = "CONFIRMED_COMPLETE_RANGE"
    UNKNOWN_COVERAGE = "UNKNOWN_COVERAGE"


@dataclass(slots=True)
class PreviousSeasonSummary:
    season_id: str
    season_number: int | None
    start_at: str
    end_at: str
    settled_at: str | None = None
    total_attacks: int = 0
    total_damage: int = 0
    boss_progress: str | None = None


@dataclass(slots=True)
class RaidBossData:
    boss_id: str
    name: str
    current_hp: int | None
    max_hp: int | None
    hp_percent: float | None
    cleared_percent: float | None
    status: BossStatus
    elements: list[str] = field(default_factory=list)
    icon_id: str | None = None
    monster_model_id: str | None = None


@dataclass(slots=True)
class UnionRaidOverviewData:
    guild_name: str
    difficulty: int | None
    level: int | None
    total_progress: float | None
    total_current_hp: int | None
    total_max_hp: int | None
    bosses: list[RaidBossData]
    season_end: str | None
    fetched_at: str
    plugin_version: str
    season_start: str | None = None
    response_coverage: RaidResponseCoverage = RaidResponseCoverage.UNKNOWN_COVERAGE
    partial_boss_records: bool = False
    raid_state: RaidState = RaidState.UNKNOWN
    previous_season: PreviousSeasonSummary | None = None
    current_season_name: str | None = None
    season_id: str | None = None
