# Spine 4.0 headless worker

这里仅保存本项目的 worker 接口和构建文件。Docker 构建阶段从官方
`EsotericSoftware/spine-runtimes` 的 `4.0` 分支固定提交拉取 C++/SFML runtime；
官方源码、二进制和 NIKKE bundle 不提交到本仓库。

## 输入输出

worker 接受一个 `.skel` 或 `.json`、atlas、animation、可选 skin，以及受限画布参数，
输出小端序 `uint32 width`、`uint32 height`、RGBA8888 像素的临时 `.rgba` 文件。
`setup` animation token 表示保持 skeleton setup pose，不要求 bundle 额外提供动画名。
Python 适配器负责路径边界、超时、输出大小、透明裁切和 PNG cache。SFML 通过最小
Xvfb 上下文提供无桌面 RenderTexture，worker 不能访问账号上下文。

进程边界：Python 适配器只向 worker 透传白名单环境变量（`PATH`、`HOME`、区域设置、
X11/GL 与 Docker CLI 连接配置等），插件密钥与代理凭据不会下发；worker 在独立进程组
中运行，超时先向整组发送 SIGTERM、短暂宽限后 SIGKILL，不留下孤儿 Xvfb。
`entrypoint-xvfb*.sh` 每次调用都用 `Xvfb -displayfd` 动态分配私有 display，
并以 `trap` 在正常退出、失败或收到终止信号时回收 worker、Xvfb 与临时目录；
并发调用不再共享固定的 `:99`。

## 版本与许可

构建默认锁定 Spine runtime commit `425ce416bb218b28caeec47b317aa57cd7140375`，
对应官方 4.0 runtime。使用、集成、分发前必须按官方
[Spine Runtimes License](https://esotericsoftware.com/spine-runtimes-license) 与
[Editor License](https://esotericsoftware.com/spine-editor-license) 核验；
公开源码和公开 URL 不自动构成 NIKKE 素材授权。
