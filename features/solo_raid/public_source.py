# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭公开赛季索引的解析与幂等写入。

只读取 NikkeHub 公开赛季页面中的赛季号、首领名、属性、弱点和起止日期；
不复制攻略正文、地图或首领图片。页面未列出的属性保持为空。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

_SEASON_ITEM = re.compile(
    r'<a class="ayneWG_seasonSwitchItem[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>\s*'
    r'<span class="ayneWG_seasonSwitchTitle">單人突襲 賽季 (?P<id>\d+)<!-- -->, (?P<name>[^<]+)</span>\s*'
    r'<span class="ayneWG_seasonMeta">(?P<meta>[^<]+)</span>',
    re.S,
)
_BOSS = re.compile(
    r'ayneWG_bossName">(?P<name>[^<]+)</h3>(?P<body>.*?)</li>', re.S
)
_ATTR = re.compile(r"<dt>(?P<key>[^<]+)</dt><dd[^>]*>(?P<value>.*?)</dd>", re.S)
_DATES = re.compile(r"(\d{1,2})/(\d{1,2})\([^)]*\)\s*(\d{1,2}):(\d{2})\s*~\s*(\d{1,2})/(\d{1,2})\([^)]*\)\s*(\d{1,2}):(\d{2})")


def _clean(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).replace("代碼", "").strip()


def parse_season_index(html: str) -> list[dict[str, Any]]:
    if not isinstance(html, str):
        raise ValueError("赛季索引必须是文本")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _SEASON_ITEM.finditer(html):
        season_id = match.group("id")
        if season_id in seen:
            continue
        seen.add(season_id)
        rows.append({
            "id": season_id,
            "name": match.group("name").strip(),
            "meta": match.group("meta").strip(),
            "source_url": (
                "https://nikkehub.com" + match.group("href")
                if match.group("href").startswith("/")
                else match.group("href")
            ),
        })
    if not rows:
        raise ValueError("公开赛季索引为空")
    return rows


def parse_season_detail(html: str) -> dict[str, Any]:
    if not isinstance(html, str):
        raise ValueError("赛季详情必须是文本")
    boss = _BOSS.search(html)
    if boss is None:
        raise ValueError("公开赛季详情缺少首领卡")
    attrs: dict[str, str] = {}
    for attr in _ATTR.finditer(boss.group("body")):
        key = _clean(attr.group("key"))
        value = _clean(attr.group("value"))
        if key in {"屬性", "弱点", "弱點", "推薦"} and value:
            attrs[key] = value
    return {
        "name": boss.group("name").strip(),
        "element": attrs.get("屬性", ""),
        "weakness": attrs.get("弱點", attrs.get("弱点", "")),
        "recommended": attrs.get("推薦", ""),
    }


def _end_utc(meta: str, *, existing_ends_at: str = "") -> str:
    """只在能核对已有记录时保留截止时间；新赛季不擅自补年份。"""
    match = _DATES.search(meta)
    if match is None:
        raise ValueError("公开赛季日期格式不完整")
    end_month, end_day, end_hour, end_minute = (
        int(match.group(5)), int(match.group(6)), int(match.group(7)), int(match.group(8))
    )
    if not existing_ends_at:
        return ""
    try:
        existing = dt.datetime.fromisoformat(existing_ends_at).astimezone(dt.timezone(dt.timedelta(hours=9)))
    except ValueError:
        return ""
    if (
        existing.month == end_month
        and existing.day == end_day
        and existing.hour == end_hour
        and existing.minute == end_minute
    ):
        return existing.astimezone(dt.timezone.utc).isoformat()
    # 日期已变化：公开页只给月日，不能安全推断年份，保留未知。
    return ""


def build_season_payload(
    index_rows: list[dict[str, Any]],
    details: Mapping[str, Mapping[str, Any]],
    *,
    as_of: dt.date,
    checked_at: str,
    existing_seasons: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    del as_of  # 保留调用签名；不再用当前年份推算网页月日。
    existing_by_id = {
        str(item.get("id")): dict(item)
        for item in (existing_seasons or ())
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    }
    parsed_ids = set()
    seasons = []
    for row in index_rows:
        detail = details.get(row["id"])
        if detail is None:
            raise ValueError(f"缺少赛季 {row['id']} 的公开详情")
        boss_name = str(detail.get("name") or "").strip()
        weakness = str(detail.get("weakness") or "").strip()
        if not boss_name:
            raise ValueError(f"赛季 {row['id']} 缺少首领名")
        if not weakness:
            raise ValueError(f"赛季 {row['id']} 缺少公开弱点，保留旧文件")
        previous = existing_by_id.get(row["id"], {})
        ends = _end_utc(row["meta"], existing_ends_at=str(previous.get("ends_at") or ""))
        merged = dict(previous)
        merged.update({
            "id": row["id"],
            "name": f"赛季 {row['id']}",
            "source_url": row["source_url"],
            "checked_at": checked_at,
            "ends_at": ends,
            "note": "公开赛季页事实；结束状态按运行时日期判断。",
            "bosses": [{
                "id": f"solo-{row['id']}-{boss_name.lower().replace(' ', '-')}",
                "name": boss_name,
                "weakness": weakness,
                "element": str(detail.get("element") or "").strip(),
            }],
        })
        seasons.append(merged)
        parsed_ids.add(row["id"])
    # 未出现在本次公开索引中的旧赛季原样保留，不丢历史。
    for season_id, old in existing_by_id.items():
        if season_id not in parsed_ids:
            seasons.append(old)
    seasons.sort(key=lambda item: int(item["id"]))
    return {
        "schema_version": 1,
        "status": "PUBLIC_VERIFIED",
        "note": "按公开赛季页增量合并；未出现在本次索引的旧赛季保留；网页缺年份时保留已有截止时间或标为未知，不擅自补年份。",
        "seasons": seasons,
    }


def write_season_payload(path: str | Path, payload: Mapping[str, Any]) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return False
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
        handle.flush()
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


__all__ = [
    "build_season_payload",
    "parse_season_detail",
    "parse_season_index",
    "write_season_payload",
]
