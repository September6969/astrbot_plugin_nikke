#!/usr/bin/env bash
# 旧命令兼容入口；exec 保留参数、退出码及取消信号。
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/spine/render_spine_candidate_batch.sh" "$@"
