"""有限候选池中的三队互斥搜索。"""

from itertools import zip_longest
from time import monotonic

from .models import ArenaTeam, ArenaThreeTeamPlan

OBJECTIVES = {"two": "优先两队相对优势", "balanced": "均衡", "speed": "速度优先"}


def validate_three(teams: tuple[ArenaTeam, ...]) -> None:
    if len(teams) != 3:
        raise ValueError("三队必须包含三组五人阵容。")
    bases = [char.base_key or char.key for team in teams for char in team.characters]
    if len(set(bases)) != 15:
        raise ValueError("三队十五人不能重复，皮肤与珍藏变体也计为同一角色。")


class ThreeTeamOptimizer:
    def __init__(self, analyzer):
        self.analyzer = analyzer

    def solve(self, enemies, available=None, *, objective="two", budget=30000,
              timeout=1.0, manual_candidates: tuple[ArenaTeam | None, ...] = ()) -> ArenaThreeTeamPlan:
        validate_three(enemies)
        if objective not in OBJECTIVES or not 1 <= budget <= 100000 or not 0 < timeout <= 5:
            raise ValueError("三队目标或搜索预算无效。")
        if manual_candidates and len(manual_candidates) != 3:
            raise ValueError("手动候选必须按三场提供。")
        analyses = tuple(self.analyzer.analyze(team, available, limit=300, include_history=False)
                         for team in enemies)
        # 先按核心角色分散候选，避免前三百套仅在同一体系里换一个辅助。
        pools = []
        for index, analysis in enumerate(analyses):
            groups = {}
            for item in analysis.recommendations:
                core = tuple(step.character_key for step in item.chain.steps)
                groups.setdefault(core, []).append(item)
            # 保留同轴队伍的不同轴外成员，避免唯一代表与其他两队抢人。
            pool = [item for round_items in zip_longest(*groups.values())
                    for item in round_items if item is not None]
            manual = manual_candidates[index] if manual_candidates else None
            if manual is not None:
                try:
                    candidate = self.analyzer.manual_candidate(manual, analysis, available)
                except ValueError as exc:
                    raise ValueError(f"第 {index + 1} 场：{exc}") from exc
                pool = [candidate, *(item for item in pool if item.team.keys != manual.keys)]
            pools.append([(item, frozenset(char.base_key or char.key for char in item.team.characters))
                          for item in pool[:60]])
        best = ()
        best_key = None
        searched = 0
        truncated = False
        deadline = monotonic() + timeout
        for candidates, occupied in self._compatible_pairs(pools):
            if searched >= budget or monotonic() >= deadline:
                truncated = True
                break
            searched += 1
            if not occupied:
                continue
            scores = sorted(item.score for item in candidates)
            key = (scores[1], sum(scores), scores[0])
            if objective == "balanced":
                key = (scores[0], sum(scores), scores[1])
            elif objective == "speed":
                unknown = sum(item.speed.tier is None for item in candidates)
                speed = sum(item.speed.tier or 10 for item in candidates)
                key = (-unknown, -speed, sum(scores))
            if best_key is None or key > best_key:
                best = candidates
                best_key = key
        warnings = ["目标按启发式相对分排序，未推断三局获胜概率。",
                    "使用有限候选池，搜索无解时仍可修改角色范围或对方站位。"]
        if truncated:
            warnings.append("已达到时间或候选预算，返回预算内最佳排阵。")
        if not best:
            warnings.append("预算内未找到十五人互斥的合法三队。")
        if available is not None:
            # 三场共用同一份名单，珍藏来源与推测提示只列一次。
            warnings.extend(self.analyzer.favorite_warnings(available))
        best = tuple(self.analyzer.with_history(item, enemy) for item, enemy in zip(best, enemies))
        return ArenaThreeTeamPlan(analyses, tuple(best), OBJECTIVES[objective], searched,
                                  truncated, tuple(warnings))

    @staticmethod
    def _compatible_pairs(pools):
        for first, first_keys in pools[0]:
            for second, second_keys in pools[1]:
                if not first_keys.isdisjoint(second_keys):
                    continue
                pair_keys = first_keys | second_keys
                for third, third_keys in pools[2]:
                    yield (first, second, third), pair_keys.isdisjoint(third_keys)
