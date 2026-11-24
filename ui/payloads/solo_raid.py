# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭五队阵容图 payload（22）；头像只使用本地已解析资源。"""

from __future__ import annotations

from typing import Any

from ...features.solo_raid.builder import BURST_LABELS, FiveTeamPlan, NO_DAMAGE_NOTE
from ..t2i_assets import T2IAssetResolver

CANVAS_WIDTH = 1000


class SoloRaidPayloadBuilder:
    """把五队方案投影为只读展示数据；缺失头像时保留稳定占位。"""

    def __init__(self, assets=None, resolver=None) -> None:
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def _portrait(self, member) -> str | None:
        if not self.assets or not member.resource_id:
            return None
        try:
            image, fallback = self.assets.get_lineup_portrait_by_resource_id(member.resource_id)
            if fallback:
                return None
            return self.resolver.encode(image, (96, 96))
        except Exception:
            return None

    def build(self, plan: FiveTeamPlan, *, boss=None) -> dict[str, Any]:
        teams = []
        for team in plan.teams:
            teams.append(
                {
                    "index": team.index,
                    "chain_ok": team.chain_ok,
                    "damage": team.damage,
                    "issues": list(team.issues),
                    "members": [
                        {
                            "name": member.name,
                            "burst": member.burst,
                            "burst_label": BURST_LABELS.get(member.burst, member.burst or "?"),
                            "element": member.element,
                            "portrait": self._portrait(member),
                        }
                        for member in team.members
                    ],
                }
            )
        return {
            "title": "单人突袭五队",
            "season": plan.season_name,
            "boss": (
                {"name": boss.name, "weakness": boss.weakness, "element": boss.element}
                if boss is not None
                else None
            ),
            "teams": teams,
            "damage": plan.damage_total,
            "damage_text": (
                NO_DAMAGE_NOTE if plan.damage_total is None else f"配置化估算 {plan.damage_total:,}"
            ),
            "issues": list(plan.issues),
            "canvas": {"width": CANVAS_WIDTH, "height": 260 + 300 * max(1, len(teams))},
        }


__all__ = ["SoloRaidPayloadBuilder"]
