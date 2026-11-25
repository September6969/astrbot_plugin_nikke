"""竞技场同一结果 DTO 的文字展示。"""

from .models import ArenaAnalysis, ArenaThreeTeamPlan, BurstChain, Recommendation, SpeedEstimate


def chain_text(chain: BurstChain) -> str:
    text = " → ".join(f"B{step.stage}={step.name}(P{step.position})" for step in chain.steps)
    if not chain.valid:
        text += " ｜缺少 " + "、".join(chain.missing)
    return text


def speed_text(speed: SpeedEstimate) -> str:
    return f"{speed.tier:g} RL" if speed.tier is not None else "充能数据不足"


def recommendation_reasons(item: Recommendation) -> list[str]:
    reasons = [evidence.text for evidence in item.evidence[1:2]]
    reasons.extend(evidence.text for evidence in item.evidence[2:]
                   if evidence.kind in {"community", "statistic", "personal"})
    return reasons


def source_text(result: ArenaAnalysis) -> str:
    provenance = result.data_status
    source = provenance.source.rstrip("/").rsplit("/", 1)[-1]
    date = result.snapshot_date or "未知日期"
    return f"{source} · {date}"


def analysis_text(result: ArenaAnalysis) -> str:
    lines = [
        "【竞技场解队参考】",
        "敌方 P1–P5：" + " / ".join(char.name for char in result.enemy.characters),
        "敌方爆裂轴：" + chain_text(result.chain),
        "敌方充能：" + speed_text(result.speed),
    ]
    for index, item in enumerate(result.recommendations[:3], 1):
        lines.extend((
            "", f"推荐方案 {index}：" + " / ".join(char.name for char in item.team.characters),
            f"爆裂轴：{chain_text(item.chain)}",
            f"充能：{speed_text(item.speed)} · 评分 {item.score}",
            "思路：" + "。".join(recommendation_reasons(item)),
            "注意：" + item.warnings[0],
        ))
    lines.extend(("", *result.warnings))
    return "\n".join(lines)


def three_team_text(result: ArenaThreeTeamPlan) -> str:
    lines = ["【竞技场三队安排】", result.objective]
    for index, item in enumerate(result.teams, 1):
        lines.extend(("", f"第 {index} 场",
                      "敌方：" + " / ".join(char.name for char in result.analyses[index - 1].enemy.characters),
                      "我方：" + " / ".join(char.name for char in item.team.characters),
                      "爆裂轴：" + chain_text(item.chain),
                      f"充能：{speed_text(item.speed)} · 评分 {item.score}",
                      "思路：" + "。".join(recommendation_reasons(item)),
                      "注意：" + item.warnings[0]))
    lines.extend(("", *result.warnings))
    return "\n".join(lines)
