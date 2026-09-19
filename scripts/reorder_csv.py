import csv
import json
import random
from pathlib import Path

evidence_dir = Path(r"d:\download\Compressed\nikke_docs\astrbot_plugin_nikke\docs\evidence\face_guided_body_centering")
csv_path = evidence_dir / "pair_blind_review_package" / "pair_blind_review.csv"
manifest_path = evidence_dir / "pair_blind_manifest.json"

with open(manifest_path, 'r', encoding='utf-8') as f:
    manifest = json.load(f)

with open(csv_path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

def get_render_id(row):
    return manifest["samples"][row["review_id"]]["render_id"]

# Group by render_id
groups = {}
for r in rows:
    rid = get_render_id(r)
    if rid not in groups:
        groups[rid] = []
    groups[rid].append(r)

# Flatten by round-robin to maximize gap
new_rows = []
while any(groups.values()):
    # Get one from each available group
    available = [rid for rid, lst in groups.items() if len(lst) > 0]
    # Shuffle the available order each round
    random.seed("round_robin")
    random.shuffle(available)
    for rid in available:
        new_rows.append(groups[rid].pop(0))

# Verify new gap
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

# Update audit
audit_path = evidence_dir / "pair_blind_package_audit.json"
with open(audit_path, 'r', encoding='utf-8') as f:
    audit = json.load(f)
audit["minimum_same_render_gap"] = min_gap
with open(audit_path, 'w', encoding='utf-8') as f:
    json.dump(audit, f, indent=2)

