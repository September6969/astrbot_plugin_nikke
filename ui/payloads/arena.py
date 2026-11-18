"""从计算 DTO 构建静态竞技场卡片，头像仅使用本地资源。"""

from math import ceil
from unicodedata import east_asian_width

from ...features.arena.models import ArenaThreeTeamPlan
from ...features.arena.presentation import chain_text, recommendation_reasons, source_text, speed_text
from ..t2i_assets import T2IAssetResolver


class ArenaT2IPayloadBuilder:
    PAGE_HEIGHT = 2200

    def __init__(self, assets=None, resolver=None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def team(self, team):
        rows = []
        for position, char in enumerate(team.characters, 1):
            uri = None
            if self.assets:
                try:
                    image, fallback = self.assets.get_lineup_portrait_by_resource_id(char.resource_id)
                    if not fallback:
                        uri = self.resolver.encode(image, (96, 96))
                except Exception:
                    pass
            rows.append({"position": position, "name": char.name, "portrait": uri})
        return rows

    def build(self, result):
        three = isinstance(result, ArenaThreeTeamPlan)
        matches = []
        if three:
            pairs = zip(result.analyses, result.teams)
        else:
            pairs = ((result, item) for item in result.recommendations[:3])
        for position, (analysis, recommendation) in enumerate(pairs, 1):
            matches.append({
                "label": f"第 {position} 场对位" if three else f"推荐 {position}",
                "enemy": self.team(analysis.enemy), "team": self.team(recommendation.team),
                "chain": chain_text(recommendation.chain), "speed": speed_text(recommendation.speed),
                "reasons": [f"相对评分 {recommendation.score}", *recommendation_reasons(recommendation)],
                "warnings": list(recommendation.warnings),
            })
        return {
            "title": "竞技场三队排阵" if three else "竞技场单队解队",
            "matches": matches, "warnings": list(result.warnings), "model_version": result.model_version,
            "source": source_text(result.analyses[0] if three else result),
            "canvas": {"width": 1000, "height": 300 + max(1, len(matches)) * 490},
        }

    def pages(self, result):
        payload = self.build(result)
        three = isinstance(result, ArenaThreeTeamPlan)
        groups = [[]]
        height = 240
        for match in payload["matches"]:
            # 按头像区和正文换行保守估算。分场时保留整组敌我阵容。
            text = (match["chain"], match["speed"], "。".join(match["reasons"]),
                    " ".join(match["warnings"]))
            lines = sum(max(1, ceil(sum(2 if east_asian_width(c) in "WF" else 1 for c in value) / 88))
                        for value in text)
            block = (410 if three or not groups[-1] else 260) + lines * 30
            if groups[-1] and height + block > self.PAGE_HEIGHT:
                groups.append([])
                height = 240
                if not three:
                    block += 150
            groups[-1].append(match)
            height += block
        if len(groups) == 1:
            return [payload]
        return [
            {**payload, "title": f"{payload['title']} · {index}/{len(groups)}",
             "matches": matches, "canvas": {"width": 1000, "height": 300 + len(matches) * 490}}
            for index, matches in enumerate(groups, 1)
        ]
