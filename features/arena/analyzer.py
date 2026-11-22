"""有限模板候选搜索与可解释相对排序。"""

import math
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace

from .burst import burst_chain
from .charge import estimate_speed
from .models import (
    FAVORITE_INFERRED, FAVORITE_LABELS, FAVORITE_MANUAL, FAVORITE_OFFICIAL,
    ArenaAnalysis, ArenaRosterSnapshot, ArenaTeam, MatchupEvidence, Provenance, Recommendation,
)

SUBSTITUTE_LIMIT = 5


def balanced_combinations(slots: Sequence[Sequence[str]],
                          base_of: Callable[[str], str]) -> Iterator[tuple[str, ...]]:
    """按五个槽位偏离首选的步数之和由近及远逐层枚举。

    product() 只轮换尾槽，预算截断时前面的槽位永远停在首选；逐层展开让各槽轮换深度相近。
    同一角色（含皮肤与珍藏变体）占两个槽的分支在生成时剪除，不消耗预算。
    """
    sizes = [len(slot) for slot in slots]
    spare = [sum(size - 1 for size in sizes[index + 1:]) for index in range(len(sizes))]
    keys: list[str] = []
    bases: set[str] = set()

    def walk(index: int, remaining: int) -> Iterator[tuple[str, ...]]:
        if index == len(slots):
            yield tuple(keys)
            return
        for offset in range(max(0, remaining - spare[index]), min(sizes[index] - 1, remaining) + 1):
            key = slots[index][offset]
            base = base_of(key)
            if base in bases:
                continue
            keys.append(key)
            bases.add(base)
            yield from walk(index + 1, remaining - offset)
            keys.pop()
            bases.discard(base)

    for depth in range(sum(size - 1 for size in sizes) + 1):
        yield from walk(0, depth)


class ArenaAnalyzer:
    def __init__(self, directory, templates, parameters, provenance: Provenance, statistics=None,
                 *, snapshot_date: str = ""):
        self.directory = directory
        self.templates = templates
        self.parameters = parameters
        self.provenance = provenance
        self.statistics = statistics
        self.snapshot_date = snapshot_date

    def _base(self, key: str) -> str:
        return self.directory.characters[key].base_key or key

    def charge_efficiency(self, key: str) -> float | None:
        """各 RL 阶静态充能的平均值，缺参数时为 None，不以武器类型代替。"""
        values = [value for value in (self.parameters.get(key) or {}).values()
                  if isinstance(value, (int, float)) and math.isfinite(value)]
        return sum(values) / len(values) if values else None

    def substitutes(self, slot: Sequence[str], allowed: set[str], fixed: set[str]) -> tuple[str, ...]:
        """同爆裂阶段替补：先按模板出现频次，再按静态充能效率，最后按键名保证确定性。"""
        characters = self.directory.characters
        stages = Counter(characters[key].burst for key in slot)
        frequency: Counter[str] = Counter()
        for template in self.templates:
            frequency.update({key for choices in template["slots"] for key in choices})

        def rank(key: str) -> tuple[int, int, bool, float, str]:
            efficiency = self.charge_efficiency(key)
            return (-stages[characters[key].burst], -frequency[key],
                    efficiency is None, -(efficiency or 0.0), key)

        pool = [key for key in allowed
                if characters[key].burst in (1, 2, 3) and stages[characters[key].burst]
                and self._base(key) not in fixed]
        return tuple(sorted(pool, key=rank)[:SUBSTITUTE_LIMIT])

    def _slots(self, template, allowed: set[str], available) -> list[tuple[str, ...]] | None:
        required = set(template["required"])
        if not required <= allowed or len(template["slots"]) != 5:
            return None
        slots = [tuple(key for key in slot if key in allowed) for slot in template["slots"]]
        if available is not None:
            fixed = {self._base(key) for key in required}
            fixed.update(self._base(slot[0]) for slot in slots if len(slot) == 1)
            slots = [choices or self.substitutes(slot, allowed, fixed)
                     for choices, slot in zip(slots, template["slots"])]
        return None if any(not slot for slot in slots) else slots

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
        enemy_keys = set(enemy.keys)
        context = (enemy_chain, enemy_speed, available, {
            item["archetype"] for item in self.templates
            if set(item["required"]) <= enemy_keys
        })
        # 每个可行模板一个游标；预算按轮次在未穷举的模板间均分，小模板用剩的额度流向大模板。
        pending = []
        for template in self.templates:
            slots = self._slots(template, allowed, available)
            if slots is not None:
                combos = balanced_combinations(slots, self._base)
                pending.append([template, combos, next(combos, None)])
        pending = [plan for plan in pending if plan[2] is not None]
        recommendations: dict[tuple[str, ...], Recommendation] = {}
        searched = 0
        while pending and searched < candidate_limit:
            share = max(1, (candidate_limit - searched) // len(pending))
            for plan in pending:
                template, combos, keys = plan
                quota = min(share, candidate_limit - searched)
                while keys is not None and quota > 0:
                    searched += 1
                    quota -= 1
                    item = self._evaluate(template, keys, context)
                    previous = recommendations.get(keys)
                    if item is not None and (previous is None or item.score > previous.score):
                        recommendations[keys] = item
                    keys = next(combos, None)
                plan[2] = keys
            pending = [plan for plan in pending if plan[2] is not None]
        ranked = sorted(recommendations.values(), key=lambda item: (-item.score, item.team.keys))
        warnings = self._analysis_warnings(status, available, searched, candidate_limit, len(pending))
        if not recommendations:
            warnings.append("当前模板与可用角色范围没有合法候选，请调整角色范围或等待模板补全。")
        shown = tuple(ranked[:limit])
        if include_history:
            shown = tuple(self.with_history(item, enemy) for item in shown[:3]) + shown[3:]
        return ArenaAnalysis(enemy, enemy_chain, enemy_speed, shown,
                             tuple(warnings), status, searched, snapshot_date=self.snapshot_date)

    def _evaluate(self, template, keys: tuple[str, ...], context) -> Recommendation | None:
        enemy_chain, enemy_speed, available, enemy_archetypes = context
        if len(set(keys)) != 5:
            return None
        characters = tuple(self.directory.characters[key] for key in keys)
        if len({char.base_key or char.key for char in characters}) != 5:
            return None
        team = ArenaTeam(characters)
        chain = burst_chain(team)
        if not chain.valid:
            return None
        speed = estimate_speed(team, self.parameters, self.provenance)
        evidence = [
            MatchupEvidence("mechanic", "第一轮 B1→B2→B3 爆裂轴完整", chain.provenance),
            MatchupEvidence("community", template["reason"], self.provenance),
        ]
        score = template.get("priority", 0)
        warnings = ["实际魔方、超频、技能与敌方养成未知。"]
        favorites = self._favorite_sources(keys, available)
        manual = [self.directory.characters[key].name for key, source in favorites if source == FAVORITE_MANUAL]
        if manual:
            warnings.insert(0, "珍藏为手动标记，尚未经官方详情确认：" + "、".join(manual))
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
        for key, source in favorites:
            text = f"珍藏来源 {FAVORITE_LABELS[source]}：{self.directory.characters[key].name}"
            if source == FAVORITE_OFFICIAL:
                text += "（已装备专属珍藏品，珍藏阶段未纳入评分）"
            evidence.append(MatchupEvidence("personal", text, self.provenance))
        return Recommendation(team, chain, speed, score, tuple(evidence), tuple(warnings))

    def _favorite_sources(self, keys, available) -> list[tuple[str, str]]:
        if available is None:
            return []
        variants = set(self.directory.variant_of.values())
        sources = [(key, available.favorite_source(key)) for key in keys if key in variants]
        return [(key, source) for key, source in sources if source is not None]

    def _analysis_warnings(self, status, available, searched, candidate_limit, unfinished) -> list[str]:
        warnings = ["当前为离线模板及静态充能排序，尚未完成实战概率校准。"]
        if status == "sandbox":
            warnings.append("全角色沙盒，持有状态未经验证。")
        if status == "manual":
            warnings.append("持有范围由用户手动标记，尚未经绑定角色库验证。")
        if available and available.unmapped:
            warnings.append(f"角色名单有 {available.unmapped} 项未映射，已从可用范围剔除。")
        if available is not None:
            warnings.extend(self.favorite_warnings(available))
        if unfinished:
            warnings.append(f"候选分支已截断，本次检查 {searched} 个候选，上限 {candidate_limit}；"
                            f"{unfinished} 个模板按偏离首选由近及远均衡抽样。")
        return warnings

    def favorite_warnings(self, available: ArenaRosterSnapshot) -> list[str]:
        warnings = []
        counts = Counter(source for _key, source in available.favorites)
        parts = [f"{FAVORITE_LABELS[source]} {counts[source]} 名"
                 for source in (FAVORITE_OFFICIAL, FAVORITE_MANUAL) if counts[source]]
        if parts:
            warnings.append("珍藏形态 " + "，".join(parts) + "。")
        featured = {key for template in self.templates for slot in template["slots"] for key in slot}
        pending = [key for key in available.favorite_unconfirmed if key in featured]
        if pending:
            characters = self.directory.characters
            names = "、".join(characters[characters[key].base_key].name for key in pending[:5])
            more = f" 等 {len(pending)} 名" if len(pending) > 5 else " "
            warnings.append(
                f"{FAVORITE_LABELS[FAVORITE_INFERRED]}：名单含 {names}{more}可制作专属珍藏的角色本体，"
                "但无官方详情确认，对应珍藏形态未参与推荐；如已制作，可在私聊解队末尾追加「珍藏:角色名」"
                "手动标记，或在网页手动持有范围中勾选。")
        warnings.extend(available.notes)
        return warnings

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
