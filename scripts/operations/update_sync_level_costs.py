# SPDX-License-Identifier: GPL-3.0-or-later
"""从 NikkeHub 公开同步器页面重新生成逐级成本表。

用法::

    python scripts/operations/update_sync_level_costs.py --output assets/data/sync-level-costs.json

失败时不写文件，保留上一批；成功写入是原子的。只读取公开前端表。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

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

from astrbot_plugin_nikke.features.sync.public_source import (  # noqa: E402
    build_sync_payload,
    parse_sync_ranges,
    write_sync_payload,
)

PAGE = "https://nikkehub.com/zh-tw/tools/sync-level"


def fetch_ranges() -> list[dict[str, int]]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        page = client.get(PAGE)
        page.raise_for_status()
        scripts = sorted(set(re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', page.text)))
        for src in scripts:
            time.sleep(0.2)
            response = client.get(src if src.startswith("http") else "https://nikkehub.com" + src)
            if response.status_code != 200:
                continue
            try:
                return parse_sync_ranges(response.text)
            except ValueError:
                continue
    raise SystemExit("未在公开页面找到同步器成本表；保留原文件")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "data" / "sync-level-costs.json")
    parser.add_argument("--checked-at", default=dt.date.today().isoformat())
    args = parser.parse_args()
    rows = fetch_ranges()
    payload = build_sync_payload(rows, checked_at=args.checked_at)
    changed = write_sync_payload(args.output, payload)
    print(f"{'更新' if changed else '无变化'}：{args.output}（{len(payload['levels'])} 级）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
