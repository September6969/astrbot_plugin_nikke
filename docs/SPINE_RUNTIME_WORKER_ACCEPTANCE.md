# Spine 4.1 headless worker 验收记录

状态：`READY_OFFLINE`（worker 接口、配置接线和失败边界）/ `NEEDS_LIVE_EVIDENCE`（Linux 编译、真实渲染、benchmark、素材与许可）。本记录不把合成 RGBA、Python mock 或 Dockerfile 的存在描述为真实 Spine 产品联调。

## 已实现

- `runtime/spine_worker/main.cpp` 使用官方 spine-cpp/spine-sdl API 读取 JSON 或 binary skeleton、atlas 和纹理，选择 setup pose、animation、可选 skin，计算 bounds 后以 SDL dummy/software renderer 输出透明 RGBA。
- worker 通过小端序 `width/height/RGBA` 临时协议返回像素；Python `SpineWorkerRuntime` 负责 bundle root 边界、animation/skin 标识、输出尺寸与大小上限、超时、JSON 响应和临时文件清理。
- `spine_runtime_config.py` 只在 `spine_worker_path` 明确存在时启用；缺失或空配置始终回到现有静态 FB/占位链。AstrBot 使用共享 `data/nikke/cache/spine-bundles`，不携带 Cookie、token 或私有 header。
- 无运行时预检查对 binary skeleton 无法确认版本时直接拒绝调用 worker；只有 `VERSION_MATCH` 才会执行，不能因配置为 4.1 就猜测输入版本。
- Docker 构建从官方 `spine-runtimes` 4.1 分支固定 commit `77a5db0ec6d16331f5efbaa7662bba9355bd3424`，不把官方源码或二进制提交到本仓库。
- `assets/costumes.json` 保持 `{}`。当前没有已核验的实际 costume 对照，所以 unknown/invalid 不回退默认服装；测试 fixture 中的 `skin_01` 不进入正式清单。

## 离线证据

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| Python worker adapter | `READY_OFFLINE` | `tests/test_spine_runtime_worker.py`：RGBA 协议、路径越界、坏输出、超时；本 PR 定向新增与 formal backend 共 13 项 |
| AstrBot 配置接线 | `READY_OFFLINE` | `tests/test_spine_runtime_config.py`：空/缺失 worker 回退、共享 bundle root |
| 正式 Spine 编排兼容 | `READY_OFFLINE` | `tests/test_spine_formal_backend.py`、`tests/test_spine_spike.py`、`tests/test_spine_inspection.py` |
| 官方 Linux 编译 | `NEEDS_LIVE_EVIDENCE` | `serv` 临时 Docker 构建需重试；当前 SSH 在 banner 阶段超时，未写入现有容器 |
| headless 真实 PNG | `NEEDS_LIVE_EVIDENCE` | 尚无合法测试 bundle 与实际 worker 输出 |
| benchmark | `NEEDS_LIVE_EVIDENCE` | 尚未取得运行时耗时/吞吐测量 |
| runtime/素材许可 | `NEEDS_HUMAN_DECISION` | 官方 runtime 许可与 NIKKE 上游素材权利必须分开确认；公开仓库和 URL 不等于再分发授权 |

## 外部来源与边界

- 官方 runtime 文档：<https://us.esotericsoftware.com/spine-runtimes>
- 官方仓库：<https://github.com/EsotericSoftware/spine-runtimes>
- 官方分支与 API 仅作为构建依赖来源；构建提交须重新核对，不能用分支名替代可复现 commit。
- 现场继续只使用已有 `astrbot`、`napcat`、`nikke-caddy` 容器；不会搜集密码、Cookie、二维码、token，不执行 CDK 消费，不改 ruleset，不部署或自动合并。
