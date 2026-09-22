import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    BossStatus,
    PreviousSeasonSummary,
    RaidBossData,
    RaidResponseCoverage,
    RaidState,
    UnionRaidOverviewData,
)


class UnionRaidBuilder:
    def __init__(self, manifest_path: Path | str | None = None):
        self._seasons: list[dict[str, Any]] = []
        paths = [
            Path(manifest_path) if manifest_path else None,
            Path(__file__).resolve().parents[2] / "assets" / "raid_raid_list.json",
            Path("data") / "nikke" / "blabla-manifests" / "raid_raid_list.json",
        ]
        for p in paths:
            if p and p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        self._seasons = data
                        break
                except Exception:
                    pass

    def resolve_response_state(self, payload: Any, *, now: datetime) -> RaidState:
        """根据同一查询时钟解析当前 API 响应状态。"""
        response = payload if isinstance(payload, dict) else {}
        manager = response.get("manager_info")
        levels = response.get("level_info")
        return self.resolve_raid_state(
            manager,
            levels,
            now.timestamp(),
            self._seasons,
        )

    def latest_completed_season_id(self, *, now: datetime) -> str | None:
        """返回时钟时刻前最近已结束且有明确 ID 的赛季。"""
        latest = max(
            (season for season in self._seasons if season.get("end_ts", 0) <= now.timestamp()),
            key=lambda season: season.get("id", 0),
            default=None,
        )
        if latest is None:
            return None
        season_id = self._identifier(latest.get("id"))
        return season_id or None

    @classmethod
    def resolve_raid_state(
        cls,
        manager_info: Any,
        raw_levels: Any,
        now_ts: float | None = None,
        seasons: list[dict[str, Any]] | None = None,
    ) -> RaidState:
        if not isinstance(manager_info, dict):
            return RaidState.UNKNOWN

        now_ts = now_ts if now_ts is not None else time.time()
        manager_id = str(manager_info.get("id", "")).strip()

        # Check explicit manager_id
        if manager_id and manager_id != "0":
            end_date_str = str(manager_info.get("season_end_date") or "").strip()
            calc_date_str = str(
                manager_info.get("season_rank_calculate_date")
                or manager_info.get("caculate_date")
                or ""
            ).strip()

            end_ts = None
            if end_date_str:
                try:
                    end_ts = datetime.fromisoformat(end_date_str).timestamp()
                except ValueError:
                    pass

            calc_ts = None
            if calc_date_str:
                try:
                    calc_ts = datetime.fromisoformat(calc_date_str).timestamp()
                except ValueError:
                    pass

            if end_ts is not None:
                if now_ts < end_ts:
                    return RaidState.ACTIVE
                if calc_ts is not None and now_ts <= calc_ts:
                    return RaidState.SETTLEMENT
                return RaidState.OFFSEASON

            if isinstance(raw_levels, list) and len(raw_levels) > 0:
                return RaidState.ACTIVE
            return RaidState.UNKNOWN

        # If raw_levels contains bosses, it's ACTIVE
        if isinstance(raw_levels, list) and len(raw_levels) > 0:
            for lvl in raw_levels:
                if isinstance(lvl, dict) and isinstance(lvl.get("boss_info"), list) and len(lvl["boss_info"]) > 0:
                    return RaidState.ACTIVE

        # manager_id == "0": explicit off-season response from official API
        if manager_id == "0":
            if seasons:
                for s in sorted(seasons, key=lambda x: x.get("start_ts", 0), reverse=True):
                    start = s.get("start_ts", 0)
                    end = s.get("end_ts", 0)
                    calc = s.get("caculate_ts", end)
                    if start <= now_ts < end:
                        return RaidState.ACTIVE
                    if end <= now_ts <= calc:
                        return RaidState.SETTLEMENT
                    if now_ts > calc:
                        return RaidState.OFFSEASON
            return RaidState.OFFSEASON

        return RaidState.UNKNOWN

    @staticmethod
    def _identifier(value: Any) -> str:
        """只接受非空文本或明确的整数标识，不把容器转成伪 ID。"""
        if isinstance(value, str):
            return value.strip()
        if type(value) is int:
            return str(value)
        return ""

    @staticmethod
    def _optional_text(value: Any) -> str:
        """展示文本只接受去除首尾空白后的字符串，拒绝容器和隐式数值转换。"""
        return value.strip() if isinstance(value, str) else ""

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
        now: datetime | float | None = None,
        previous_season: PreviousSeasonSummary | None = None,
    ) -> UnionRaidOverviewData:
        """Parse raw GetUnionRaidLevelInfo response into UnionRaidOverviewData."""
        payload = level_info_payload if isinstance(level_info_payload, dict) else {}
        raw_levels = payload.get("level_info")
        manager = payload.get("manager_info")
        manager = manager if isinstance(manager, dict) else {}

        now_ts = (
            now.timestamp()
            if isinstance(now, datetime)
            else (float(now) if isinstance(now, (int, float)) else time.time())
        )
        raid_state = self.resolve_raid_state(manager, raw_levels, now_ts, self._seasons)

        season_end = manager.get("season_end_date")
        season_start = manager.get("season_start_date")
        manager_id = str(manager.get("id") or "").strip()
        season_id = manager_id if manager_id and manager_id != "0" else None
        season_name = f"第 {int(season_id) % 1000000} 季" if season_id and season_id.isdigit() else None

        if raid_state == RaidState.OFFSEASON:
            if previous_season is None and self._seasons:
                latest = max(
                    (s for s in self._seasons if s.get("end_ts", 0) <= now_ts),
                    key=lambda x: x.get("id", 0),
                    default=None,
                )
                if latest:
                    s_id = str(latest.get("id"))
                    s_num = int(s_id) % 1000000 if s_id.isdigit() else None
                    previous_season = PreviousSeasonSummary(
                        season_id=s_id,
                        season_number=s_num,
                        start_at=str(latest.get("season_start_date") or ""),
                        end_at=str(latest.get("season_end_date") or ""),
                        settled_at=str(latest.get("caculate_date") or ""),
                    )
            return UnionRaidOverviewData(
                guild_name=guild_name,
                difficulty=None,
                level=None,
                total_progress=None,
                total_current_hp=None,
                total_max_hp=None,
                bosses=[],
                season_end=str(season_end) if season_end else None,
                season_start=str(season_start) if season_start else None,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
                response_coverage=RaidResponseCoverage.CURRENT_RESPONSE,
                partial_boss_records=False,
                raid_state=RaidState.OFFSEASON,
                previous_season=previous_season,
                current_season_name=season_name,
                season_id=season_id,
            )

        if raid_state == RaidState.SETTLEMENT:
            return UnionRaidOverviewData(
                guild_name=guild_name,
                difficulty=None,
                level=None,
                total_progress=None,
                total_current_hp=None,
                total_max_hp=None,
                bosses=[],
                season_end=str(season_end) if season_end else None,
                season_start=str(season_start) if season_start else None,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
                response_coverage=RaidResponseCoverage.CURRENT_RESPONSE,
                partial_boss_records=False,
                raid_state=RaidState.SETTLEMENT,
                previous_season=previous_season,
                current_season_name=season_name,
                season_id=season_id,
            )

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
            boss_id = self._identifier(raw_boss_id)
            if not boss_id:
                partial_boss_records = True
            elif boss_id in seen_boss_ids:
                partial_boss_records = True
            else:
                seen_boss_ids.add(boss_id)

            current_hp = self._optional_integer(raw.get("current_hp"), clamp_negative=True)
            max_hp = self._optional_integer(raw.get("max_hp"))

            names = raw.get("name_localvalues", {})
            name = ""
            if isinstance(names, dict):
                for locale in ("zh-cn", "zh-tw", "zh_tw", "en", "ja", "ko"):
                    name = self._optional_text(names.get(locale))
                    if name:
                        break
            if not name:
                name = self._optional_text(raw.get("name_localkey")) or f"Boss {boss_id or '?'}"

            elements = raw.get("element_id", [])
            element_list = [identifier for value in elements if (identifier := self._identifier(value))] if isinstance(elements, list) else []

            boss_items.append({
                "boss_id": boss_id,
                "name": name,
                "current_hp": current_hp,
                "max_hp": max_hp,
                "elements": element_list,
                "icon_id": self._identifier(raw.get("icon_id")) or None,
                "monster_model_id": self._identifier(raw.get("monster_model_id")) or None,
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
            raid_state=raid_state,
            previous_season=previous_season,
            current_season_name=season_name,
            season_id=season_id,
        )
