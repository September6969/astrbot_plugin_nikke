"""从已下载的官网静态表提取关卡映射；不推导 ID，不访问账号。"""
import argparse
import json
import re
from pathlib import Path


def build_mapping(rows):
    if not isinstance(rows, list):
        raise ValueError("关卡表必须为数组")
    result = {"NORMAL": {}, "HARD": {}}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("关卡记录格式错误")
        mode = {"Normal": "NORMAL", "Hard": "HARD"}.get(row.get("chapter_mod"))
        if mode is None:
            continue
        label = row.get("name_localkey", {})
        name = label.get("name", "") if isinstance(label, dict) else ""
        match = re.fullmatch(r"(\d+-\d+(?:[A-Z]-\d+)?) (?:HARD )?(?:STAGE|BOSS)", name)
        if not match:
            continue
        name = match[1]
        identifier = row.get("id")
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("关卡 ID 无效")
        # chapter_id 是内部章节键，显示章节必须从明确标签读取。
        chapter = result[mode].setdefault(name.split("-", 1)[0], {})
        if name in chapter and chapter[name] != identifier:
            raise ValueError("同名关卡 ID 冲突")
        chapter[name] = identifier
    if not all(result.values()):
        raise ValueError("缺少普通或困难模式")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build_mapping(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
