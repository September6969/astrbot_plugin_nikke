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
NIKKE_MIN_FREE_GB=${NIKKE_MIN_FREE_GB:-5}

if ! [[ "$NIKKE_MIN_FREE_GB" =~ ^[0-9]+$ ]] || (( NIKKE_MIN_FREE_GB < 1 )); then
  echo "NIKKE_MIN_FREE_GB 必须是大于等于 1 的整数" >&2
  exit 2
fi
MIN_FREE_BYTES=$((NIKKE_MIN_FREE_GB * 1024 * 1024 * 1024))

path_size_bytes() {
  local path=$1
  if [[ -e "$path" ]]; then
    du -sk -- "$path" 2>/dev/null | awk 'NR == 1 { print $1 * 1024 }'
  else
    echo 0
  fi
}

free_bytes() {
  df -Pk -- "$DATA_ROOT" | awk 'NR == 2 { print $4 * 1024 }'
}

check_disk_capacity() {
  local phase=$1
  local current_free vendor_size render_size
  current_free=$(free_bytes)
  vendor_size=$(path_size_bytes "$DB_ROOT")
  render_size=$(path_size_bytes "$OUTPUT_ROOT")
  if ! [[ "$current_free" =~ ^[0-9]+$ && "$vendor_size" =~ ^[0-9]+$ && "$render_size" =~ ^[0-9]+$ ]]; then
    echo "无法读取磁盘容量或目录大小，停止维护操作 phase=$phase" >&2
    exit 2
  fi
  if (( current_free < MIN_FREE_BYTES )); then
    echo "BLOCKED_BY_DISK_CAPACITY phase=$phase required_safety_threshold_gb=$NIKKE_MIN_FREE_GB current_free_bytes=$current_free current_vendor_size_bytes=$vendor_size render_size_bytes=$render_size" >&2
    exit 3
  fi
}

echo "[维护] 磁盘预检查"
df -h "$DATA_ROOT"
du -sh "$DATA_ROOT" 2>/dev/null || true
check_disk_capacity "before-clone"

if [[ ! -d "$DB_ROOT/.git" ]]; then
  mkdir -p "$(dirname -- "$DB_ROOT")"
  git clone --depth 1 --filter=blob:none --no-checkout "$SOURCE_REPO" "$DB_ROOT"
fi

if [[ -n "$(git -C "$DB_ROOT" status --porcelain)" ]]; then
  echo "Nikke-db checkout 存在未提交改动，停止以保护本地维护状态" >&2
  exit 2
fi

check_disk_capacity "before-fetch"
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
  # 第一阶段只取 skeleton 与 atlas；纹理页由 atlas 的实际声明决定。
  SPARSE_PATTERNS+=(
    "/l2d/$asset_id/*.skel" "/l2d/$asset_id/**/*.skel"
    "/l2d/$asset_id/*.atlas" "/l2d/$asset_id/**/*.atlas"
  )
done
check_disk_capacity "before-sparse-phase-a"
git -C "$DB_ROOT" sparse-checkout set --no-cone "${SPARSE_PATTERNS[@]}"
git -C "$DB_ROOT" checkout --detach FETCH_HEAD

TEXTURE_PATTERN_FILE=$(mktemp)
cleanup_texture_pattern_file() {
  rm -f -- "$TEXTURE_PATTERN_FILE"
}
trap cleanup_texture_pattern_file EXIT
if ! python3 - "$DB_ROOT" "${ASSET_IDS[@]}" > "$TEXTURE_PATTERN_FILE" <<'PY'
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
asset_ids = sys.argv[2:]
page_suffixes = {".png", ".webp"}
patterns = set()

def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)

for asset_id in asset_ids:
    if not re.fullmatch(r"c[0-9]+(?:_[0-9]+)?", asset_id, re.ASCII):
        fail(f"非法 Spine asset ID: {asset_id}")
    asset_root = (root / "l2d" / asset_id).resolve()
    if not asset_root.is_relative_to(root):
        fail(f"Spine asset 根目录越界: {asset_id}")
    atlas_paths = sorted(asset_root.rglob("*.atlas"))
    for atlas_path in atlas_paths:
        try:
            text = atlas_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            fail(f"atlas 无法按 UTF-8-SIG 读取: {atlas_path}: {exc}")
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [line.strip().lstrip("\ufeff") for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            page = lines[0]
            if Path(page).suffix.lower() not in page_suffixes:
                continue
            if (
                not page
                or "\\" in page
                or posixpath.isabs(page)
                or re.match(r"^[A-Za-z]:", page)
            ):
                fail(f"atlas 纹理页路径非法: {page}")
            parts = PurePosixPath(page).parts
            if any(part in {"", ".", ".."} for part in parts):
                fail(f"atlas 纹理页路径越界: {page}")
            target = (atlas_path.parent / Path(*parts)).resolve()
            if not target.is_relative_to(asset_root):
                fail(f"atlas 纹理页路径越界: {page}")
            relative = target.relative_to(root).as_posix()
            patterns.add("/" + relative)

if not patterns:
    fail("atlas 未声明可用纹理页")
for pattern in sorted(patterns):
    print(pattern)
PY
then
  echo "atlas 纹理页解析失败，停止维护操作" >&2
  exit 2
fi
mapfile -t TEXTURE_PATTERNS < "$TEXTURE_PATTERN_FILE"
rm -f -- "$TEXTURE_PATTERN_FILE"
trap - EXIT

check_disk_capacity "before-sparse-phase-b"
git -C "$DB_ROOT" sparse-checkout add "${TEXTURE_PATTERNS[@]}"

echo "[维护] sparse checkout 大小"
du -sh "$DB_ROOT"

check_disk_capacity "before-render"
python3 "$PLUGIN_ROOT/scripts/sync_spine_assets.py" \
  --all \
  --nikke-db-root "$DB_ROOT" \
  --out-dir "$OUTPUT_ROOT" \
  --manifest-path "$MANIFEST_PATH" \
  --coverage-report "$COVERAGE_PATH"

echo "[维护] 预渲染目录大小"
du -sh "$OUTPUT_ROOT" 2>/dev/null || true
check_disk_capacity "after-render"
df -h "$DATA_ROOT"
