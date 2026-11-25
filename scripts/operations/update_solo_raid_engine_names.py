# SPDX-License-Identifier: GPL-3.0-or-later
"""按共同稳定 ID 生成 nikke-calc 角色名映射。

只使用引擎 `scraper/nikke_scraped.json` 的 `id` 与本仓 `character_master.json`
的 `resource_id`/`name_code` 交集；英文/中文别名仅在唯一时加入，不做译名模糊匹配。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = ROOT / "output" / "nikke-calc"
PINNED = "67835ca3033a95482749ea2db35a8ee2a0856a92"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--master", type=Path, default=ROOT / "assets" / "data" / "character_master.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "data" / "solo_raid_engine_names.json")
    args = parser.parse_args()
    scraped_path = args.engine / "scraper" / "nikke_scraped.json"
    if not scraped_path.is_file():
        raise SystemExit(f"缺少引擎抓取数据：{scraped_path}")
    engine = json.loads(scraped_path.read_text(encoding="utf-8"))
    master = json.loads(args.master.read_text(encoding="utf-8"))["characters"]
    by_resource = {int(row["resource_id"]): row for row in master}
    names: dict[str, str] = {}
    collisions: list[tuple[str, str, str]] = []
    mapped = 0

    def add(key, value: str) -> None:
        text = str(key or "").strip()
        if not text:
            return
        old = names.get(text)
        if old is not None and old != value:
            collisions.append((text, old, value))
            return
        names[text] = value

    for official, row in sorted(engine.items()):
        resource_id = row.get("id")
        master_row = by_resource.get(resource_id) if isinstance(resource_id, int) else None
        if not master_row:
            continue
        mapped += 1
        add(resource_id, official)
        add(master_row["name_code"], official)
        for field in ("name_cn", "name_zh_tw", "name_en"):
            add(master_row.get(field), official)

    payload = {
        "schema_version": 1,
        "engine_repo": "Jgaram/nikke-calc",
        "engine_commit": PINNED,
        "source_url": f"https://github.com/Jgaram/nikke-calc/tree/{PINNED}",
        "checked_at": __import__("datetime").date.today().isoformat(),
        "names": names,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output.is_file() and args.output.read_text(encoding="utf-8") == text:
        print("无变化")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"写入 {args.output}：{mapped} 名角色，{len(names)} 个键，跳过冲突 {len(collisions)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
