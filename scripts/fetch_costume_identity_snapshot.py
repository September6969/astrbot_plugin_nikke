#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""维护期抓取 Canned Jar 明示的 Costume 名称与站立资产绑定。

输出仅包含公开元数据、页面哈希和资产 URL，不下载 Spine bundle，也不在产品
热路径运行。后续仍须与官方 Costume inventory、Nikke-db L2D index 交叉验证。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import urllib.request
from pathlib import Path


BASE_URL = "https://nikke.cannedjar.com"
POSTER_BASE = "https://nikke-res.cannedjar.com/assets/poster"
_CARD = re.compile(
    r'href="/nikke/([^"/]+)"[^>]*>.*?'
    r'<img src="https://nikke-res\.cannedjar\.com/assets/poster/mi_(c\d+)_00_s\.png"',
)
_SKIN = re.compile(
    r'<img src="https://nikke-res\.cannedjar\.com/assets/poster/mi_(c\d+_\d+)_s\.png" alt="([^"]+)"'
)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "astrbot-plugin-nikke-maintenance/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def build_snapshot(inventory: dict, *, workers: int = 6) -> dict:
    costumes = inventory.get("costumes")
    if not isinstance(costumes, list) or len(costumes) != 178:
        raise ValueError("official inventory 必须固定为 178 条")
    list_bytes = _fetch(f"{BASE_URL}/nikke")
    list_html = list_bytes.decode("utf-8")
    slug_by_owner = {match.group(2): match.group(1) for match in _CARD.finditer(list_html)}
    owners = sorted({f"c{int(row['character_resource_id']):03d}" for row in costumes})

    def fetch_owner(owner: str) -> dict:
        slug = slug_by_owner.get(owner)
        if not slug:
            raise ValueError(f"Canned Jar 缺少 owner 页面: {owner}")
        url = f"{BASE_URL}/nikke/{slug}/skins/0"
        body = _fetch(url)
        found: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in _SKIN.finditer(body.decode("utf-8")):
            asset_id = match.group(1)
            if asset_id in seen or asset_id.endswith("_00"):
                continue
            seen.add(asset_id)
            found.append({
                "asset_id": asset_id,
                "costume_name": html.unescape(match.group(2)),
                "standing_asset_url": f"{POSTER_BASE}/mi_{asset_id}_s.png",
            })
        return {
            "character_resource_id": str(int(owner[1:])),
            "owner_asset_id": owner,
            "slug": slug,
            "source_url": url,
            "source_sha256": hashlib.sha256(body).hexdigest(),
            "alternate_assets": found,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        owner_rows = list(executor.map(fetch_owner, owners))
    alternate_total = sum(len(row["alternate_assets"]) for row in owner_rows)
    return {
        "schema_version": 1,
        "source": BASE_URL,
        "source_role": "public identity cross-reference; not the authoritative official Costume universe",
        "list_source_sha256": hashlib.sha256(list_bytes).hexdigest(),
        "official_owner_total": len(owners),
        "alternate_asset_total": alternate_total,
        "owners": owner_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取公开 Costume identity 快照")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    snapshot = build_snapshot(inventory, workers=args.workers)
    if snapshot["alternate_asset_total"] != 178:
        raise ValueError(f"公开目录 alternate 数量漂移: {snapshot['alternate_asset_total']} != 178")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in snapshot.items() if key != "owners"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
