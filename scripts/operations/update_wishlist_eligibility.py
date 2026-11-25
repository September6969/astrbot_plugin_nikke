# SPDX-License-Identifier: GPL-3.0-or-later
"""愿望单准入表可持续核验与增量更新脚本。

数据来源：
- 本地 `assets/data/character_master.json`（全量角色主表）
- 开源 MIT 仓库 `leegunwoooo/nikke-calculator`：
  `site/public/pickup-history.json` 与 `data/name_codes.json`

规则（保守 fail-closed）：
1. 已在 `wishlist_pool_eligibility.json` 核验为 `limited` / `collab` / `free_welfare` / `ordinary_recruit` / `pilgrim_overspec` 的条目默认保留；
2. 对尚未知或新增 SSR，结合 `pickup-history.json` 招募类别（是否 limited / collab / 超标准 tags=['오버스펙'] / PILGRIM）与角色元数据自动判定；
3. 无法确认（如无招募记录的全新未知卡）仍保守标为 `unknown` 并拒绝入池，不擅自放行。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
PICKUP_URL = "https://raw.githubusercontent.com/leegunwoooo/nikke-calculator/HEAD/site/public/pickup-history.json"
NAME_CODES_URL = "https://raw.githubusercontent.com/leegunwoooo/nikke-calculator/HEAD/data/name_codes.json"


def _fetch_json(url_or_path: str) -> Any:
    path = Path(url_or_path)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url_or_path, headers={"User-Agent": "astrbot-plugin-nikke-updater"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reconcile_wishlist(
    master_rows: list[Mapping[str, Any]],
    existing_payload: Mapping[str, Any],
    pickup_payload: Mapping[str, Any],
    name_codes: Mapping[str, str],
    *,
    checked_at: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """对比角色主表与公开招募历史，返回更新后 payload 与变更日志。"""
    entries: dict[str, dict[str, Any]] = {
        str(k): dict(v)
        for k, v in (existing_payload.get("entries") or {}).items()
        if isinstance(v, Mapping)
    }
    by_kr: dict[str, list[Mapping[str, Any]]] = {}
    for ev in pickup_payload.get("events", ()) or ():
        if not isinstance(ev, Mapping):
            continue
        for name in ev.get("names", ()) or ():
            by_kr.setdefault(str(name), []).append(ev)

    changes: list[str] = []
    for row in master_rows:
        if not isinstance(row, Mapping) or str(row.get("rare") or "").upper() != "SSR":
            continue
        code = str(row.get("name_code") or "").strip()
        if not code:
            continue
        cn_name = str(row.get("name_zh_cn") or row.get("name_zh_tw") or row.get("name_en") or code)
        corp = str(row.get("corporation") or "").upper()
        cur = entries.get(code)
        if cur and cur.get("pool_status") not in (None, "", "unknown"):
            continue

        if corp == "ABNORMAL":
            entries[code] = {
                "pool_status": "collab",
                "wishlist_group": "NONE",
                "note": f"{cn_name}（ABNORMAL 联动不入普池）",
            }
            changes.append(f"+ {code} {cn_name}: collab")
            continue

        kr_name = str(name_codes.get(code) or "").strip()
        events = by_kr.get(kr_name, []) if kr_name else []
        new_entry = _classify_from_events(cn_name, corp, events)
        entries[code] = new_entry
        changes.append(f"~ {code} {cn_name}: {new_entry['pool_status']}")

    updated = {
        "schema_version": 1,
        "checked_at": checked_at or dt.date.today().isoformat(),
        "source_note": existing_payload.get(
            "source_note",
            "基于《胜利女神：NIKKE》普通招募愿望单规则与 MIT nikke-calculator 招募历史交叉核验（fail-closed）。",
        ),
        "entries": dict(sorted(entries.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0])),
    }
    return updated, changes


def _classify_from_events(cn_name: str, corp: str, events: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "pool_status": "unknown",
            "wishlist_group": "NONE",
            "note": f"{cn_name}（尚无公开招募历史核验记录，保守 fail-closed 排除）",
        }
    if any(bool(ev.get("collab")) for ev in events):
        return {"pool_status": "collab", "wishlist_group": "NONE", "note": f"{cn_name}（联动角色不入普池）"}
    if any(bool(ev.get("limited")) for ev in events):
        return {"pool_status": "limited", "wishlist_group": "NONE", "note": f"{cn_name}（期间限定不入普池）"}
    is_overspec = any("오버스펙" in (ev.get("tags") or ()) for ev in events)
    if corp == "PILGRIM" or is_overspec:
        return {
            "pool_status": "pilgrim_overspec",
            "wishlist_group": "PILGRIM",
            "note": f"{cn_name}（朝圣者 / 超标准独立 5 席）",
        }
    if corp in {"ELYSION", "MISSILIS", "TETRA"}:
        return {
            "pool_status": "ordinary_recruit",
            "wishlist_group": corp,
            "note": f"{cn_name}（常规企业普通招募池）",
        }
    return {
        "pool_status": "unknown",
        "wishlist_group": "NONE",
        "note": f"{cn_name}（未知企业归属，保守排除）",
    }


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        tmp = Path(handle.name)
        handle.write(text)
        handle.flush()
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="更新普通招募愿望单准入表")
    parser.add_argument("--pickup", default=PICKUP_URL, help="pickup-history.json 路径或 URL")
    parser.add_argument("--name-codes", default=NAME_CODES_URL, help="name_codes.json 路径或 URL")
    parser.add_argument(
        "--target",
        default=str(ROOT / "assets" / "data" / "wishlist_pool_eligibility.json"),
        help="输出 wishlist_pool_eligibility.json 路径",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅检查差异，不写盘")
    args = parser.parse_args(argv)

    master = json.loads((ROOT / "assets" / "data" / "character_master.json").read_text(encoding="utf-8"))["characters"]
    target = Path(args.target)
    existing = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {"entries": {}}
    pickup = _fetch_json(args.pickup)
    name_codes = _fetch_json(args.name_codes)
    updated, changes = reconcile_wishlist(master, existing, pickup, name_codes)
    for line in changes:
        print(line)
    print(f"Total entries: {len(updated['entries'])}, updates: {len(changes)}")
    if not args.dry_run and (changes or not target.is_file()):
        _write_atomic(target, updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
