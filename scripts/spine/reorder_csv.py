
# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import csv
import json
import random
from pathlib import Path

import argparse


def main():
    parser = argparse.ArgumentParser(description="重排已生成盲审 CSV，仅处理指定输出目录")
    parser.add_argument("--evidence-dir", type=Path, default=_bootstrap_root / "output/face_guided_body_centering")
    args = parser.parse_args()
    evidence_dir = args.evidence_dir
    csv_path = evidence_dir / "pair_blind_review_package" / "pair_blind_review.csv"
    manifest_path = evidence_dir / "pair_blind_manifest.json"

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    def get_render_id(row):
        return manifest["samples"][row["review_id"]]["render_id"]

    # 按渲染标识分组
    groups = {}
    for r in rows:
        rid = get_render_id(r)
        if rid not in groups:
            groups[rid] = []
        groups[rid].append(r)

    # 轮流取样以增大同类样本间隔
    new_rows = []
    while any(groups.values()):
        # 每轮从各非空组取一项
        available = [rid for rid, lst in groups.items() if len(lst) > 0]
        # 每轮使用固定种子打乱组顺序
        random.seed("round_robin")
        random.shuffle(available)
        for rid in available:
            new_rows.append(groups[rid].pop(0))

    # 验证新的样本间隔
    min_gap = len(new_rows)
    for i in range(len(new_rows)):
        for j in range(i+1, len(new_rows)):
            if get_render_id(new_rows[i]) == get_render_id(new_rows[j]):
                gap = j - i - 1
                if gap < min_gap:
                    min_gap = gap
                break

    print(f"New minimum gap: {min_gap}")

    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=["review_id", "overall", "direction", "magnitude", "note"])
        writer.writeheader()
        writer.writerows(new_rows)

    # 更新输出审计记录
    audit_path = evidence_dir / "pair_blind_package_audit.json"
    with open(audit_path, 'r', encoding='utf-8') as f:
        audit = json.load(f)
    audit["minimum_same_render_gap"] = min_gap
    with open(audit_path, 'w', encoding='utf-8') as f:
        json.dump(audit, f, indent=2)



if __name__ == "__main__":
    main()
