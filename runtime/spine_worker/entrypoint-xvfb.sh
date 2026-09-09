#!/bin/sh
# SFML 2.5 的 RenderTexture 需要一个最小 X11/GL 上下文，Xvfb 不连接真实桌面。
set -eu

display="${DISPLAY:-:99}"
echo "nikke-spine-worker: 启动 Xvfb ${display}" >&2
Xvfb "${display}" -screen 0 32x32x24 -nolisten tcp >/tmp/nikke-xvfb.log 2>&1 &
xvfb_pid=$!
trap 'kill "${xvfb_pid}" 2>/dev/null || true' EXIT
sleep 1
if ! kill -0 "${xvfb_pid}" 2>/dev/null; then
	cat /tmp/nikke-xvfb.log >&2 || true
	exit 1
fi
export DISPLAY="${display}"
echo "nikke-spine-worker: Xvfb 已就绪，启动 worker" >&2
exec /usr/local/bin/nikke-spine-worker "$@"
