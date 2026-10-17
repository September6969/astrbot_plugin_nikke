"""突袭展示分析：保留可核实数值，不把未知覆盖当成完整战况。"""
from copy import deepcopy
from dataclasses import dataclass
from math import ceil

from .participants import RaidAttackData, RaidRankingData, RaidParticipantSummary, build_ranking, integer, scope_label


@dataclass
class AttendanceEvidence:
    """由已验证的数据提供者显式提供完整性，不能仅凭名单存在推断。"""
    roster_season: str
    roster_day: int
    members: dict[str, str]
    attack_season: str
    attack_day: int
    roster_complete: bool
    attacks_complete: bool


def analyze(payload, *, member_id=None, season_id=None, historical=False, attendance=None):
    rows = payload.get("participate_data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("攻击记录暂不可用")
    scope = "LAST_SEASON" if historical else "CURRENT_RESPONSE"
    data = RaidRankingData([], scope=scope + ("_MEMBER" if member_id is not None else ""), season_id=season_id)
    groups, attacked = {}, set()
    for row in rows:
        try:
            if not isinstance(row, dict) or not isinstance(row.get("openid"), str) or not row["openid"].strip():
                raise ValueError("缺少成员身份")
            damage = integer(row.get("total_damage"))
        except ValueError:
            data.excluded_records += 1
            data.incomplete = True
            continue
        who = row["openid"]
        attacked.add(who)
        if member_id is not None and who != member_id:
            continue
        try:
            record = build_ranking({"participate_data": [row]}).participants[0].attacks[0]
        except (ValueError, TypeError, KeyError):
            def known_number(key):
                try:
                    return integer(row.get(key))
                except ValueError:
                    return None
            final_hit = row.get("is_final_hit")
            if type(final_hit) is not bool:
                final_hit = None
            record = RaidAttackData(str(row.get("boss_id") or ""), known_number("day"),
                known_number("difficulty"), known_number("level"), known_number("step"),
                damage, final_hit, [], details_complete=False)
        participant = groups.setdefault(who, RaidParticipantSummary(str(row.get("nickname") or "成员")))
        participant.attacks.append(record)
        participant.total_damage += damage
    data.participants = sorted(groups.values(), key=lambda p: -p.total_damage)
    previous, rank = None, 0
    for index, participant in enumerate(data.participants, 1):
        if participant.total_damage != previous:
            rank = index
        participant.rank = rank
        previous = participant.total_damage
    data.total_damage = sum(p.total_damage for p in data.participants)
    data.total_records = sum(len(p.attacks) for p in data.participants)
    if attendance is not None:
        e = attendance
        complete = (e.roster_complete and e.attacks_complete and not data.incomplete
            and bool(e.roster_season) and e.roster_season == e.attack_season
            and type(e.roster_day) is int and e.roster_day >= 0 and e.roster_day == e.attack_day
            and bool(e.members) and all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in e.members.items())
            and all(isinstance(r, dict) and type(r.get("day")) is int and r["day"] == e.attack_day for r in rows))
        if complete:
            data.coverage_complete = True
            data.unattacked = [name for who, name in e.members.items() if who not in attacked]
            data.attendance_status = "HAS_UNATTACKED" if data.unattacked else "ALL_ATTACKED"
    return data


def paginate(data, page=1, *, member=False):
    """分页只裁切明细，保留整个查询范围的汇总与分母。"""
    size = 5 if member else 15
    count = sum(len(p.attacks) for p in data.participants) if member else len(data.participants)
    pages = max(1, ceil(count / size))
    if type(page) is not int or not 1 <= page <= pages:
        raise ValueError(f"页码应为 1–{pages}；用法：/妮姬 突袭 {'我的' if member else '排名'} [页码]")
    result = deepcopy(data)
    result.page, result.total_pages = page, pages
    start = (page - 1) * size
    if member:
        for p in result.participants:
            p.attacks = sorted(p.attacks, key=lambda a: (a.day is None, a.day or 0))[start:start + size]
    else:
        result.participants = result.participants[start:start + size]
    return result



def format_dashboard(data):
    from .participants import format_compact_number
    lines = [f"【{data.guild_name} · 联盟突袭】", f"更新：{data.fetched_at}"]
    if data.current_season_name:
        lines.append(data.current_season_name)
    for boss in data.bosses:
        hp = f"{boss.hp_percent:.1%}" if boss.hp_percent is not None else "未知"
        lines.append(f"{boss.name}：剩余 {hp}")
    if not data.bosses:
        lines.append("当前没有可展示的 Boss 进度")
    if data.ranking is not None:
        lines.append(scope_label(data.ranking))
        for p in data.ranking.participants[:5]:
            lines.append(f"{p.rank}. {p.nickname} · {format_compact_number(p.total_damage)}")
    if data.member is not None:
        damage = "未知" if data.member.incomplete and not data.member.total_records else format_compact_number(data.member.total_damage)
        lines.append(scope_label(data.member))
        lines.append(f"我的有效记录：{data.member.total_records} 条 · 伤害 {damage}")
    lines.extend(data.notices)
    lines.append("/妮姬 突袭 排名 [页码] · /妮姬 突袭 我的 [页码]")
    return "\n".join(lines)
