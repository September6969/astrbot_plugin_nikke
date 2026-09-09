#!/bin/sh
# SFML 2.5 的 RenderTexture 需要一个最小 X11/GL 上下文，Xvfb 不连接真实桌面。
set -eu

display="${DISPLAY:-:99}"
disp_num="${display#:}"
lock_file="/tmp/.X${disp_num}-lock"

we_started_xvfb=0

if [ -f "$lock_file" ]; then
    existing_pid="$(cat "$lock_file" 2>/dev/null | tr -d ' ' || true)"
    if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
        export DISPLAY="${display}"
        exec /usr/local/bin/nikke-spine-worker "$@"
    else
        rm -f "$lock_file" "/tmp/.X11-unix/X${disp_num}" 2>/dev/null || true
    fi
fi

echo "nikke-spine-worker: 启动 Xvfb ${display}" >&2
Xvfb "${display}" -screen 0 32x32x24 -nolisten tcp >/tmp/nikke-xvfb.log 2>&1 &
xvfb_pid=$!
we_started_xvfb=1

ready=0
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ -S "/tmp/.X11-unix/X${disp_num}" ] || [ -f "$lock_file" ]; then
        if kill -0 "${xvfb_pid}" 2>/dev/null; then
            ready=1
            break
        fi
    fi
    sleep 0.1
done

if [ $ready -ne 1 ] && ! kill -0 "${xvfb_pid}" 2>/dev/null; then
    cat /tmp/nikke-xvfb.log >&2 || true
    exit 1
fi

export DISPLAY="${display}"
echo "nikke-spine-worker: Xvfb 已就绪，启动 worker" >&2

worker_ret=0
/usr/local/bin/nikke-spine-worker "$@" || worker_ret=$?

if [ $we_started_xvfb -eq 1 ]; then
    kill "${xvfb_pid}" 2>/dev/null || true
    wait "${xvfb_pid}" 2>/dev/null || true
    rm -f "$lock_file" "/tmp/.X11-unix/X${disp_num}" 2>/dev/null || true
fi

exit $worker_ret

