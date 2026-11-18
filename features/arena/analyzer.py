"""有限模板候选搜索与可解释相对排序。"""

from itertools import product
from dataclasses import replace

from .burst import burst_chain
from .charge import estimate_speed
from .models import (
    ArenaAnalysis, ArenaRosterSnapshot, ArenaTeam, MatchupEvidence,
    Provenance, Recommendation,
)


class ArenaAnalyzer:
    def __init__(self, directory, templates, parameters, provenance: Provenance, statistics=None,
                 *, snapshot_date: str = ""):
        self.directory = directory
        self.templates = templates
        self.parameters = parameters
        self.provenance = provenance
        self.statistics = statistics
        self.snapshot_date = snapshot_date

    def analyze(self, enemy: ArenaTeam, available: ArenaRosterSnapshot | None = None,
                *, limit: int = 3, candidate_limit: int = 2048, include_history: bool = True) -> ArenaAnalysis:
        if not 1 <= limit <= 300 or not 1 <= candidate_limit <= 10000:
            raise ValueError("候选预算超出范围。")
        enemy_chain = burst_chain(enemy)
        enemy_speed = estimate_speed(enemy, self.parameters, self.provenance)
        allowed = set(self.directory.characters)
        status = "sandbox"
        if available is not None:
            if available.status not in {"available", "partial", "manual"}:
                allowed = set()
            else:
                allowed &= available.keys
            status = available.status
        recommendations: dict[tuple[str, ...], Recommendation] = {}
        searched = 0
        truncated = False
        enemy_keys = set(enemy.keys)
        enemy_archetypes = {
            item["archetype"] for item in self.templates
            if set(item["required"]) <= enemy_keys
        }
        substitutes = {
            stage: tuple(key for key in sorted(allowed)
                         if self.directory.characters[key].burst == stage)
            for stage in (1, 2, 3)
        }
        for template in self.templates:
            required = set(template["required"])
            if not required <= allowed:
                continue
            slots = []
            for slot in template["slots"]:
                choices = tuple(key for key in slot if key in allowed)
                if not choices and available is not None:
                    stages = {self.directory.characters[key].burst for key in slot}
                    choices = tuple(key for stage in sorted(stages)
                                    for key in substitutes.get(stage, ()) if key not in required)[:5]
                slots.append(choices)
            if len(slots) != 5 or any(not slot for slot in slots):
                continue
            template_budget = max(1, candidate_limit // max(1, len(self.templates)))
            for attempt, keys in enumerate(product(*slots)):
                if attempt >= template_budget or searched >= candidate_limit:
                    truncated = True
                    break
                searched += 1
                if len(set(keys)) != 5:
                    continue
                characters = tuple(self.directory.characters[key] for key in keys)
                if len({char.base_key or char.key for char in characters}) != 5:
                    continue
                team = ArenaTeam(characters)
                chain = burst_chain(team)
                if not chain.valid:
                    continue
                speed = estimate_speed(team, self.parameters, self.provenance)
                evidence = [
                    MatchupEvidence("mechanic", "第一轮 B1→B2→B3 爆裂轴完整", chain.provenance),
                    MatchupEvidence("community", template["reason"], self.provenance),
                ]
                score = template.get("priority", 0)
                warnings = ["实际魔方、超频、技能与敌方养成未知。"]
                replaced = [f"P{position} {self.directory.characters[key].name}"
                            for position, (key, slot) in enumerate(zip(keys, template["slots"]), 1)
                            if key not in slot]
                if replaced:
                    warnings.insert(0, "同爆裂阶段替补尚未验证：" + "、".join(replaced))
                    score -= 15 * len(replaced)
                positive = enemy_archetypes.intersection(template.get("counters", ()))
                negative = enemy_archetypes.intersection(template.get("countered_by", ()))
                if replaced:
                    positive = set()
                if positive:
                    evidence.append(MatchupEvidence(
                        "community", "模板声称可针对 " + "、".join(sorted(positive)), self.provenance))
                    score += 40 * len(positive)
                if negative:
                    evidence.append(MatchupEvidence(
                        "community", "模板同时标注不利于 " + "、".join(sorted(negative)), self.provenance))
                    score -= 30 * len(negative)
                if (speed.tier is not None and enemy_speed.tier is not None
                        and len(chain.steps) == 3 and len(enemy_chain.steps) == 3):
                    difference = enemy_speed.tier - speed.tier
                    score += int(difference * 10)
                    evidence.append(MatchupEvidence(
                        "heuristic", f"静态充能相差 {difference:+g} RL 阶，尚未计入再入延迟",
                        self.provenance))
                if len(chain.steps) > 3 or len(enemy_chain.steps) > 3:
                    warnings.append("存在再入爆裂，静态 RL 阶不能直接代表全爆裂先后。")
                previous = recommendations.get(keys)
                if previous is None or score > previous.score:
                    recommendations[keys] = Recommendation(
                        team, chain, speed, score, tuple(evidence), tuple(warnings))
            if searched >= candidate_limit:
                break
        ranked = sorted(recommendations.values(), key=lambda item: (-item.score, item.team.keys))
        warnings = ["当前为离线模板及静态充能排序，尚未完成实战概率校准。"]
        if status == "sandbox":
            warnings.append("全角色沙盒，持有状态未经验证。")
        if status == "manual":
            warnings.append("持有范围由用户手动标记，尚未经绑定角色库验证。")
        if available and available.unmapped:
            warnings.append(f"角色名单有 {available.unmapped} 项未映射，已从可用范围剔除。")
        if truncated:
            warnings.append(f"候选分支已截断，本次检查 {searched} 个候选，上限 {candidate_limit}。")
        if not recommendations:
            warnings.append("当前模板与可用角色范围没有合法候选，请调整角色范围或等待模板补全。")
        shown = tuple(ranked[:limit])
        if include_history:
            shown = tuple(self.with_history(item, enemy) for item in shown[:3]) + shown[3:]
        return ArenaAnalysis(enemy, enemy_chain, enemy_speed, shown,
                             tuple(warnings), status, searched, snapshot_date=self.snapshot_date)

    def with_history(self, item: Recommendation, enemy: ArenaTeam) -> Recommendation:
        historical = self.statistics.matchup(item.team, enemy) if self.statistics else None
        return replace(item, evidence=(*item.evidence, historical)) if historical else item

    def manual_candidate(self, team: ArenaTeam, analysis: ArenaAnalysis,
                         available: ArenaRosterSnapshot | None) -> Recommendation:
        if available is not None and (available.status not in {"available", "partial", "manual"}
                                      or not set(team.keys) <= available.keys):
            raise ValueError("手动候选包含当前范围内无法确认持有的角色。")
        chain = burst_chain(team)
        if not chain.valid:
            raise ValueError("手动候选的第一轮爆裂轴不完整。")
        entered = MatchupEvidence("personal", "手动加入本场候选", self.provenance)
        existing = next((item for item in analysis.recommendations if item.team.keys == team.keys), None)
        if existing:
            return replace(existing, evidence=(*existing.evidence, entered))
        speed = estimate_speed(team, self.parameters, self.provenance)
        score = 0
        evidence = [MatchupEvidence("mechanic", "第一轮 B1→B2→B3 爆裂轴完整", chain.provenance), entered]
        warnings = ["此手动候选无模板评分，仅按已知静态机制比较。实际魔方、超频、技能与敌方养成未知。"]
        if (speed.tier is not None and analysis.speed.tier is not None
                and len(chain.steps) == len(analysis.chain.steps) == 3):
            difference = analysis.speed.tier - speed.tier
            score = int(difference * 10)
            evidence.append(MatchupEvidence(
                "heuristic", f"静态充能相差 {difference:+g} RL 阶，尚未计入再入延迟", self.provenance))
        return Recommendation(team, chain, speed, score, tuple(evidence), tuple(warnings))
