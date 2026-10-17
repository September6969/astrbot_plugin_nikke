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


def identifier(value, *, field: str, allow_integer: bool = False) -> str:
    """只保留有明确文本意义的身份字段，不把空值或任意对象转成假 ID。"""
    valid_type = isinstance(value, str) or (allow_integer and type(value) is int)
    if not valid_type or not str(value).strip():
        raise ValueError(f"{field}缺少有效标识")
    return str(value)


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
    day: int | None
    difficulty: int | None
    level: int | None
    step: int | None
    total_damage: int
    is_final_hit: bool | None
    squad: list[RaidSquadMember]
    details_complete: bool = True


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
    union_members: list[str] | None = None
    guild_name: str = "联盟"
    season_id: str | None = None
    fetched_at: str = ""
    incomplete: bool = False
    coverage_complete: bool = False
    excluded_records: int = 0
    total_damage: int = 0
    total_records: int = 0
    page: int = 1
    total_pages: int = 1
    attendance_status: str = "UNKNOWN"
    unattacked: list[str] = field(default_factory=list)


def build_ranking(payload: dict, union_members: list[str] | None = None) -> RaidRankingData:
    rows = payload.get("participate_data")
    if not isinstance(rows, list):
        raise ValueError("突袭响应缺少攻击列表")
    groups = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("openid"), str) or not row["openid"].strip():
            raise ValueError("攻击记录缺少有效身份，不能安全聚合")
        try:
            boss_id = identifier(row.get("boss_id"), field="Boss ID", allow_integer=True)
            squad = [RaidSquadMember(identifier(m["tid"], field="角色 ID", allow_integer=True), integer(m["lv"]), integer(m["combat"]),
                      integer(m["slot"]), str(m["costume_id"]) if m.get("costume_id") is not None else None)
                     for m in row["squad"]]
            if len(squad) != 5 or {m.slot for m in squad} != {1, 2, 3, 4, 5}:
                raise ValueError("历史队伍不完整")
            if type(row["is_final_hit"]) is not bool:
                raise ValueError("尾刀标志无效")
            attack = RaidAttackData(boss_id, integer(row["day"]), integer(row["difficulty"]),
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
    if union_members is None and isinstance(payload, dict):
        union_members = payload.get("union_members") or payload.get("guild_members")
    return RaidRankingData(participants, union_members=union_members,
        total_damage=sum(p.total_damage for p in participants), total_records=sum(len(p.attacks) for p in participants))


def build_member_ranking(payload: dict, member_openid: str) -> RaidRankingData:
    """按请求使用的稳定 openid 精确筛选当前响应，不猜测成员字段。"""
    if not isinstance(member_openid, str) or not member_openid.strip():
        raise ValueError("当前账号缺少稳定联盟身份")
    rows = payload.get("participate_data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("突袭响应缺少攻击列表")
    matched: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("攻击记录格式异常，不能安全筛选")
        openid = row.get("openid")
        if not isinstance(openid, str) or not openid.strip():
            raise ValueError("攻击记录缺少有效身份，不能安全筛选")
        if openid == member_openid:
            matched.append(row)
    ranking = build_ranking({"participate_data": matched})
    ranking.scope = "CURRENT_RESPONSE_MEMBER"
    return ranking


def format_compact_number(value: int | float | None) -> str:
    """Format large numbers into compact K / M / B representation with carry-over rounding."""
    if value is None:
        return "0"
    is_neg = value < 0
    val = abs(value)
    if val < 1000:
        res = str(int(val))
        return f"-{res}" if is_neg and res != "0" else res

    tiers = [
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ]
    divisor, unit = tiers[-1]
    for d, u in tiers:
        if val >= d:
            divisor, unit = d, u
            break

    num = val / divisor
    rounded = round(num, 2)
    if rounded >= 1000:
        if unit == "K":
            divisor, unit = 1_000_000, "M"
            num = val / divisor
            rounded = round(num, 2)
        elif unit == "M":
            divisor, unit = 1_000_000_000, "B"
            num = val / divisor
            rounded = round(num, 2)

    s = f"{rounded:.2f}".rstrip("0").rstrip(".") + unit
    return f"-{s}" if is_neg else s


def format_ranking(data: RaidRankingData) -> str:
    member = data.scope.endswith("_MEMBER")
    title = ("我的上赛季记录" if member else "上赛季返回排名") if data.scope.startswith("LAST_SEASON") else ("我的当前响应范围" if member else "当前响应范围排名")
    lines = [f"【联盟突袭 · {data.guild_name} · {title}】", scope_label(data), "按已返回记录汇总，不代表完整赛季或实际攻击次数。"]
    for item in data.participants:
        name = " ".join(item.nickname.split())[:40]
        share = f" · 占比 {item.total_damage / data.total_damage:.1%}" if not member and data.total_damage else ""
        lines.append(f"{item.rank}. {name}：{format_compact_number(item.total_damage)}{share} · {data.total_records if member else len(item.attacks)} 条返回记录")
        if member:
            for attack in item.attacks:
                lines.append(f"第 {attack.day if attack.day is not None else '未知'} 日 · {attack.boss_id or '未知Boss'} · {format_compact_number(attack.total_damage)}")
    if not data.participants:
        lines.append("此范围未返回可验证的个人记录。" if member else "此范围没有可验证的攻击记录。")
    if data.excluded_records:
        lines.append(f"有 {data.excluded_records} 条无效记录未纳入统计")
    if not member:
        if data.attendance_status == "UNKNOWN":
            lines.append("未出刀情况：当前数据无法确认")
        elif data.unattacked:
            lines.append("已确认未出刀：" + "、".join(data.unattacked))
        else:
            lines.append("完整范围内全员已有记录")
    if data.fetched_at:
        lines.append(f"更新：{data.fetched_at}")
    lines.append(f"第 {data.page}/{data.total_pages} 页 · /妮姬 突袭 {'我的' if member else '排名'} [页码]")
    return "\n".join(lines)


def scope_label(data):
    season = (f"第 {int(data.season_id) % 1000000} 季 · " if str(data.season_id).isdigit() else f"赛季 {data.season_id} · ") if data.season_id else ""
    period = "上赛季返回记录" if data.scope.startswith("LAST_SEASON") else "本次返回记录"
    return season + period + (" · 部分有效数据" if data.incomplete else (" · 已确认完整范围" if data.coverage_complete else " · 完整性未确认"))
