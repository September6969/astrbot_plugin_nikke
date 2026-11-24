# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭五队编组（22）：全局去重、爆裂链检查与配置化伤害估算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .seasons import Boss, Season

TEAM_COUNT = 5
TEAM_SIZE = 5
BURST_ORDER = {"Step1": 1, "Step2": 2, "Step3": 3, "AllStep": 0}
BURST_LABELS = {"Step1": "B1", "Step2": "B2", "Step3": "B3", "AllStep": "全阶"}
NO_DAMAGE_NOTE = "缺少可靠伤害公式：不估算伤害（未使用猜测系数）。"
ESTIMATE_NOTE = "配置化估算：由运营者提供的系数计算，非官方伤害公式。"


class SoloRaidError(ValueError):
    """成员或配置不合法。"""


@dataclass(frozen=True, slots=True)
class Member:
    name_code: str
    name: str
    burst: str
    element: str = ""
    resource_id: str = ""


@dataclass(frozen=True, slots=True)
class Team:
    index: int
    members: tuple[Member, ...]
    chain_ok: bool
    issues: tuple[str, ...] = ()
    damage: int | None = None

    @property
    def stages(self) -> tuple[str, ...]:
        return tuple(BURST_LABELS.get(member.burst, "?") for member in self.members)


@dataclass(frozen=True, slots=True)
class FiveTeamPlan:
    season_id: str
    season_name: str
    teams: tuple[Team, ...]
    unused: tuple[Member, ...]
    issues: tuple[str, ...]
    damage_total: int | None
    damage_model_label: str
    estimate_note: str

    @property
    def chain_ok(self) -> bool:
        return all(team.chain_ok for team in self.teams)

    def to_dict(self) -> dict[str, Any]:
        return {
            "season_id": self.season_id,
            "season_name": self.season_name,
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
                for team in self.teams
            ],
            "issues": list(self.issues),
            "damage_total": self.damage_total,
            "damage_model_label": self.damage_model_label,
        }


def parse_members(text: str) -> tuple[Member, ...]:
    """解析手工角色池：``名称`` 或 ``名称:B1``，逗号/顿号/斜杠分隔。"""
    normalized = str(text or "")
    for separator in ("，", "、", "/", "\n", ";"):
        normalized = normalized.replace(separator, ",")
    members: list[Member] = []
    seen: set[str] = set()
    for position, chunk in enumerate(part.strip() for part in normalized.split(",")):
        if not chunk:
            continue
        burst = ""
        name = chunk
        for separator in (":", "："):
            if separator in chunk:
                name, _, tail = chunk.rpartition(separator)
                burst = tail.strip().upper()
                break
        burst_map = {"B1": "Step1", "B2": "Step2", "B3": "Step3", "STEP1": "Step1", "STEP2": "Step2", "STEP3": "Step3"}
        burst = burst_map.get(burst, burst if burst in BURST_ORDER else "")
        key = name.strip().casefold()
        if not key:
            raise SoloRaidError("角色池存在空名称")
        if key in seen:
            raise SoloRaidError(f"角色池重复：{name.strip()}")
        seen.add(key)
        members.append(
            Member(
                name_code=str(position + 1),
                name=name.strip(),
                burst=burst,
                element="",
                resource_id="",
            )
        )
    return tuple(members)


def members_from_roster(rows: Iterable[Mapping[str, Any]]) -> tuple[Member, ...]:
    """从已绑定角色名单构造成员；缺少爆裂阶段时保留未知，不猜测。"""
    members: list[Member] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("name_code") or row.get("character_key") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        members.append(
            Member(
                name_code=code,
                name=str(row.get("name_zh_cn") or row.get("name_zh_tw") or row.get("name_cn") or code),
                burst=str(row.get("burst") or ""),
                element=str(row.get("element") or ""),
                resource_id=str(row.get("resource_id") or ""),
            )
        )
    return tuple(members)


def _stage_set(members: Sequence[Member]) -> set[str]:
    stages = {member.burst for member in members if member.burst in {"Step1", "Step2", "Step3"}}
    if any(member.burst == "AllStep" for member in members):
        # 全阶角色可补任意一个缺失定位，但不能凭空补齐全部。
        missing = {"Step1", "Step2", "Step3"} - stages
        stages |= set(sorted(missing)[:1])
    return stages


def check_burst_chain(members: Sequence[Member]) -> tuple[bool, tuple[str, ...]]:
    """爆裂链需要同时具备 B1/B2/B3；缺失定位逐项说明。"""
    stages = _stage_set(members)
    missing = [BURST_LABELS[stage] for stage in ("Step1", "Step2", "Step3") if stage not in stages]
    if not members:
        return False, ("队伍为空",)
    return (not missing, tuple(f"缺少 {label}" for label in missing))


def _boss_weakness_element(season: Season | None) -> str:
    if season is None or not season.bosses:
        return ""
    return str(season.bosses[0].element or "").strip().casefold()


def build_five_teams(
    members: Iterable[Member],
    *,
    season: Season | None = None,
    damage_model: Mapping[str, Any] | None = None,
) -> FiveTeamPlan:
    """按 B1/B2/B3 定位确定性编成五队；全员全局去重。"""
    unique: dict[str, Member] = {}
    for member in members:
        if not isinstance(member, Member):
            raise SoloRaidError("成员必须是 Member")
        unique.setdefault(member.name_code, member)
    pool = sorted(unique.values(), key=lambda item: (BURST_ORDER.get(item.burst, 9), item.name_code))
    weakness = _boss_weakness_element(season)

    def elemental_priority(member: Member) -> int:
        return 0 if weakness and member.element.casefold() == weakness else 1

    buckets: dict[str, list[Member]] = {"Step1": [], "Step2": [], "Step3": [], "AllStep": []}
    for member in pool:
        buckets.setdefault(member.burst, []).append(member)
    for key in buckets:
        buckets[key].sort(key=lambda item: (elemental_priority(item), item.name_code))

    used: set[str] = set()

    def take(stage: str) -> Member | None:
        for candidate in buckets.get(stage, []):
            if candidate.name_code not in used:
                used.add(candidate.name_code)
                return candidate
        return None

    teams: list[Team] = []
    issues: list[str] = []
    # 先为五队各保留 B1/B2/B3，避免元素优先的补位提前吃掉后续队伍必需定位。
    reserved_members: list[list[Member]] = []
    reserved_issues: list[list[str]] = []
    for index in range(1, TEAM_COUNT + 1):
        members_team: list[Member] = []
        team_issues: list[str] = []
        for stage, label in (("Step1", "B1"), ("Step2", "B2"), ("Step3", "B3")):
            picked = take(stage)
            if picked is None:
                # 全阶角色可作为缺口的候选补充。
                picked = take("AllStep")
            if picked is None:
                team_issues.append(f"缺少 {label} 定位")
            else:
                members_team.append(picked)
        reserved_members.append(members_team)
        reserved_issues.append(team_issues)

    role_priority = {"Step3": 0, "AllStep": 1, "Step2": 2, "Step1": 3}
    for index, members_team in enumerate(reserved_members, 1):
        team_issues = list(reserved_issues[index - 1])
        remaining = sorted(
            (member for member in pool if member.name_code not in used),
            key=lambda item: (
                role_priority.get(item.burst, 4),
                elemental_priority(item),
                item.name_code,
            ),
        )
        for member in remaining:
            if len(members_team) >= TEAM_SIZE:
                break
            if member.name_code in used:
                continue
            used.add(member.name_code)
            members_team.append(member)
        chain_ok, chain_issues = check_burst_chain(members_team)
        if chain_issues:
            team_issues.extend(chain_issues)
        if len(members_team) < TEAM_SIZE:
            team_issues.append(f"人数不足（{len(members_team)}/5）")
        if team_issues:
            issues.append(f"第 {index} 队：" + "；".join(dict.fromkeys(team_issues)))
        teams.append(
            Team(
                index=index,
                members=tuple(members_team),
                chain_ok=chain_ok,
                issues=tuple(dict.fromkeys(team_issues)),
            )
        )

    total: int | None
    label = ""
    note = NO_DAMAGE_NOTE
    if damage_model:
        per_member = damage_model.get("per_member")
        chain_bonus = damage_model.get("chain_bonus", 0)
        if (
            isinstance(per_member, bool)
            or not isinstance(per_member, int)
            or per_member < 0
            or isinstance(chain_bonus, bool)
            or not isinstance(chain_bonus, int)
            or chain_bonus < 0
        ):
            raise SoloRaidError("伤害估算系数必须是非负整数")
        label = str(damage_model.get("label") or "配置化估算")
        total = 0
        computed: list[Team] = []
        for team in teams:
            damage = per_member * len(team.members) + (chain_bonus if team.chain_ok else 0)
            total += damage
            computed.append(Team(team.index, team.members, team.chain_ok, team.issues, damage))
        teams = computed
        note = ESTIMATE_NOTE
    else:
        total = None

    unused = tuple(member for member in pool if member.name_code not in used)
    return FiveTeamPlan(
        season_id=season.season_id if season else "",
        season_name=season.name if season else "未选择赛季",
        teams=tuple(teams),
        unused=unused,
        issues=tuple(issues),
        damage_total=total,
        damage_model_label=label,
        estimate_note=note,
    )


def render_plan(plan: FiveTeamPlan, *, boss: Boss | None = None) -> str:
    """渲染五队方案；伤害无法估算时给出明确说明。"""
    lines = [f"【单人突袭 · 五队】{plan.season_name}"]
    if boss is not None:
        lines.append(f"首领：{boss.name} · 弱点：{boss.weakness}" + (f" · 属性：{boss.element}" if boss.element else ""))
    lines.append(f"爆裂链：{'全部通过' if plan.chain_ok else '存在缺口（见下）'}")
    for team in plan.teams:
        members = " / ".join(
            f"{member.name}（{BURST_LABELS.get(member.burst, '?')}）" for member in team.members
        ) or "（空）"
        suffix = ""
        if team.damage is not None:
            suffix = f" · 估算 {team.damage:,}"
        lines.append(f"第 {team.index} 队：{members}{suffix}")
        if team.issues:
            lines.append("  问题：" + "；".join(team.issues))
    if plan.damage_total is None:
        lines.append("伤害：" + (plan.estimate_note or NO_DAMAGE_NOTE))
    else:
        lines.append(f"伤害：{plan.damage_total:,}（{plan.damage_model_label}）")
        if plan.estimate_note:
            lines.append(plan.estimate_note)
    if plan.unused:
        lines.append("未上场：" + "、".join(member.name for member in plan.unused))
    if plan.issues:
        lines.append("")
        lines.extend(f"· {issue}" for issue in plan.issues)
    return "\n".join(lines)


__all__ = [
    "BURST_LABELS",
    "FiveTeamPlan",
    "Member",
    "NO_DAMAGE_NOTE",
    "SoloRaidError",
    "TEAM_COUNT",
    "TEAM_SIZE",
    "Team",
    "build_five_teams",
    "check_burst_chain",
    "members_from_roster",
    "parse_members",
    "render_plan",
]
