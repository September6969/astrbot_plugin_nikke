# SPDX-License-Identifier: GPL-3.0-or-later
"""从公开 NikkeHub 单人突袭页面重新生成赛季事实索引。

失败时不写文件，保留上一批；成功写入原子且可幂等重跑。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# 工作树目录名不一定是包名；脚本始终装载当前仓库，避免误用相邻工作树。
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "astrbot_plugin_nikke", ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
_module = importlib.util.module_from_spec(_spec)
sys.modules["astrbot_plugin_nikke"] = _module
_spec.loader.exec_module(_module)

from astrbot_plugin_nikke.features.solo_raid.public_source import (  # noqa: E402
    build_season_payload,
    parse_season_detail,
    parse_season_index,
    write_season_payload,
)

INDEX = "https://nikkehub.com/zh-tw/raids/solo"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "data" / "solo_raid_seasons.json")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--checked-at", default=dt.date.today().isoformat())
    args = parser.parse_args()
    with httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        page = client.get(INDEX)
        page.raise_for_status()
        index_rows = parse_season_index(page.text)[: args.limit]
        details = {}
        for row in index_rows:
            time.sleep(0.4)
            response = client.get(row["source_url"])
            response.raise_for_status()
            details[row["id"]] = parse_season_detail(response.text)
    existing = None
    if args.output.is_file():
        try:
            existing_payload = json.loads(args.output.read_text(encoding="utf-8"))
            existing = existing_payload.get("seasons") if isinstance(existing_payload, dict) else None
        except (OSError, ValueError):
            existing = None
    payload = build_season_payload(
        index_rows, details, as_of=dt.date.today(), checked_at=args.checked_at,
        existing_seasons=existing,
    )
    changed = write_season_payload(args.output, payload)
    print(f"{'更新' if changed else '无变化'}：{args.output}（{len(payload['seasons'])} 期）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
