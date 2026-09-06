# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid data builder for parsing and normalizing API responses."""

from __future__ import annotations

from typing import Any

from .union_raid_models import BossStatus, RaidBossData, RaidResponseCoverage, UnionRaidOverviewData


class UnionRaidBuilder:
    @staticmethod
    def _optional_integer(value: Any, *, clamp_negative: bool = False) -> int | None:
        """只接受明确的整型值；仅 HP 调用方保留负数归零边界。"""
        parsed: int | None = None
        if type(value) is int:
            parsed = value
        elif isinstance(value, str):
            normalized = value.strip()
            digits = normalized[1:] if normalized[:1] in {"+", "-"} else normalized
            if digits and digits.isascii() and digits.isdecimal():
                parsed = int(normalized)
        if parsed is None:
            return None
        if parsed < 0:
            return 0 if clamp_negative else None
        return parsed

    def build(
        self,
        *,
        guild_name: str,
        level_info_payload: dict[str, Any],
        fetched_at: str,
        plugin_version: str,
    ) -> UnionRaidOverviewData:
        """Parse raw GetUnionRaidLevelInfo response into UnionRaidOverviewData."""
        payload = level_info_payload if isinstance(level_info_payload, dict) else {}
        raw_levels = payload.get("level_info")
        manager = payload.get("manager_info")
        manager = manager if isinstance(manager, dict) else {}

        # level_info 的排序及多项语义尚未确认，绝不把首项猜成当前阶段。
        if isinstance(raw_levels, list) and len(raw_levels) == 1 and isinstance(raw_levels[0], dict):
            level_obj: dict[str, Any] | None = raw_levels[0]
            response_coverage = RaidResponseCoverage.CURRENT_RESPONSE
        else:
            level_obj = None
            response_coverage = RaidResponseCoverage.UNKNOWN_COVERAGE

        difficulty = self._optional_integer(level_obj.get("difficulty")) if level_obj else None
        level = self._optional_integer(level_obj.get("level")) if level_obj else None
        raw_bosses = level_obj.get("boss_info") if level_obj else []
        partial_boss_records = not isinstance(raw_bosses, list)
        if not isinstance(raw_bosses, list):
            raw_bosses = []

        # Parse raw bosses
        boss_items: list[dict[str, Any]] = []
        seen_boss_ids: set[str] = set()
        for raw in raw_bosses:
            if not isinstance(raw, dict):
                partial_boss_records = True
                continue
            raw_boss_id = raw.get("boss_id")
            boss_id = str(raw_boss_id) if raw_boss_id not in (None, "") else ""
            if not boss_id or boss_id in seen_boss_ids:
                partial_boss_records = True
            seen_boss_ids.add(boss_id)

            current_hp = self._optional_integer(raw.get("current_hp"), clamp_negative=True)
            max_hp = self._optional_integer(raw.get("max_hp"))

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

        if partial_boss_records:
            response_coverage = RaidResponseCoverage.UNKNOWN_COVERAGE

        parsed_bosses: list[RaidBossData] = []
        for i, item in enumerate(boss_items):
            max_hp = item["max_hp"]
            current_hp = item["current_hp"]

            if max_hp is None or current_hp is None or max_hp <= 0:
                status = BossStatus.UNKNOWN
                hp_percent = None
                cleared_percent = None
            else:
                # DTO、文本及加权汇总统一使用有效血量范围。
                current_hp = min(current_hp, max_hp)
                hp_percent = current_hp / max_hp
                cleared_percent = max(0.0, min(1.0, 1.0 - hp_percent))
                if current_hp == 0:
                    status = BossStatus.DEFEATED
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

        # 仅在单个、未发现部分记录的响应内做已返回 Boss 的加权汇总。
        if response_coverage != RaidResponseCoverage.CURRENT_RESPONSE or not parsed_bosses or any(
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
            response_coverage=response_coverage,
            partial_boss_records=partial_boss_records,
        )
