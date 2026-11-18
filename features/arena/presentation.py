"""竞技场同一结果 DTO 的文字展示。"""

from .models import ArenaAnalysis, ArenaThreeTeamPlan, BurstChain, Recommendation, SpeedEstimate


def chain_text(chain: BurstChain) -> str:
    text = " → ".join(f"B{step.stage}={step.name}(P{step.position})" for step in chain.steps)
    if not chain.valid:
        text += " ｜缺少 " + "、".join(chain.missing)
    return text


def speed_text(speed: SpeedEstimate) -> str:
    return f"{speed.tier:g} RL（静态基线）" if speed.tier is not None else "unknown（充能参数不全）"


def recommendation_reasons(item: Recommendation) -> list[str]:
    reasons = [evidence.text for evidence in item.evidence[1:2]]
    reasons.extend(evidence.text for evidence in item.evidence[2:]
                   if evidence.kind in {"community", "statistic", "personal"})
    return reasons


def source_text(result: ArenaAnalysis) -> str:
    provenance = result.data_status
    source = provenance.source.rstrip("/").rsplit("/", 1)[-1]
    date = result.snapshot_date or "日期未知"
    return f"{source} {provenance.version[:7]} · {date}"


def analysis_text(result: ArenaAnalysis) -> str:
    lines = [
        "【竞技场解队】",
        "敌方 P1–P5 " + "/".join(char.name for char in result.enemy.characters),
        "敌方爆裂轴 " + chain_text(result.chain),
        "敌方速度 " + speed_text(result.speed),
    ]
    for index, item in enumerate(result.recommendations[:3], 1):
        lines.extend((
            "", f"建议 {index} " + "/".join(char.name for char in item.team.characters),
            f"爆裂轴 {chain_text(item.chain)}",
            f"速度 {speed_text(item.speed)}",
            f"相对评分 {item.score}",
            "依据 " + "。".join(recommendation_reasons(item)),
            "风险 " + item.warnings[0],
        ))
    lines.extend(("", *result.warnings, f"模型 {result.model_version} ｜{source_text(result)}"))
    return "\n".join(lines)


def three_team_text(result: ArenaThreeTeamPlan) -> str:
    lines = ["【竞技场三队】", result.objective]
    for index, item in enumerate(result.teams, 1):
        lines.extend(("", f"第 {index} 场对位",
                      "敌方 " + "/".join(char.name for char in result.analyses[index - 1].enemy.characters),
                      "我方 " + "/".join(char.name for char in item.team.characters),
                      "爆裂轴 " + chain_text(item.chain), "速度 " + speed_text(item.speed),
                      f"相对评分 {item.score}",
                      "依据 " + "。".join(recommendation_reasons(item)), "风险 " + item.warnings[0]))
    lines.extend(("", f"已搜索 {result.searched} 组三队组合", *result.warnings,
                  f"模型 {result.model_version} ｜{source_text(result.analyses[0])}"))
    return "\n".join(lines)
