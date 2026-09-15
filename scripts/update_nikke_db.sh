#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Nikke-db 本地仓库更新与全量 Spine 离线预渲染流水线

set -euo pipefail

NIKKE_DB_ROOT="${NIKKE_DB_ROOT:-/opt/nikke-bot/vendor/nikke-db}"
OUT_DIR="${OUT_DIR:-/opt/nikke-bot/astrbot/data/nikke/spine-rendered}"
MANIFEST_PATH="${MANIFEST_PATH:-/opt/nikke-bot/astrbot/data/nikke/spine-manifest.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "=================================================="
echo "Nikke-db 维护与离线预渲染流水线"
echo "时间: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=================================================="

# 1. 安全更新本地 Nikke-db 检出
if [ -d "$NIKKE_DB_ROOT/.git" ]; then
    echo "[1/3] 更新本地 Nikke-db 仓库 ($NIKKE_DB_ROOT)..."
    cd "$NIKKE_DB_ROOT"
    git fetch --depth 1 origin main
    git reset --hard origin/main
    echo "最新 commit: $(git rev-parse HEAD)"
else
    echo "提示: $NIKKE_DB_ROOT 未初始化为 git 仓库，跳过 git pull。"
fi

# 2. 启动批量离线预渲染
echo "[2/3] 启动 Spine 全量离线预渲染流水线..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$PYTHON_BIN" "$SCRIPT_DIR/sync_spine_assets.py" \
    --all \
    --nikke-db-root "$NIKKE_DB_ROOT" \
    --out-dir "$OUT_DIR" \
    --manifest "$MANIFEST_PATH"

# 3. 确保持久化软链接
if [ -d "/opt/nikke-bot/data/nikke" ] && [ ! -e "/opt/nikke-bot/data/nikke/spine-rendered" ]; then
    echo "[3/3] 建立软链接 /opt/nikke-bot/data/nikke/spine-rendered -> $OUT_DIR"
    ln -s "$OUT_DIR" /opt/nikke-bot/data/nikke/spine-rendered
fi

echo "流水线执行完毕。"
