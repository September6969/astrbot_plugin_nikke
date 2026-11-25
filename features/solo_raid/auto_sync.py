# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭赛季运行时增量同步：从官方公告与日程快照自动识别最新赛季与停赛提示。"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .seasons import JST, Boss, Season, SeasonCatalog

_SOLO_EN_RE = re.compile(
    r"Solo\s+Raid\s+Season\s+(?P<id>\d+)"
    r"(?:\s*[-–—:]\s*(?P<boss>[A-Za-z0-9 :'\"_-]+?))?"
    r"\s+(?:(?:will\s+be\s+available|is\s+scheduled\s+to\s+open|opens)\s+)?"
    r"(?:from|on)\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>20\d{2})"
    r"(?:,\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?\s*\(UTC\+9\))?",
    re.S | re.I,
)
_RAID_RUSH_RE = re.compile(
    r"Raid\s+Rush.{0,220}?Solo\s+Raid\s+and\s+Union\s+Raid\s+will\s+not\s+be\s+available",
    re.S | re.I,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _iter_announcement_records(announcements: Any) -> list[Any]:
    if announcements is None:
        return []
    cache = getattr(announcements, "cache", None)
    records = getattr(cache, "records", None) if cache is not None else None
    if isinstance(records, dict):
        return list(records.values())
    if isinstance(records, (list, tuple)):
        return list(records)
    return []


def resolve_live_season_catalog(
    base_catalog: SeasonCatalog,
    announcements: Any = None,
    calendar: Any = None,
) -> SeasonCatalog:
    """结合静态核验赛季库与官方缓存公告/日程，自动同步新赛季或休赛公告。"""
    del calendar  # 预留日历联动扩展口，保持零网络阻塞调用
    records = _iter_announcement_records(announcements)
    if not records:
        return base_catalog

    seasons_by_id: dict[str, Season] = {s.season_id: s for s in base_catalog.seasons}
    raid_rush_notice = ""

    for rec in records:
        title = str(getattr(rec, "title", "") or (rec.get("title") if isinstance(rec, dict) else "") or "")
        body = str(
            getattr(rec, "summary_raw", "")
            or getattr(rec, "content", "")
            or (rec.get("content") or rec.get("summary") if isinstance(rec, dict) else "")
            or ""
        )
        combined = f"{title}\n{body}"
        if _RAID_RUSH_RE.search(combined) and not raid_rush_notice:
            raid_rush_notice = "官方公告提示：Raid Rush 期间常规单人突袭/联盟突袭暂停开放。"

        for m in _SOLO_EN_RE.finditer(combined):
            sid = m.group("id")
            month_num = _MONTHS.get(m.group("month").casefold())
            if not month_num:
                continue
            day = int(m.group("day"))
            year = int(m.group("year"))
            hour = int(m.group("hour") or 12)
            minute = int(m.group("minute") or 0)
            second = int(m.group("second") or 0)
            start_jst = datetime(year, month_num, day, hour, minute, second, tzinfo=JST)
            # NIKKE 官方单人突袭通常持续 7 天并截止于 UTC+9 04:59:59。
            end_jst = (start_jst + timedelta(days=7)).replace(hour=4, minute=59, second=59)
            ends_at_utc = end_jst.astimezone(timezone.utc).isoformat()
            boss_hint = (m.group("boss") or "").strip()
            src_url = str(
                getattr(rec, "url", "")
                or (rec.get("url") if isinstance(rec, dict) else "")
                or "https://nikke-en.com/news.html"
            )
            checked = str(
                getattr(rec, "published_at", "")
                or (rec.get("published_at") if isinstance(rec, dict) else "")
                or f"{year:04d}-{month_num:02d}-{day:02d}"
            )[:10]

            if sid in seasons_by_id:
                existing = seasons_by_id[sid]
                if not existing.ends_at:
                    seasons_by_id[sid] = replace(existing, ends_at=ends_at_utc)
                continue

            seasons_by_id[sid] = Season(
                season_id=sid,
                name=f"赛季 {sid}",
                source_url=src_url if src_url.startswith("https://") else "https://nikke-en.com/news.html",
                checked_at=checked,
                bosses=(
                    Boss(
                        boss_id=f"solo-{sid}-announced",
                        name=boss_hint or f"Season {sid} Boss（见官方公告）",
                        weakness="待公告/手选弱点",
                        element="",
                        mechanics="由官方更新公告自动识别开启时间；弱点未标明时可在工作台手动选择对应属性。",
                    ),
                ),
                ends_at=ends_at_utc,
                note=f"自动同步自官方公告《{title[:60]}》",
            )

    if not seasons_by_id and not raid_rush_notice:
        return base_catalog

    ordered = tuple(
        sorted(
            seasons_by_id.values(),
            key=lambda s: int(s.season_id) if s.season_id.isdigit() else 0,
        )
    )
    if raid_rush_notice and ordered:
        latest = ordered[-1]
        note = f"{latest.note}；{raid_rush_notice}" if latest.note else raid_rush_notice
        ordered = ordered[:-1] + (replace(latest, note=note),)
    return SeasonCatalog(seasons=ordered, available=bool(ordered), reason=base_catalog.reason)


__all__ = ["resolve_live_season_catalog"]
