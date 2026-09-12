#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# 维护期小批量拉取候选 bundle 并渲染；临时 checkout 不进入产品热路径。

set -euo pipefail

if (( $# == 0 )); then
  echo "用法: $0 c010_01 [c010_02 ...]" >&2
  exit 2
fi

DATA_ROOT=${NIKKE_DATA_ROOT:-/AstrBot/data}
OUTPUT_ROOT=${NIKKE_SPINE_OUTPUT_ROOT:-"$DATA_ROOT/nikke/spine-rendered"}
MANIFEST_PATH=${NIKKE_SPINE_MANIFEST_PATH:-"$DATA_ROOT/nikke/spine-manifest.json"}
PLUGIN_ROOT=${NIKKE_PLUGIN_ROOT:-"$DATA_ROOT/plugins/astrbot_plugin_nikke"}
SOURCE_REPO=https://github.com/Nikke-db/Nikke-db.github.io.git
SOURCE_COMMIT=${NIKKE_DB_COMMIT:-a2358b72bd1335c30737e46482a99947f3788bc7}
NIKKE_MIN_FREE_GB=${NIKKE_MIN_FREE_GB:-5}

python3 - "$@" <<'PY'
import re
import sys

for value in sys.argv[1:]:
    if not re.fullmatch(r"c[0-9]+_[0-9]+", value, re.ASCII):
        raise SystemExit(f"非法 alternate Spine asset ID: {value}")
PY

check_disk() {
  local phase=$1
  python3 - "$DATA_ROOT" "$NIKKE_MIN_FREE_GB" "$phase" <<'PY'
import shutil
import sys

root, minimum, phase = sys.argv[1], int(sys.argv[2]), sys.argv[3]
free = shutil.disk_usage(root).free
required = minimum * 1024**3
if free < required:
    raise SystemExit(
        f"BLOCKED_BY_DISK_CAPACITY phase={phase} required_bytes={required} free_bytes={free}"
    )
print(f"disk_guard phase={phase} free_bytes={free}")
PY
}

check_disk before_clone
mkdir -p "$DATA_ROOT/vendor"
BATCH_ROOT=$(mktemp -d "$DATA_ROOT/vendor/.costume-batch.XXXXXX")
cleanup() {
  case "$BATCH_ROOT" in
    "$DATA_ROOT"/vendor/.costume-batch.*) rm -rf -- "$BATCH_ROOT" ;;
    *) echo "拒绝清理未验证的临时路径: $BATCH_ROOT" >&2 ;;
  esac
}
trap cleanup EXIT

git clone --filter=blob:none --no-checkout --single-branch "$SOURCE_REPO" "$BATCH_ROOT"
git -C "$BATCH_ROOT" sparse-checkout init --no-cone

PHASE_A=()
for asset_id in "$@"; do
  PHASE_A+=("/l2d/$asset_id/*.skel" "/l2d/$asset_id/**/*.skel")
  PHASE_A+=("/l2d/$asset_id/*.atlas" "/l2d/$asset_id/**/*.atlas")
done
git -C "$BATCH_ROOT" sparse-checkout set --no-cone "${PHASE_A[@]}"
git -C "$BATCH_ROOT" checkout --detach "$SOURCE_COMMIT"
check_disk after_bundle_metadata

TEXTURE_FILE=$(mktemp "$DATA_ROOT/vendor/.costume-textures.XXXXXX")
python3 - "$BATCH_ROOT" "$@" > "$TEXTURE_FILE" <<'PY'
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
patterns = set()
for asset_id in sys.argv[2:]:
    asset_root = (root / "l2d" / asset_id).resolve()
    for atlas in asset_root.rglob("*.atlas"):
        text = atlas.read_text(encoding="utf-8-sig")
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [line.strip().lstrip("\ufeff") for line in block.splitlines() if line.strip()]
            if not lines or Path(lines[0]).suffix.lower() not in {".png", ".webp"}:
                continue
            page = lines[0]
            if "\\" in page or posixpath.isabs(page) or re.match(r"^[A-Za-z]:", page):
                raise SystemExit(f"atlas 纹理页路径非法: {page}")
            parts = PurePosixPath(page).parts
            if any(part in {"", ".", ".."} for part in parts):
                raise SystemExit(f"atlas 纹理页路径越界: {page}")
            target = (atlas.parent / Path(*parts)).resolve()
            if not target.is_relative_to(asset_root):
                raise SystemExit(f"atlas 纹理页路径越界: {page}")
            patterns.add("/" + target.relative_to(root).as_posix())
if not patterns:
    raise SystemExit("atlas 未声明可用纹理页")
print("\n".join(sorted(patterns)))
PY
mapfile -t TEXTURES < "$TEXTURE_FILE"
rm -f -- "$TEXTURE_FILE"
git -C "$BATCH_ROOT" sparse-checkout add "${TEXTURES[@]}"
check_disk before_render

python3 "$PLUGIN_ROOT/scripts/sync_spine_assets.py" \
  --assets "$@" \
  --nikke-db-root "$BATCH_ROOT" \
  --out-dir "$OUTPUT_ROOT" \
  --manifest-path "$MANIFEST_PATH"

check_disk after_render
