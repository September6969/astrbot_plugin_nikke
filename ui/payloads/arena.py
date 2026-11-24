"""从计算 DTO 构建静态竞技场卡片，头像仅使用本地资源。"""

from math import ceil
from unicodedata import east_asian_width

from ...features.arena.models import ArenaThreeTeamPlan
from ...features.arena.presentation import chain_text, recommendation_reasons, source_text, speed_text
from ..t2i_assets import T2IAssetResolver

# 高度模型与 templates/t2i/_shared/arena.css 的显式行高逐项对应（单位 px）。
CANVAS_WIDTH = 1000
PAGE_PADDING = 38
TITLE_HEIGHT = 38 * 1.5 + 10          # h1 + margin-bottom
SOURCE_LINE = 17 * 1.5
MATCH_GAP = 22                        # .match margin-top
MATCH_CHROME = 2 + 2 * 22 + 8 + 23 * 1.5 + 12  # 边框 + 内边距 + h2（含上下外边距）
SIDE_LABEL = 18 * 1.5                 # “敌方/我方 P1–P5”
MEMBER_CHROME = 2 * 10 + 17 * 1.4     # 成员卡上下内边距 + 位置标签
PORTRAIT = 64 + 4 + 2
NAME_LINE = 17 * 1.5
NAME_MIN = 28
DETAIL_GAP = 12
DETAIL_LINE = 18 * 1.65
FOOTER_GAP = 24
FOOTER_LINE = 17 * 1.6
# 每行可容纳的半角单位（全角字符记 2）：正文 878px / 9px，页脚 924px / 8.5px，成员名 159px / 8.5px，均略留余量。
DETAIL_UNITS = 96
FOOTER_UNITS = 106
NAME_UNITS = 18
SOURCE_UNITS = 106


def _lines(text: str, capacity: int) -> int:
    """按半角单位估算折行数；空字符串记 0 行。"""
    if not text:
        return 0
    units = sum(2 if east_asian_width(char) in "WF" else 1 for char in text)
    return max(1, ceil(units / capacity))


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

    @staticmethod
    def _lineup_height(members) -> float:
        portrait = PORTRAIT if any(member["portrait"] for member in members) else 0
        name = max((max(NAME_MIN, _lines(member["name"], NAME_UNITS) * NAME_LINE) for member in members),
                   default=NAME_MIN)
        return SIDE_LABEL + MEMBER_CHROME + portrait + name

    @classmethod
    def match_height(cls, match, *, show_enemy: bool) -> float:
        """单场对位卡片高度：标题、阵容、爆裂轴/速度/理由三段正文与风险提示。"""
        lineups = [match["enemy"], match["team"]] if show_enemy else [match["team"]]
        details = (
            _lines("爆裂轴 " + match["chain"], DETAIL_UNITS)
            + _lines("速度 " + match["speed"], DETAIL_UNITS)
            + max(1, _lines("；".join(match["reasons"]), DETAIL_UNITS))
        )
        warnings = _lines(" ".join(match["warnings"]), DETAIL_UNITS)
        return (
            MATCH_CHROME
            + sum(cls._lineup_height(members) for members in lineups)
            + DETAIL_GAP + details * DETAIL_LINE
            + DETAIL_GAP + warnings * DETAIL_LINE
        )

    @classmethod
    def page_height(cls, payload, matches, *, three: bool) -> int:
        """整页高度；与画布、分页预算共用同一模型（不再固定按每场 490px 估算）。"""
        footer = sum(_lines(text, FOOTER_UNITS) for text in payload["warnings"]) * FOOTER_LINE
        body = sum(
            MATCH_GAP + cls.match_height(match, show_enemy=three or index == 0)
            for index, match in enumerate(matches)
        )
        source = _lines(f"{payload['source']} · {payload['model_version']}", SOURCE_UNITS) * SOURCE_LINE
        return ceil(2 * PAGE_PADDING + TITLE_HEIGHT + source + body + FOOTER_GAP + footer)

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
        payload = {
            "title": "竞技场三队排阵" if three else "竞技场单队解队",
            "matches": matches, "warnings": list(result.warnings), "model_version": result.model_version,
            "source": source_text(result.analyses[0] if three else result),
        }
        payload["canvas"] = {"width": CANVAS_WIDTH, "height": self.page_height(payload, matches, three=three)}
        return payload

    def pages(self, result):
        payload = self.build(result)
        three = isinstance(result, ArenaThreeTeamPlan)
        groups: list[list[dict]] = [[]]
        for match in payload["matches"]:
            # 分页与画布共用 page_height；新页首场在单队模式下会重新展示敌方阵容。
            candidate = groups[-1] + [match]
            if groups[-1] and self.page_height(payload, candidate, three=three) > self.PAGE_HEIGHT:
                groups.append([match])
            else:
                groups[-1] = candidate
        if len(groups) == 1:
            return [payload]
        return [
            {**payload, "title": f"{payload['title']} · {index}/{len(groups)}", "matches": matches,
             "canvas": {"width": CANVAS_WIDTH, "height": self.page_height(payload, matches, three=three)}}
            for index, matches in enumerate(groups, 1)
        ]
