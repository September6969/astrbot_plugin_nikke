"""只在当前响应内聚合攻击；公开 DTO 不携带账号标识。"""
from dataclasses import dataclass, field


def integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("攻击数值格式无效")
    if isinstance(value, str) and not value.isdigit():
        raise ValueError("攻击数值格式无效")
    result = int(value)
    if result < 0:
        raise ValueError("攻击数值不能为负")
    return result


@dataclass(slots=True)
class RaidSquadMember:
    tid: str
    level: int
    combat: int
    slot: int
    costume_id: str | None = None


@dataclass(slots=True)
class RaidAttackData:
    boss_id: str
    day: int
    difficulty: int
    level: int
    step: int
    total_damage: int
    is_final_hit: bool
    squad: list[RaidSquadMember]


@dataclass(slots=True)
class RaidParticipantSummary:
    nickname: str
    total_damage: int = 0
    rank: int = 0
    attacks: list[RaidAttackData] = field(default_factory=list)


@dataclass(slots=True)
class RaidRankingData:
    participants: list[RaidParticipantSummary]
    scope: str = "CURRENT_RESPONSE"


def build_ranking(payload: dict) -> RaidRankingData:
    rows = payload.get("participate_data")
    if not isinstance(rows, list):
        raise ValueError("突袭响应缺少攻击列表")
    groups = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("openid"), str) or not row["openid"]:
            raise ValueError("攻击记录缺少有效身份，不能安全聚合")
        try:
            squad = [RaidSquadMember(str(m["tid"]), integer(m["lv"]), integer(m["combat"]),
                      integer(m["slot"]), str(m["costume_id"]) if m.get("costume_id") is not None else None)
                     for m in row["squad"]]
            if len(squad) != 5 or {m.slot for m in squad} != {1, 2, 3, 4, 5}:
                raise ValueError("历史队伍不完整")
            if type(row["is_final_hit"]) is not bool:
                raise ValueError("尾刀标志无效")
            attack = RaidAttackData(str(row["boss_id"]), integer(row["day"]), integer(row["difficulty"]),
                integer(row["level"]), integer(row["step"]), integer(row["total_damage"]), row["is_final_hit"], squad)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("攻击记录格式异常，不能生成完整排名") from exc
        # 昵称只作显示，不参与合并或并列裁决。
        group = groups.setdefault(row["openid"], RaidParticipantSummary(str(row.get("nickname") or "成员")))
        group.attacks.append(attack)
        group.total_damage += attack.total_damage
    participants = sorted(groups.values(), key=lambda item: -item.total_damage)
    previous = None
    rank = 0
    for index, participant in enumerate(participants, 1):
        if participant.total_damage != previous:
            rank = index
        participant.rank = rank
        previous = participant.total_damage
    return RaidRankingData(participants)


def format_ranking(data: RaidRankingData) -> str:
    lines = [
        "【联盟突袭 · 当前响应范围排名】",
        "按已返回记录的伤害字段汇总；不代表完整赛季或实际攻击次数。",
    ]
    for item in data.participants[:50]:
        name = " ".join(item.nickname.split())[:40]
        lines.append(f"{item.rank}. {name}：{item.total_damage:,} · {len(item.attacks)} 条返回记录")
    if not data.participants:
        lines.append("当前响应没有攻击记录。")
    if len(data.participants) > 50:
        lines.append(f"另有 {len(data.participants)-50} 位成员，当前仅展示前50项。")
    return "\n".join(lines)
