# SPDX-License-Identifier: GPL-3.0-or-later
"""从受控响应构建 ProfileDashboardData。"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

from .campaign_stage_resolver import CampaignStageResolver
from .memorial_registry import MemorialCategoryRegistry
from .profile_models import CurrencyItem, MemorialCountData, ProfileDashboardData, RecycleResearchData
from .research_registry import research_labels


_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_MAX_INTEGER_DIGITS = 12
_PROFILE_DISPLAY_TZ = timezone(timedelta(hours=8))
_MIN_PROFILE_TIMESTAMP = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MAX_PROFILE_TIMESTAMP = datetime(2100, 1, 1, tzinfo=timezone.utc)

CORE_CURRENCIES: list[tuple[int, str, str]] = [
    (99, "珠宝", "jewel"),
    (1000, "信用点", "credit"),
    (2000, "战斗数据辑", "battle_data"),
    (3000, "芯尘", "core_dust"),
    (5100, "高级招募券", "advanced_ticket"),
    (5200, "普通招募券", "recruit_ticket"),
    (11000, "躯体标签", "body_label"),
    (12000, "联盟芯片", "union_chip"),
]


def format_compact_number(value: int | float | None) -> str:
    """格式化紧凑数字，如 26M, 130M, 10.5K, <1000 整数。"""
    if value is None:
        return "—"
    try:
        val = int(value)
    except (ValueError, TypeError):
        return "—"
    if val < 0:
        return str(val)
    if val >= 1_000_000:
        m_val = val / 1_000_000.0
        if val % 1_000_000 == 0:
            return f"{int(m_val)}M"
        return f"{m_val:.1f}M"
    elif val >= 1_000:
        k_val = val / 1_000.0
        if val % 1_000 == 0:
            return f"{int(k_val)}K"
        return f"{k_val:.1f}K"
    else:
        return f"{val:,}"


def _parse_storage_fullness(value: Any) -> float | None:
    """解析保管箱容量比例（0.059 -> 5.9%）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        f_val = float(value)
    except (ValueError, TypeError):
        return None
    if f_val < 0:
        return None
    if f_val <= 1.0:
        return round(f_val * 100.0, 1)
    return round(f_val, 1)


def _parse_sim_room_record(best_record: Any) -> str | None:
    """解析模拟室每日最佳记录（如 difficulty: 5, chapter: 3 -> 5-C）。"""
    if not isinstance(best_record, dict):
        return None
    diff = _optional_int(best_record.get("difficulty"))
    chap = _optional_int(best_record.get("chapter"))
    if diff is None:
        return None
    if chap is not None:
        letter = chr(64 + chap) if 1 <= chap <= 26 else str(chap)
        return f"{diff}-{letter}"
    return str(diff)


def _parse_currencies(currencies_raw: Any) -> list[CurrencyItem] | None:
    """解析 8 格核心资源。"""
    if not isinstance(currencies_raw, list):
        return None
    val_map: dict[int, int] = {}
    for item in currencies_raw:
        if isinstance(item, dict):
            c_type = _optional_int(item.get("type"))
            c_val = _optional_int(item.get("value"))
            if c_type is not None and c_val is not None:
                val_map[c_type] = c_val
    items: list[CurrencyItem] = []
    for c_type, name, icon_key in CORE_CURRENCIES:
        val = val_map.get(c_type, 0)
        items.append(
            CurrencyItem(
                type=c_type,
                value=val,
                display_name=name,
                icon_key=icon_key,
                compact_value=format_compact_number(val),
            )
        )
    return items



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
        rows.append(RecycleResearchData(tid, level, exp, display_name, category))
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
        # category 不做未经证实的名称映射；缺失时由 renderer 使用中性名称。
        if "count" not in item or count is None:
            partial = True
        rows.append(MemorialCountData(category, count))
    return rows, partial


class ProfileBuilder:
    def __init__(self, campaign_resolver: CampaignStageResolver | None = None):
        self.campaign_resolver = campaign_resolver

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

        infra_core_level = _optional_str(outpost.get("infra_core_level"))
        tactic_academy_class = _format_unmapped_internal_id(outpost.get("tactic_academy_class"))
        tactic_academy_lesson = _format_unmapped_internal_id(outpost.get("tactic_academy_lesson"))
        jukebox_count = _optional_str(outpost.get("jukebox_count"))

        research_data, research_partial = _parse_researches(
            outpost.get("recycle_room_researches")
        )
        memorial_data, memorial_partial = _parse_memorials(outpost.get("memorial_counts"))

        # Daily contents parsing
        daily_dict = daily if isinstance(daily, dict) else {}
        daily_partial = False
        if daily_available and not daily_dict:
            daily_partial = True

        raw_storage = (
            daily_dict.get("outpost_battle_storage_fullness")
            if "outpost_battle_storage_fullness" in daily_dict
            else outpost.get("outpost_battle_storage_fullness")
        )
        storage_fullness = _parse_storage_fullness(raw_storage)
        intercept_remaining = _optional_int(daily_dict.get("intercept_remaining_tickets"))
        rookie_arena_remaining = _optional_int(daily_dict.get("rookie_arena_remaining_count"))
        special_arena_remaining = _optional_int(daily_dict.get("special_arena_remaining_count"))
        counsel_remaining = _optional_int(daily_dict.get("counsel_remaining_count"))
        dispatch_completed = _optional_int(daily_dict.get("dispatch_completed_count"))
        dispatch_in_prog = _optional_int(daily_dict.get("dispatch_in_progress_count"))
        dispatch_total = (
            dispatch_completed + dispatch_in_prog
            if dispatch_completed is not None and dispatch_in_prog is not None
            else None
        )

        tower_daily_list = daily_dict.get("tower_daily_info_list")
        tower_daily_remaining: int | None = None
        if isinstance(tower_daily_list, list):
            tower_daily_remaining = sum(
                _optional_int(t.get("remaining_count")) or 0
                for t in tower_daily_list
                if isinstance(t, dict)
            )

        sim_room_daily_record = _parse_sim_room_record(daily_dict.get("sim_room_daily_best_record"))
        sim_room_overclock_subseason = _optional_int(
            basic.get("sim_room_overclock_current_sub_season_high_score")
        )
        sim_room_overclock_season = _optional_int(
            basic.get("sim_room_overclock_latest_season_high_score")
        )

        currencies = _parse_currencies(basic.get("currencies"))
        memorial_summary_dict = MemorialCategoryRegistry.summarize_memorials(
            outpost.get("memorial_counts"), jukebox_count
        )

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
            memorial_summary=None,
            recycle_room_researches=research_data,
            memorial_counts=memorial_data,
            outpost_available=outpost_available,
            roster_available=roster_available,
            daily_available=daily_available,
            roster_partial=roster_partial,
            research_partial=research_partial,
            memorial_partial=memorial_partial,
            daily_partial=daily_partial,
            storage_fullness=storage_fullness,
            intercept_remaining=intercept_remaining,
            rookie_arena_remaining=rookie_arena_remaining,
            special_arena_remaining=special_arena_remaining,
            counsel_remaining=counsel_remaining,
            dispatch_completed=dispatch_completed,
            dispatch_total=dispatch_total,
            tower_daily_remaining=tower_daily_remaining,
            sim_room_daily_record=sim_room_daily_record,
            sim_room_overclock_subseason=sim_room_overclock_subseason,
            sim_room_overclock_season=sim_room_overclock_season,
            currencies=currencies,
            memorial_summary_dict=memorial_summary_dict,
        )
