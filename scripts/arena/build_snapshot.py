"""将锁定的 MIT Planner 快照转换为插件规范角色键。"""

import argparse
import hashlib
import json
import re
from pathlib import Path

PLANNER_COMMIT = "c7948fb4b8778efde16320768a2159eb500e4216"
BURSTS = {"I": 1, "II": 2, "III": 3, "Λ": 0}
TIERS = {"2RL": 2, "5SG": 2.5, "3RL": 3, "7SG": 3.5, "4RL": 4, "5RL": 5}


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def build(source_dir: Path, root: Path):
    master = json.loads((root / "assets/data/character_master.json").read_text(encoding="utf-8"))["characters"]
    by_resource = {int(row["resource_id"]): row for row in master}
    by_english = {}
    for row in master:
        by_english.setdefault(normalized(row["name_en"]), []).append(row)
    characters = json.loads((source_dir / "planner-characters.json").read_text(encoding="utf-8"))
    templates = json.loads((source_dir / "planner-templates.json").read_text(encoding="utf-8"))
    mapping, variants, parameters, names, missing, methods = {}, [], {}, {}, [], {}
    for char in characters:
        resource = re.search(r"si_c(\d+)_", char.get("avatarImg", ""))
        base = by_resource.get(int(resource.group(1))) if resource else None
        method = "resource_id"
        if base is None:
            english = char["name"]["en"].removesuffix(": Treasure")
            matches = by_english.get(normalized(english), ())
            if len(matches) == 1:
                base = matches[0]
                method = "exact_english_name"
        if base is None:
            missing.append(char["id"])
            continue
        key = base["character_key"]
        if char["id"].endswith("-treasure"):
            key += "_treasure"
            variants.append({"key": key, "base_key": base["character_key"],
                             "name": base["name_cn"] + " 珍藏",
                             "name_code": str(base["name_code"]), "burst": BURSTS[char["burst"]]})
        if key in names:
            raise ValueError("多个第三方角色映射到同一规范角色，请人工核对。")
        mapping[char["id"]] = key
        methods[char["id"]] = method
        names[key] = char["name"]
        curve = char.get("burstGen", {}).get("attack", {})
        parameters[key] = {str(tier): round(curve[label] * 100, 6)
                           for label, tier in TIERS.items() if label in curve}
    converted = []
    for template in templates:
        flexible = {item["slot"]: item["options"] for item in template["flex"]}
        required = iter(template["required"])
        slots = []
        for index in range(5):
            options = flexible.get(index)
            if options is None:
                options = [next(required)]
            slots.append([mapping[key] for key in options if key in mapping])
        if all(slots):
            converted.append({
                "id": template["id"], "archetype": template["archetype"],
                "required": [mapping[key] for key in template["required"]],
                "slots": slots, "reason": template["name"]["zh-CN"] + "（参考模板，效果待实战确认）",
                "priority": {1: 30, 2: 20, 3: 10}.get(template["priority"], 0),
                "counters": template["counters"], "countered_by": template["counteredBy"],
            })
    return {
        "schema_version": 1, "source": "https://github.com/williamchong/nikke-arena-planner",
        "commit": PLANNER_COMMIT, "fetched_at": "2026-11-17", "license": "MIT",
        "confidence": "reference", "missing_fields": ["cubes", "overload", "skill_levels", "reentry_timing"],
        "source_hashes": {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
                          for name in ("planner-characters.json", "planner-templates.json")},
        "mapping": mapping, "mapping_method": methods, "unmapped": missing, "variants": variants,
        "names": names, "parameters": parameters, "templates": converted,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True,
                        help="包含 planner-characters.json、planner-templates.json 的锁定快照目录")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = build(args.source_dir, root)
    destination = root / "assets/data/arena/rules.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已映射 {len(result['mapping'])} 个身份，保留 {len(result['templates'])} 组模板。")
