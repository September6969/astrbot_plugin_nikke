# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭赛季与首领数据（22）。

数据文件是可维护的导入格式：必须标注 HTTPS 来源与核验日期。仓库默认不内置任何
真实赛季首领或弱点（没有可核实来源时不伪造），入口会显示明确的数据缺口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


class SoloRaidDataError(ValueError):
    """赛季数据不符合导入格式。"""


@dataclass(frozen=True, slots=True)
class Boss:
    boss_id: str
    name: str
    weakness: str
    element: str = ""
    mechanics: str = ""


CST = timezone(timedelta(hours=8))
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class Season:
    season_id: str
    name: str
    source_url: str
    checked_at: str
    bosses: tuple[Boss, ...] = ()
    ends_at: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class SeasonCatalog:
    seasons: tuple[Season, ...] = ()
    available: bool = False
    reason: str = ""

    @classmethod
    def missing(cls, reason: str = "") -> "SeasonCatalog":
        return cls(
            available=False,
            reason=reason
            or "未导入可核实的单人突袭赛季数据；请由维护者导入带来源与核验日期的赛季 JSON。",
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "SeasonCatalog":
        target = Path(path)
        if not target.is_file():
            return cls.missing(f"赛季数据文件不存在：{target.name}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except OSError:
            return cls.missing(f"赛季数据无法读取：{target.name}")
        except (UnicodeError, json.JSONDecodeError):
            return cls.missing("赛季数据不是合法 UTF-8 JSON")
        try:
            return cls.from_payload(payload)
        except SoloRaidDataError as exc:
            return cls.missing(f"赛季数据格式无效：{exc}")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SeasonCatalog":
        if not isinstance(payload, Mapping):
            raise SoloRaidDataError("根节点必须是对象")
        if payload.get("schema_version") != 1:
            raise SoloRaidDataError("schema_version 必须为 1")
        raw = payload.get("seasons")
        if not isinstance(raw, list):
            raise SoloRaidDataError("seasons 必须是数组")
        seasons: list[Season] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise SoloRaidDataError(f"seasons[{index}] 必须是对象")
            season_id = _text(item.get("id"), f"seasons[{index}].id")
            if season_id in seen:
                raise SoloRaidDataError(f"赛季 ID 重复：{season_id}")
            seen.add(season_id)
            bosses_raw = item.get("bosses", [])
            if not isinstance(bosses_raw, list) or not bosses_raw:
                raise SoloRaidDataError(f"seasons[{index}] 至少需要一个首领")
            bosses: list[Boss] = []
            boss_ids: set[str] = set()
            for position, boss in enumerate(bosses_raw):
                if not isinstance(boss, Mapping):
                    raise SoloRaidDataError(f"seasons[{index}].bosses[{position}] 必须是对象")
                boss_id = _text(boss.get("id"), f"seasons[{index}].bosses[{position}].id")
                if boss_id in boss_ids:
                    raise SoloRaidDataError(f"seasons[{index}] 首领 ID 重复：{boss_id}")
                boss_ids.add(boss_id)
                bosses.append(
                    Boss(
                        boss_id=boss_id,
                        name=_text(boss.get("name"), f"seasons[{index}].bosses[{position}].name"),
                        weakness=_text(boss.get("weakness"), f"seasons[{index}].bosses[{position}].weakness"),
                        element=str(boss.get("element") or "").strip(),
                        mechanics=str(boss.get("mechanics") or "").strip(),
                    )
                )
            ends_at = _optional_aware(item.get("ends_at"), f"seasons[{index}].ends_at")
            seasons.append(
                Season(
                    season_id=season_id,
                    name=_text(item.get("name"), f"seasons[{index}].name"),
                    source_url=_https(item.get("source_url"), f"seasons[{index}].source_url"),
                    checked_at=_text(item.get("checked_at"), f"seasons[{index}].checked_at"),
                    bosses=tuple(bosses),
                    ends_at=ends_at,
                    note=str(item.get("note") or "").strip(),
                )
            )
        if not seasons:
            return cls(
                seasons=(),
                available=False,
                reason=str(payload.get("note") or "赛季数据为空；未获得可核实的新赛季首领与弱点。"),
            )
        return cls(seasons=tuple(seasons), available=True)

    def latest(self) -> Season | None:
        return self.seasons[-1] if self.seasons else None


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SoloRaidDataError(f"{field} 缺失")
    return value.strip()


def _optional_aware(value: Any, field: str) -> str:
    """可选结束时间必须是带时区的 ISO 8601；缺失时保持未知。"""
    if value in (None, ""):
        return ""
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SoloRaidDataError(f"{field} 不是合法 ISO 8601") from exc
    if parsed.tzinfo is None:
        raise SoloRaidDataError(f"{field} 必须包含明确时区")
    return parsed.astimezone(timezone.utc).isoformat()


def season_status(season: Season, now: datetime | None = None) -> str:
    """明确区分正在进行与已经结束；不把最近历史当作当前赛季。"""
    if not season.ends_at:
        return "时间未标注"
    try:
        end = datetime.fromisoformat(season.ends_at)
    except ValueError:
        return "时间未标注"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("当前时间必须包含明确时区")
    # 官方公告使用 UTC+9 截止时间，展示时保留该时区以免换算歧义。
    end_text = end.astimezone(JST).strftime("%Y-%m-%d %H:%M") + " UTC+9"
    if current.astimezone(timezone.utc) >= end:
        return f"已结束（截止 {end_text}）"
    return f"进行中（截止 {end_text}）"


def _https(value: Any, field: str) -> str:
    text = _text(value, field)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SoloRaidDataError(f"{field} 必须是无凭据 HTTPS 地址")
    return text


__all__ = ["Boss", "Season", "SeasonCatalog", "SoloRaidDataError", "season_status"]
