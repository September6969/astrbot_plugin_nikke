"""联盟突袭概览卡片的展示数据组装。"""


class UnionOverviewT2IPayloadBuilder:
    def __init__(self, assets=None, resolver=None):
        from astrbot_plugin_nikke.ui.t2i_assets import T2IAssetResolver

        self.assets, self.resolver = assets, resolver or T2IAssetResolver()

    def build(self, data, now=None):
        from datetime import datetime

        from astrbot_plugin_nikke.features.raid.models import RaidState
        from astrbot_plugin_nikke.features.raid.participants import format_compact_number
        from astrbot_plugin_nikke.ui.renderers.raid import UnionRaidRenderer
        from astrbot_plugin_nikke.ui.t2i_payloads import (
            boss_presentation,
            display_number,
            display_remaining,
        )

        raid_state = getattr(data, "raid_state", RaidState.UNKNOWN)
        if isinstance(raid_state, RaidState):
            state_str = raid_state.value
        elif isinstance(raid_state, str):
            state_str = raid_state
        else:
            state_str = "UNKNOWN"

        previous_season = getattr(data, "previous_season", None)
        prev_dict = None
        if previous_season:
            def _format_date(iso_str: str) -> str:
                if not iso_str:
                    return ""
                try:
                    dt = datetime.fromisoformat(iso_str)
                    return dt.strftime("%m.%d %H:%M")
                except Exception:
                    return iso_str[:16].replace("T", " ")

            start_fmt = _format_date(getattr(previous_season, "start_at", ""))
            end_fmt = _format_date(getattr(previous_season, "end_at", ""))
            date_range = f"{start_fmt} → {end_fmt}" if start_fmt and end_fmt else ""
            total_dmg = getattr(previous_season, "total_damage", 0)
            dmg_str = format_compact_number(total_dmg) if total_dmg else "0"
            season_number = getattr(previous_season, "season_number", None)
            season_name = (
                f"第 {season_number} 季"
                if season_number is not None
                else str(getattr(previous_season, "season_id", ""))
            )
            prev_dict = {
                "season_id": getattr(previous_season, "season_id", ""),
                "season_number": season_number,
                "season_name": season_name,
                "date_range": date_range,
                "total_attacks": getattr(previous_season, "total_attacks", 0),
                "total_damage": total_dmg,
                "total_damage_formatted": dmg_str,
                "boss_progress": getattr(previous_season, "boss_progress", None),
            }

        if state_str in ("OFFSEASON", "SETTLEMENT"):
            return {
                "guild": data.guild_name,
                "raid_state": state_str,
                "difficulty": None,
                "level": None,
                "bosses": [],
                "coverage": UnionRaidRenderer._coverage_text(data.response_coverage),
                "partial": data.partial_boss_records,
                "returned": 0,
                "progress": None,
                "remaining": None,
                "updated": data.fetched_at,
                "version": data.plugin_version,
                "previous_season": prev_dict,
                "current_season_name": getattr(data, "current_season_name", None),
            }

        if len(data.bosses) > 5:
            raise ValueError("超过五个 Boss，使用原有完整记录展示")
        bosses = [
            {
                **boss_presentation(
                    self.assets,
                    self.resolver,
                    boss.boss_id,
                    boss.icon_id,
                    boss.monster_model_id,
                    boss.name,
                ),
                "hp": f"{display_number(boss.current_hp)} / {display_number(boss.max_hp)}",
                "percent": f"{boss.hp_percent:.1%}" if boss.hp_percent is not None else "Unknown",
                "bar": round(boss.hp_percent * 100, 2) if boss.hp_percent is not None else None,
                "status": boss.status.value,
                "elements": " / ".join(boss.elements) or "Unknown",
            }
            for boss in data.bosses
        ]
        while len(bosses) < 5:
            bosses.append(
                {
                    "name": "未返回 Boss 记录",
                    "hp": "Unknown",
                    "percent": "Unknown",
                    "bar": None,
                    "status": "UNKNOWN",
                    "elements": "Unknown",
                }
            )
        return {
            "guild": data.guild_name,
            "raid_state": state_str,
            "difficulty": display_number(data.difficulty),
            "level": display_number(data.level),
            "bosses": bosses,
            "coverage": UnionRaidRenderer._coverage_text(data.response_coverage),
            "partial": data.partial_boss_records,
            "returned": len(data.bosses),
            "progress": f"{data.total_progress:.1%}" if data.total_progress is not None else "Unknown",
            "remaining": display_remaining(data.season_end, now),
            "updated": data.fetched_at,
            "version": data.plugin_version,
            "previous_season": prev_dict,
            "current_season_name": getattr(data, "current_season_name", None),
        }
