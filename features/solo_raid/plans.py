# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭方案存储（22）：按所有者隔离，只有本人可读写自己的五队方案。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .builder import FiveTeamPlan, Member, Team


class SoloRaidPlanError(ValueError):
    """方案存储输入或数据损坏。"""


class PlanStorePort(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class SavedPlan:
    actor_id: str
    season_id: str
    season_name: str
    teams: tuple[Team, ...]
    damage_total: int | None
    saved_at: str
    damage_model_label: str = ""


class SoloRaidPlanStore:
    """方案只按用户键保存；不提供跨用户读取接口。"""

    KEY_PREFIX = "solo_raid_plan_v1:"

    def __init__(self, store: PlanStorePort, *, clock=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        text = str(actor_id or "").strip()
        if not text:
            raise SoloRaidPlanError("缺少用户标识，无法保存或读取方案")
        return f"{self.KEY_PREFIX}{text}"

    def save(self, actor_id: str, plan: FiveTeamPlan) -> SavedPlan:
        if not isinstance(plan, FiveTeamPlan):
            raise SoloRaidPlanError("只能保存五队方案")
        current = self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise SoloRaidPlanError("保存时间必须包含明确时区")
        saved_at = current.astimezone(timezone.utc).isoformat()
        payload = {
            "season_id": plan.season_id,
            "season_name": plan.season_name,
            "teams": [
                {
                    "index": team.index,
                    "members": [
                        {
                            "name_code": member.name_code,
                            "name": member.name,
                            "burst": member.burst,
                            "element": member.element,
                            "resource_id": member.resource_id,
                        }
                        for member in team.members
                    ],
                    "chain_ok": team.chain_ok,
                    "issues": list(team.issues),
                    "damage": team.damage,
                }
                for team in plan.teams
            ],
            "damage_total": plan.damage_total,
            "damage_model_label": plan.damage_model_label,
            "saved_at": saved_at,
        }
        self._store.set_setting(self._key(actor_id), payload)
        return SavedPlan(
            actor_id=str(actor_id),
            season_id=plan.season_id,
            season_name=plan.season_name,
            teams=plan.teams,
            damage_total=plan.damage_total,
            saved_at=saved_at,
            damage_model_label=plan.damage_model_label,
        )

    def load(self, actor_id: str) -> SavedPlan | None:
        raw = self._store.get_setting(self._key(actor_id), None)
        if not isinstance(raw, Mapping):
            return None
        teams_raw = raw.get("teams")
        if not isinstance(teams_raw, list):
            return None
        teams: list[Team] = []
        for row in teams_raw:
            if not isinstance(row, Mapping):
                return None
            members_raw = row.get("members")
            if not isinstance(members_raw, list):
                return None
            members = tuple(
                Member(
                    name_code=str(member.get("name_code") or ""),
                    name=str(member.get("name") or ""),
                    burst=str(member.get("burst") or ""),
                    element=str(member.get("element") or ""),
                    resource_id=str(member.get("resource_id") or ""),
                )
                for member in members_raw
                if isinstance(member, Mapping)
            )
            teams.append(
                Team(
                    index=int(row.get("index") or 0),
                    members=members,
                    chain_ok=bool(row.get("chain_ok")),
                    issues=tuple(str(item) for item in row.get("issues") or ()),
                    damage=row.get("damage") if isinstance(row.get("damage"), int) else None,
                )
            )
        return SavedPlan(
            actor_id=str(actor_id),
            season_id=str(raw.get("season_id") or ""),
            season_name=str(raw.get("season_name") or ""),
            teams=tuple(teams),
            damage_total=raw.get("damage_total") if isinstance(raw.get("damage_total"), int) else None,
            saved_at=str(raw.get("saved_at") or ""),
            damage_model_label=str(raw.get("damage_model_label") or ""),
        )

    def team(self, actor_id: str, index: int) -> Team | None:
        """按所有者读取单支队伍；索引从 1 开始。"""
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= 5:
            raise SoloRaidPlanError("队伍编号必须是 1–5")
        saved = self.load(actor_id)
        if saved is None:
            return None
        return next((team for team in saved.teams if team.index == index), None)

    def clear(self, actor_id: str) -> None:
        self._store.set_setting(self._key(actor_id), None)


__all__ = ["PlanStorePort", "SavedPlan", "SoloRaidPlanError", "SoloRaidPlanStore"]
