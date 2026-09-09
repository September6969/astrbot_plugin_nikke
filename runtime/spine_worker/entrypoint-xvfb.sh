#!/bin/sh
# SFML 2.5 的 RenderTexture 需要一个最小 X11/GL 上下文，Xvfb 不连接真实桌面。
set -eu
exec xvfb-run -a -s "-screen 0 32x32x24 -nolisten tcp" /usr/local/bin/nikke-spine-worker "$@"
