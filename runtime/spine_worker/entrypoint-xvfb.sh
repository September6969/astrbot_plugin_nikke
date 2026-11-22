#!/bin/sh
# SFML 2.5 的 RenderTexture 需要一个最小 X11/GL 上下文，Xvfb 不连接真实桌面。
# 每次调用都启动私有 Xvfb：-displayfd 由 X server 原子分配空闲 display 号，
# 避免并发 worker 共用固定 :99 而复用或误杀对方的 Xvfb；trap 保证正常结束、
# 失败或被 SIGTERM/SIGINT/SIGHUP 终止时都回收 worker、Xvfb 与临时文件。
set -eu

worker_name="nikke-spine-worker"
worker_bin="/usr/local/bin/nikke-spine-worker"

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/${worker_name}-xvfb.XXXXXX")"
display_file="${work_dir}/display"
xvfb_log="${work_dir}/xvfb.log"
xvfb_pid=""
worker_pid=""

cleanup() {
    trap - EXIT HUP INT TERM
    if [ -n "${worker_pid}" ]; then
        kill "${worker_pid}" 2>/dev/null || true
        wait "${worker_pid}" 2>/dev/null || true
    fi
    if [ -n "${xvfb_pid}" ]; then
        kill "${xvfb_pid}" 2>/dev/null || true
        wait "${xvfb_pid}" 2>/dev/null || true
    fi
    rm -rf "${work_dir}"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

: >"${display_file}"
Xvfb -displayfd 3 -screen 0 32x32x24 -nolisten tcp 3>"${display_file}" >"${xvfb_log}" 2>&1 &
xvfb_pid=$!

# X server 就绪后才会向 displayfd 写入以换行结尾的 display 号。
display_number=""
tries=0
while [ "${tries}" -lt 50 ]; do
    # read 只有读到完整一行时才成功，避免读到写入一半的 display 号。
    if IFS= read -r display_line <"${display_file}"; then
        case "${display_line}" in
            '' | *[!0-9]*) ;;
            *) display_number="${display_line}" ;;
        esac
        break
    fi
    if ! kill -0 "${xvfb_pid}" 2>/dev/null; then
        break
    fi
    tries=$((tries + 1))
    sleep 0.1
done

if [ -z "${display_number}" ]; then
    echo "${worker_name}: Xvfb 启动失败" >&2
    cat "${xvfb_log}" >&2 || true
    exit 1
fi

export DISPLAY=":${display_number}"
echo "${worker_name}: Xvfb ${DISPLAY} 已就绪，启动 worker" >&2

# 后台运行并 wait，使 shell 在 worker 运行期间也能立即响应终止信号。
"${worker_bin}" "$@" &
worker_pid=$!
worker_ret=0
wait "${worker_pid}" || worker_ret=$?
worker_pid=""
exit "${worker_ret}"
