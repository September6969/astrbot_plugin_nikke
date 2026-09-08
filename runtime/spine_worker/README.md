# Spine 4.1 headless worker

这里仅保存本项目的 worker 接口和构建文件。Docker 构建阶段从官方
`EsotericSoftware/spine-runtimes` 的 `4.1` 分支固定提交拉取 C++/SDL runtime；
官方源码、二进制和 NIKKE bundle 不提交到本仓库。

## 输入输出

worker 接受一个 `.skel` 或 `.json`、atlas、animation、可选 skin，以及受限画布参数，
输出小端序 `uint32 width`、`uint32 height`、RGBA8888 像素的临时 `.rgba` 文件。
Python 适配器负责路径边界、超时、输出大小、透明裁切和 PNG cache。worker 只允许
软件 renderer 与 SDL dummy video，不能访问账号上下文。

## 版本与许可

构建默认锁定 Spine runtime commit `77a5db0ec6d16331f5efbaa7662bba9355bd3424`，
对应官方 4.1 runtime。使用、集成、分发前必须按官方
[Spine Runtimes License](https://esotericsoftware.com/spine-runtimes-license) 与
[Editor License](https://esotericsoftware.com/spine-editor-license) 核验；
公开源码和公开 URL 不自动构成 NIKKE 素材授权。
