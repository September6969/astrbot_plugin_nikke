# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid data models and status definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BossStatus(str, Enum):
    DEFEATED = "DEFEATED"
    CURRENT = "CURRENT"
    NEXT = "NEXT"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


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
    difficulty: int
    level: int
    total_progress: float | None
    total_current_hp: int | None
    total_max_hp: int | None
    bosses: list[RaidBossData]
    season_end: str | None
    fetched_at: str
    plugin_version: str
    season_start: str | None = None