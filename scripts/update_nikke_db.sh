#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# 仅供维护期人工执行：更新本地 Nikke-db sparse checkout 并批量预渲染。

set -euo pipefail

PLUGIN_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
DATA_ROOT=${NIKKE_DATA_ROOT:-/AstrBot/data}
DB_ROOT=${NIKKE_DB_ROOT:-"$DATA_ROOT/vendor/nikke-db"}
OUTPUT_ROOT=${NIKKE_SPINE_OUTPUT_ROOT:-"$DATA_ROOT/nikke/spine-rendered"}
MANIFEST_PATH=${NIKKE_SPINE_MANIFEST_PATH:-"$DATA_ROOT/nikke/spine-manifest.json"}
COVERAGE_PATH=${NIKKE_SPINE_COVERAGE_PATH:-"$DATA_ROOT/nikke/spine-coverage.json"}
SOURCE_REPO=https://github.com/Nikke-db/Nikke-db.github.io.git

echo "[维护] 磁盘预检查"
df -h "$DATA_ROOT"
du -sh "$DATA_ROOT" 2>/dev/null || true

if [[ ! -d "$DB_ROOT/.git" ]]; then
  mkdir -p "$(dirname -- "$DB_ROOT")"
  git clone --depth 1 --filter=blob:none --no-checkout "$SOURCE_REPO" "$DB_ROOT"
fi

if [[ -n "$(git -C "$DB_ROOT" status --porcelain)" ]]; then
  echo "Nikke-db checkout 存在未提交改动，停止以保护本地维护状态" >&2
  exit 2
fi

git -C "$DB_ROOT" fetch --depth 1 origin main
git -C "$DB_ROOT" sparse-checkout init --no-cone 2>/dev/null || true

mapfile -t ASSET_IDS < <(python3 - "$PLUGIN_ROOT" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
pattern = re.compile(r"^c[0-9]+(?:_[0-9]+)?$", re.ASCII)
seen = set()

def add(value):
    if not isinstance(value, str):
        return
    value = value.strip().lower()
    if pattern.fullmatch(value) and value not in seen:
        seen.add(value)
        print(value)

master = json.loads((root / "assets" / "character_master.json").read_text(encoding="utf-8"))
for row in master.get("characters", []):
    if isinstance(row, dict):
        add(row.get("spine_asset_id"))
costumes = json.loads((root / "assets" / "costumes.json").read_text(encoding="utf-8"))
for row in costumes.get("entries", []):
    if isinstance(row, dict):
        if all(isinstance(row.get(key), str) and row[key].strip() for key in ("source", "source_sha256", "verified_at")):
            add(row.get("spine_asset_id"))
PY
)

if [[ "${#ASSET_IDS[@]}" -eq 0 ]]; then
  echo "没有从 verified registry 解析到 Spine 目标" >&2
  exit 2
fi

SPARSE_PATTERNS=()
for asset_id in "${ASSET_IDS[@]}"; do
  SPARSE_PATTERNS+=("/l2d/$asset_id/*.skel" "/l2d/$asset_id/*.atlas" "/l2d/$asset_id/*.png" "/l2d/$asset_id/*.webp")
done
git -C "$DB_ROOT" sparse-checkout set --no-cone "${SPARSE_PATTERNS[@]}"
git -C "$DB_ROOT" checkout --detach FETCH_HEAD

echo "[维护] sparse checkout 大小"
du -sh "$DB_ROOT"

python3 "$PLUGIN_ROOT/scripts/sync_spine_assets.py" \
  --all \
  --nikke-db-root "$DB_ROOT" \
  --out-dir "$OUTPUT_ROOT" \
  --manifest-path "$MANIFEST_PATH" \
  --coverage-report "$COVERAGE_PATH"

echo "[维护] 预渲染目录大小"
du -sh "$OUTPUT_ROOT" 2>/dev/null || true
df -h "$DATA_ROOT"
