# SPDX-License-Identifier: GPL-3.0-or-later
"""战役历史通关阵容数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ClearLineupStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


@dataclass(slots=True)
class StageClearMember:
    tid: int
    level: int
    combat: int
    slot: int
    name_cn: str = ""
    name_en: str = ""
    resource_id: str | None = None


@dataclass(slots=True)
class StageClearRecord:
    mode: str  # NORMAL / HARD
    chapter: int
    stage_name: str
    stage_id: int
    status: ClearLineupStatus = ClearLineupStatus.AVAILABLE
    status_message: str = ""
    members: list[StageClearMember] = field(default_factory=list)
    commander_name: str = ""
    fetched_at: str = ""
    plugin_version: str = ""

    @property
    def total_combat(self) -> int:
        return sum(member.combat for member in self.members)

