"""合成引擎桩：仅用于验证子进程 JSON 合同，不是 nikke-calc 实现。"""

from __future__ import annotations

import json
import sys

COMMIT = "67835ca3033a95482749ea2db35a8ee2a0856a92"


def main() -> int:
    argv = sys.argv[1:]
    if "--request" not in argv:
        print(json.dumps({"schema_version": 2, "error": {"message": "missing request"}}))
        return 2
    request = json.loads(argv[argv.index("--request") + 1])
    squad = request.get("squad") or []
    if not squad or len(squad) > 5 or any(name == "FAIL" for name in squad):
        print(json.dumps({"schema_version": 2, "error": {"message": "synthetic invalid squad"}}))
        return 2
    total = sum(len(name) for name in squad) * 1000
    print(
        json.dumps(
            {
                "schema_version": 2,
                "total_damage": total,
                "members": [
                    {"name": name, "damage": len(name) * 1000, "share": 0.2}
                    for name in squad
                ],
                "evaluator": {"repo": "Jgaram/nikke-calc", "commit": COMMIT, "dirty": False},
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
