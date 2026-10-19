# SPDX-License-Identifier: GPL-3.0-or-later
"""从脱敏 CharacterDetails JSON 输出字段结构诊断，不输出原始账号值。"""

from __future__ import annotations

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))


import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astrbot_plugin_nikke.features.character.diagnostic import summarize_character_details


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
