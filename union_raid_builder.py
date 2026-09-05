# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid data builder for parsing and normalizing API responses."""

from __future__ import annotations

from typing import Any

from .union_raid_models import BossStatus, RaidBossData, UnionRaidOverviewData


class UnionRaidBuilder:
    def build(
        self,
        *,
        guild_name: str,
        level_info_payload: dict[str, Any],
        fetched_at: str,
        plugin_version: str,
    ) -> UnionRaidOverviewData:
        """Parse raw GetUnionRaidLevelInfo response into UnionRaidOverviewData."""
        levels = level_info_payload.get("level_info", [])
        manager = level_info_payload.get("manager_info", {})

        current_level_obj: dict[str, Any] = {}
        for lvl in levels:
            if isinstance(lvl, dict):
                current_level_obj = lvl
                break

        difficulty = int(current_level_obj.get("difficulty", 1) or 1)
        level = int(current_level_obj.get("level", 1) or 1)
        raw_bosses = current_level_obj.get("boss_info", [])

        # Parse raw bosses
        boss_items: list[dict[str, Any]] = []
        for raw in raw_bosses:
            if not isinstance(raw, dict):
                continue
            boss_id = str(raw.get("boss_id", ""))
            current_hp_raw = raw.get("current_hp")
            max_hp_raw = raw.get("max_hp")

            current_hp = None
            if current_hp_raw not in (None, ""):
                try:
                    current_hp = max(0, int(current_hp_raw))
                except (ValueError, TypeError):
                    current_hp = None

            max_hp = None
            if max_hp_raw not in (None, ""):
                try:
                    max_hp = int(max_hp_raw)
                except (ValueError, TypeError):
                    max_hp = None

            names = raw.get("name_localvalues", {})
            name = ""
            if isinstance(names, dict):
                name = (
                    names.get("zh-cn")
                    or names.get("zh-tw")
                    or names.get("zh_tw")
                    or names.get("en")
                    or names.get("ja")
                    or names.get("ko")
                    or ""
                )
            if not name:
                name = str(raw.get("name_localkey") or f"Boss {boss_id}")

            elements = raw.get("element_id", [])
            element_list = [str(e) for e in elements if e not in (None, "")] if isinstance(elements, list) else []

            boss_items.append({
                "boss_id": boss_id,
                "name": name,
                "current_hp": current_hp,
                "max_hp": max_hp,
                "elements": element_list,
                "icon_id": str(raw.get("icon_id")) if raw.get("icon_id") not in (None, "") else None,
                "monster_model_id": str(raw.get("monster_model_id")) if raw.get("monster_model_id") not in (None, "") else None,
            })

        # Determine status according to state machine sequence
        current_idx = None
        for i, item in enumerate(boss_items):
            cur = item["current_hp"]
            mx = item["max_hp"]
            if cur is not None and mx is not None and cur > 0 and mx > 0:
                current_idx = i
                break

        parsed_bosses: list[RaidBossData] = []
        for i, item in enumerate(boss_items):
            max_hp = item["max_hp"]
            current_hp = item["current_hp"]

            if max_hp is None or current_hp is None or max_hp <= 0:
                status = BossStatus.UNKNOWN
                hp_percent = None
                cleared_percent = None
            else:
                hp_percent = current_hp / max_hp
                cleared_percent = max(0.0, min(1.0, 1.0 - hp_percent))
                if current_hp == 0:
                    status = BossStatus.DEFEATED
                elif current_idx is not None and i == current_idx:
                    status = BossStatus.CURRENT
                elif current_idx is not None and i == current_idx + 1:
                    status = BossStatus.NEXT
                elif current_idx is not None and i > current_idx + 1:
                    status = BossStatus.LOCKED
                else:
                    status = BossStatus.UNKNOWN

            parsed_bosses.append(
                RaidBossData(
                    boss_id=item["boss_id"],
                    name=item["name"],
                    current_hp=current_hp,
                    max_hp=max_hp,
                    hp_percent=hp_percent,
                    cleared_percent=cleared_percent,
                    status=status,
                    elements=item["elements"],
                    icon_id=item["icon_id"],
                    monster_model_id=item["monster_model_id"],
                )
            )

        # Weighted total progress calculation: 1 - sum(current_hp) / sum(max_hp)
        # If any boss has missing/invalid HP or boss list is empty, hide total progress
        if not parsed_bosses or any(
            b.current_hp is None or b.max_hp is None or b.max_hp <= 0 for b in parsed_bosses
        ):
            total_progress = None
            total_current = None
            total_max = None
        else:
            total_max = sum(b.max_hp for b in parsed_bosses)
            total_current = sum(b.current_hp for b in parsed_bosses)
            total_progress = max(0.0, min(1.0, 1.0 - (total_current / total_max))) if total_max > 0 else None

        season_end = manager.get("season_end_date")
        season_start = manager.get("season_start_date")

        return UnionRaidOverviewData(
            guild_name=guild_name,
            difficulty=difficulty,
            level=level,
            total_progress=total_progress,
            total_current_hp=total_current,
            total_max_hp=total_max,
            bosses=parsed_bosses,
            season_end=str(season_end) if season_end else None,
            season_start=str(season_start) if season_start else None,
            fetched_at=fetched_at,
            plugin_version=plugin_version,
        )