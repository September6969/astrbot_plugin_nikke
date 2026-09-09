# SPDX-License-Identifier: GPL-3.0-or-later
"""从脱敏 CharacterDetails JSON 输出字段结构诊断，不输出原始账号值。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from character_detail_diagnostic import summarize_character_details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="脱敏 CharacterDetails JSON 文件")
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and isinstance(payload.get("character_details"), list):
        summary = {
            "schema_version": 1,
            "character_details": [
                summarize_character_details(item)
                for item in payload["character_details"]
                if isinstance(item, dict)
            ],
        }
    else:
        detail = payload.get("detail", payload.get("character_detail", payload))
        summary = summarize_character_details(detail)
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
