# SPDX-License-Identifier: GPL-3.0-or-later
"""从受控响应构建 ProfileDashboardData。"""

from __future__ import annotations

import re
import math
from datetime import datetime, timezone, timedelta
from typing import Any

from .campaign_stage_resolver import CampaignStageResolver
from .currency_registry import CurrencyRegistry
from .memorial_registry import MemorialCategoryRegistry
from .profile_models import (
    DailyTowerInfo,
    MemorialCountData,
    ProfileDashboardData,
    RecycleResearchData,
    SimulationRoomDailyRecord,
)
from .research_registry import research_labels, research_presentation_label


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_MAX_INTEGER_DIGITS = 12
_PROFILE_DISPLAY_TZ = timezone(timedelta(hours=8))
_MIN_PROFILE_TIMESTAMP = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_PROFILE_TIMESTAMP = datetime(2100, 1, 1, tzinfo=timezone.utc)


def _optional_int(value: Any) -> int | None:
    """只接受整数或已确认的十进制整数字符串，不把浮点数截断。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or not _INTEGER_RE.fullmatch(text):
            return None
        if len(text.lstrip("+-")) > _MAX_INTEGER_DIGITS:
            return None
        try:
            candidate = int(text)
        except ValueError:
            return None
    else:
        return None
    if candidate < 0 or len(str(candidate)) > _MAX_INTEGER_DIGITS:
        return None
    return candidate


def _optional_str(value: Any, *, max_length: int = 200) -> str | None:
    """仅把标量转换为显示文本，拒绝容器 repr 和控制字符。"""
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    text = text.strip()
    return text[:max_length] or None


def _first_optional_str(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in source:
            value = _optional_str(source[key])
            if value is not None:
                return value
    return None


def _optional_ratio(value: Any) -> float | None:
    """解析 0..1 的容量比例；不把百分数或异常值静默转换。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        return None
    return parsed


def parse_profile_created_at(value: Any) -> str | None:
    """把已确认的 Profile 注册时间统一为 UTC+8 日期文本。

    Bla 的历史响应使用 Unix 秒级时间戳；兼容已确认的毫秒时间戳和
    ISO-8601 响应。超界、布尔值、浮点数和无法解析的文本一律未知。
    """
    if value is None or isinstance(value, bool):
        return None

    timestamp: float | None = None
    if isinstance(value, int):
        digits = str(abs(value))
        if len(digits) == 10:
            timestamp = float(value)
        elif len(digits) == 13:
            timestamp = value / 1000.0
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{10}", text):
            timestamp = float(text)
        elif re.fullmatch(r"\d{13}", text):
            timestamp = int(text) / 1000.0
        elif text:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_PROFILE_DISPLAY_TZ)
                parsed = parsed.astimezone(_PROFILE_DISPLAY_TZ)
                if _MIN_PROFILE_TIMESTAMP <= parsed.astimezone(timezone.utc) < _MAX_PROFILE_TIMESTAMP:
                    return parsed.strftime("%Y-%m-%d")
            return None
    if timestamp is None:
        return None
    try:
        parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    if not (_MIN_PROFILE_TIMESTAMP <= parsed < _MAX_PROFILE_TIMESTAMP):
        return None
    return parsed.astimezone(_PROFILE_DISPLAY_TZ).strftime("%Y-%m-%d")


def _format_campaign_progress(
    value: Any,
    *,
    mode: str,
    resolver: CampaignStageResolver | None,
) -> str | None:
    """将内部进度 ID 映射到静态表中的关卡名，未知时保留原始 ID。"""
    raw = _optional_str(value)
    if raw is None:
        return None
    if not re.fullmatch(r"\d+", raw):
        return raw
    if resolver is None:
        return f"未映射 · ID {raw}"
    stage = resolver.resolve_id(raw, mode_hint=mode)
    return stage.name if stage is not None else f"未映射 · ID {raw}"


def _format_unmapped_internal_id(value: Any) -> str | None:
    """内部资料 ID 没有来源映射时保持中性，不伪装成等级或名称。"""
    raw = _optional_str(value)
    if raw is None:
        return None
    return f"未映射 · ID {raw}" if re.fullmatch(r"\d+", raw) else raw


def _parse_researches(value: Any) -> tuple[list[RecycleResearchData] | None, bool]:
    if not isinstance(value, list):
        return None, False
    rows: list[RecycleResearchData] = []
    partial = False
    for item in value:
        if not isinstance(item, dict):
            # 保留列表位置，但不给坏条目补内部 ID 或数值。
            rows.append(RecycleResearchData(None, None, None))
            partial = True
            continue
        tid = _optional_str(item.get("tid"))
        level = _optional_int(item.get("lv"))
        exp = _optional_int(item.get("exp"))
        if any(key not in item for key in ("tid", "lv", "exp")):
            partial = True
        if "tid" in item and tid is None:
            partial = True
        if ("lv" in item and level is None) or ("exp" in item and exp is None):
            partial = True
        display_name, category = research_labels(tid)
        rows.append(
            RecycleResearchData(
                tid,
                level,
                exp,
                display_name,
                category,
                research_presentation_label(tid),
            )
        )
    return rows, partial


def _parse_memorials(value: Any) -> tuple[list[MemorialCountData] | None, bool]:
    if not isinstance(value, list):
        return None, False
    rows: list[MemorialCountData] = []
    partial = False
    for item in value:
        if not isinstance(item, dict):
            rows.append(MemorialCountData(None, None))
            partial = True
            continue
        category = _optional_str(item.get("category"))
        count = _optional_int(item.get("count"))
        group = MemorialCategoryRegistry.group_for(category)
        display_name = MemorialCategoryRegistry.GROUP_NAMES.get(group) if group else None
        # category 不做未经证实的名称映射；未知分类只保持原始状态并由 registry 诊断。
        if "count" not in item or count is None:
            partial = True
        rows.append(MemorialCountData(category, count, display_name, group))
    return rows, partial


def _parse_daily_tower(value: Any) -> tuple[list[DailyTowerInfo] | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, list):
        return None, True
    result: list[DailyTowerInfo] = []
    partial = False
    for item in value:
        if not isinstance(item, dict):
            result.append(DailyTowerInfo({}))
            partial = True
            continue
        # raw 是脱离账号身份的每日记录副本；renderer 不直接读取它。
        display_name = _first_optional_str(item, "name", "tower_name", "type")
        remaining = _optional_int(item.get("remaining"))
        if "remaining" in item and remaining is None:
            partial = True
        result.append(DailyTowerInfo(dict(item), display_name, remaining))
    return result, partial


def _parse_sim_room_record(value: Any) -> tuple[SimulationRoomDailyRecord | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, dict):
        return None, True
    chapter = _optional_int(value.get("chapter"))
    difficulty = _optional_int(value.get("difficulty"))
    partial = ("chapter" in value and chapter is None) or ("difficulty" in value and difficulty is None)
    score = None
    for key in ("score", "best_score"):
        if key in value:
            score = _optional_int(value.get(key))
            if score is None:
                partial = True
            break
    if chapter not in {None, 1, 2, 3}:
        # 只有 A/B/C 有确认展示合同，未知章节不能拼成看似合法的标签。
        chapter = None
        partial = True
    if difficulty is None and ("chapter" in value or "difficulty" in value):
        partial = True
    return SimulationRoomDailyRecord(chapter, difficulty, dict(value), score), partial


def _parse_daily(value: Any) -> tuple[dict[str, Any], bool]:
    """把 Daily 单条 progress 转成 renderer 可消费的结构化字段。"""
    if value is None:
        return {
            "storage_fullness": None,
            "intercept_remaining": None,
            "rookie_arena_remaining": None,
            "special_arena_remaining": None,
            "counsel_remaining": None,
            "dispatch_completed": None,
            "dispatch_in_progress": None,
            "tower_daily_info": None,
            "sim_room_daily_record": None,
        }, False
    if not isinstance(value, dict):
        return {}, True

    fields = {
        "storage_fullness": _optional_ratio(value.get("outpost_battle_storage_fullness")),
        "intercept_remaining": _optional_int(value.get("intercept_remaining_tickets")),
        "rookie_arena_remaining": _optional_int(value.get("rookie_arena_remaining_count")),
        "special_arena_remaining": _optional_int(value.get("special_arena_remaining_count")),
        "counsel_remaining": _optional_int(value.get("counsel_remaining_count")),
        "dispatch_completed": _optional_int(value.get("dispatch_completed_count")),
        "dispatch_in_progress": _optional_int(value.get("dispatch_in_progress_count")),
    }
    partial = False
    for source_key, field_name in (
        ("outpost_battle_storage_fullness", "storage_fullness"),
        ("intercept_remaining_tickets", "intercept_remaining"),
        ("rookie_arena_remaining_count", "rookie_arena_remaining"),
        ("special_arena_remaining_count", "special_arena_remaining"),
        ("counsel_remaining_count", "counsel_remaining"),
        ("dispatch_completed_count", "dispatch_completed"),
        ("dispatch_in_progress_count", "dispatch_in_progress"),
    ):
        if source_key in value and fields[field_name] is None:
            partial = True
    tower, tower_partial = _parse_daily_tower(value.get("tower_daily_info_list"))
    sim_room, sim_partial = _parse_sim_room_record(value.get("sim_room_daily_best_record"))
    fields["tower_daily_info"] = tower
    fields["sim_room_daily_record"] = sim_room
    return fields, partial or tower_partial or sim_partial


class ProfileBuilder:
    def __init__(
        self,
        campaign_resolver: CampaignStageResolver | None = None,
        currency_registry: CurrencyRegistry | None = None,
        memorial_registry: MemorialCategoryRegistry | None = None,
    ):
        self.campaign_resolver = campaign_resolver
        self.currency_registry = currency_registry or CurrencyRegistry()
        self.memorial_registry = memorial_registry or MemorialCategoryRegistry()

    def build(
        self,
        *,
        account: dict[str, Any],
        basic: dict[str, Any],
        outpost: dict[str, Any],
        roster: list[Any] | None,
        fetched_at: str,
        plugin_version: str,
        outpost_available: bool | None = None,
        roster_available: bool | None = None,
        daily: dict[str, Any] | None = None,
        daily_available: bool | None = None,
    ) -> ProfileDashboardData:
        basic = basic if isinstance(basic, dict) else {}
        outpost = outpost if isinstance(outpost, dict) else {}
        commander_name = (
            _optional_str(basic.get("nickname"))
            or _first_optional_str(account, "nickname", "role_name")
            or "指挥官"
        )
        area_id = _optional_str(account.get("area_id")) or ""

        synchro_level = _optional_int(outpost.get("synchro_level"))
        outpost_battle_level = _optional_int(outpost.get("outpost_battle_level"))

        normal_campaign = _format_campaign_progress(
            _first_optional_str(basic, "progress_normal_campaign", "progress_campaign_normal"),
            mode="NORMAL",
            resolver=self.campaign_resolver,
        )
        hard_campaign = _format_campaign_progress(
            _first_optional_str(basic, "progress_hard_campaign", "progress_campaign_hard"),
            mode="HARD",
            resolver=self.campaign_resolver,
        )

        basic_count = _optional_int(basic.get("character_count"))
        roster_partial = False
        valid_roster: list[tuple[int, int]] = []
        if roster is not None:
            for item in roster:
                if not isinstance(item, dict):
                    roster_partial = True
                    continue
                level = _optional_int(item.get("lv"))
                combat = _optional_int(item.get("combat"))
                if level is None or combat is None:
                    roster_partial = True
                    continue
                valid_roster.append((level, combat))

        if basic_count is not None:
            character_count = basic_count
        elif roster is not None and not roster_partial:
            character_count = len(roster)
        else:
            character_count = None

        if roster is not None and roster and not roster_partial and valid_roster:
            max_level = max(level for level, _ in valid_roster)
            max_combat = max(combat for _, combat in valid_roster)
        else:
            max_level = None
            max_combat = None

        commander_level = _optional_int(basic.get("lv"))
        team_combat = _optional_int(basic.get("team_combat"))
        created_at = parse_profile_created_at(basic.get("created_at"))
        character_costume_count = _optional_int(basic.get("character_costume_count"))
        progress_tribe_tower = _optional_str(basic.get("progress_tribe_tower"))
        sim_room_overclock_score = _optional_str(
            basic.get("sim_room_overclock_current_sub_season_high_score")
        )
        sim_room_overclock_season = _optional_str(
            basic.get("sim_room_overclock_latest_season_high_score")
        )

        infra_core_level = _optional_str(outpost.get("infra_core_level"))
        tactic_academy_class = _format_unmapped_internal_id(outpost.get("tactic_academy_class"))
        tactic_academy_lesson = _format_unmapped_internal_id(outpost.get("tactic_academy_lesson"))
        jukebox_count = _optional_str(outpost.get("jukebox_count"))

        research_data, research_partial = _parse_researches(
            outpost.get("recycle_room_researches")
        )
        memorial_data, memorial_partial = _parse_memorials(outpost.get("memorial_counts"))
        jukebox_value = _optional_int(outpost.get("jukebox_count"))
        if "jukebox_count" in outpost and jukebox_value is None:
            memorial_partial = True
        memorial_summary, memorial_summary_partial = self.memorial_registry.summarize(
            memorial_data,
            jukebox_count=jukebox_value,
        )
        memorial_partial = memorial_partial or memorial_summary_partial

        currencies, currencies_partial = self.currency_registry.parse(basic.get("currencies"))
        daily_fields, daily_partial = _parse_daily(daily)

        return ProfileDashboardData(
            commander_name=commander_name,
            area_id=area_id,
            synchro_level=synchro_level,
            outpost_battle_level=outpost_battle_level,
            normal_campaign=normal_campaign,
            hard_campaign=hard_campaign,
            character_count=character_count,
            max_level=max_level,
            max_combat=max_combat,
            fetched_at=fetched_at,
            plugin_version=plugin_version,
            commander_level=commander_level,
            team_combat=team_combat,
            created_at=created_at,
            character_costume_count=character_costume_count,
            progress_tribe_tower=progress_tribe_tower,
            sim_room_overclock_score=sim_room_overclock_score,
            infra_core_level=infra_core_level,
            tactic_academy_class=tactic_academy_class,
            tactic_academy_lesson=tactic_academy_lesson,
            jukebox_count=jukebox_count,
            # 摘要字段保留兼容性，但不再从可能部分的明细推导总数。
            recycle_room_summary=None,
            memorial_summary=memorial_summary,
            recycle_room_researches=research_data,
            memorial_counts=memorial_data,
            outpost_available=outpost_available,
            roster_available=roster_available,
            roster_partial=roster_partial,
            research_partial=research_partial,
            memorial_partial=memorial_partial,
            daily_available=daily_available,
            storage_fullness=daily_fields.get("storage_fullness"),
            intercept_remaining=daily_fields.get("intercept_remaining"),
            rookie_arena_remaining=daily_fields.get("rookie_arena_remaining"),
            special_arena_remaining=daily_fields.get("special_arena_remaining"),
            counsel_remaining=daily_fields.get("counsel_remaining"),
            dispatch_completed=daily_fields.get("dispatch_completed"),
            dispatch_in_progress=daily_fields.get("dispatch_in_progress"),
            tower_daily_info=daily_fields.get("tower_daily_info"),
            sim_room_daily_record=daily_fields.get("sim_room_daily_record"),
            sim_room_overclock_subseason=sim_room_overclock_score,
            sim_room_overclock_season=sim_room_overclock_season,
            currencies=currencies,
            currencies_partial=currencies_partial,
            daily_partial=daily_partial,
        )
