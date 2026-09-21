# Character Card Layout v2 集成证据

日期：2026-09-21  
工作树：`E:\_codex_work\character-card-main-integration`  
分支：`integration/character-card-main`  
状态：`READY_OFFLINE`，尚未合并到 `main`，未部署，未执行 QQ 送达验证。

## 基线与集成策略

- Calendar pixel contract：`ecc54955dd7b315e75e18981e5d366344da7f6cb`。
- Calendar Content Quality：`bde290f2eebcba22270c940fa68290078584b04d`。
- 当前 `origin/main`：`bde290f2eebcba22270c940fa68290078584b04d`。
- 旧 Character Card v2 分支来源：`bef2d3b1d5928f030f28b4cd41324f78e0035df8`。
- Calendar 与模块化 Character Card 基线合并提交：`fa18979`。
- 集成分支最终提交：`8f4fe8a`；仅补 CI 的 Playwright/Chromium 测试依赖安装，不改变插件运行时依赖。

旧分支包含已经淘汰的根目录架构，直接 merge 会删除当前 `features/`、`ui/` 和 `integrations/` 模块。因此本轮只移植 v2 的可验证增量，未把旧架构整体带入：

1. `features/character/layout.py`：摘要面板、安全走廊、头顶→眼睛→胸部轴的确定性计算。
2. `features/character/face_anchor.py`：显式摘要行数约束、核心轴校验、最多 6% 自动缩放和 fail-closed clamp。
3. `features/character/spine_core_axis.py`、`scripts/spine_surface_semantics.mjs`：保守选择胸部/头部候选，拒绝辅助骨骼、头发和头饰误识别。
4. `scripts/extract_spine_face_anchor.mjs` / `scripts/prepare_face_anchors.py`：离线 sidecar 输出核心轴，保留清单范围外的旧 metadata。
5. `ui/t2i_payloads.py` / `templates/t2i/character.html`：按真实摘要行数动态定位面板；0 行不输出面板；未装备装备槽使用低对比 placeholder。
6. `features/character/replica.py`：模板版本升级为 `replica-1600x2400-v2`，并把摘要行数传入构图。

## 视觉证据

使用 `scripts/preview_replica.py`、`assets/spine_manifest.json` 和现有 `assets/spine-rendered/` 静态样本生成 11 个案例：默认角色、服装、宽/高立绘、多个企业、超长名称、空装备、unknown costume。所有案例的 overflow 扫描均为 `[]`。

### Before（v1）

- 目录：`E:\_codex_work\character-card-before-v2\output\playwright\replica`
- 代表图：`rapi.png`、`empty.png`
- v1 的空装备卡仍保留固定空摘要面板，装备图标沿用已装备的粉色视觉。

### After（v2 + refinement）

- 目录：`E:\_codex_work\character-card-main-integration\output\playwright\replica`
- 代表图：`rapi.png`、`rapi-vacation.png`、`wide.png`、`tall.png`、`long-name.png`、`empty.png`、`unknown-costume.png`
- v2 空摘要不再渲染面板；四个装备位置始终保留；未装备图标降饱和、降低透明度并显示“未装备”；unknown costume 保持中性占位，不借用默认服装。
- refinement：摘要面板增加 `overflow:hidden`，动态高度下圆角边界稳定。

上述 PNG 已通过本地图像查看逐张检查；它们是离线合成证据，不是真实账号、QQ 送达、部署或资源授权证据。

## 性能测量

相同 `preview_replica.py` 11 案例 Playwright 批次，在同一 Windows 工作区测量：

| 版本 | 批次耗时 | 说明 |
| --- | ---: | --- |
| v1 | 27,273.16 ms | 同一静态样本与浏览器流程 |
| v2 + refinement | 26,747.95 ms | 同一静态样本与浏览器流程 |

这是合成预览批次的粗粒度测量，不等于生产 QQ 延迟或单卡 P95。

## 回归结果

- Character Card / Face Anchor / Replica / T2I 定向 Python 回归：`66 passed`。
- 补充清单保留与 release metadata 定向回归：`4 passed`、`22 subtests passed`。
- Node Spine surface semantics：`4 passed`。
- `git diff --check`：通过。
- Python/Node 语法检查：通过。
- PR #97 GitHub CI run `35619830726`：Node 扩展、Spine 4.0 headless、Python 3.10/3.11/3.12/3.13 全部通过。
- Issue #73 的 `.1322 → 13.22%` / `.8537 → 85.37%` 合同测试仍在既有 UI 回归中通过；本轮未改数值 formatter 或后端数据合同。
- 最终 full pytest 已按约束只执行一次：`1119 passed, 2 skipped, 653 subtests passed, 17 failed`。其中 16 项来自被旧集成分支带入、但不在当前 `origin/main` 的 `tests/test_calendar_operations_feed.py`；删除该 stale test 后，当前 Calendar v04/v05/Content Quality/P0/UI 定向套件为 `125 passed`。剩余 1 项是本地 worktree 目录名不是 `astrbot_plugin_nikke`，注册测试子进程因此加载了旁边旧 worktree；标准 GitHub checkout 目录与 CI 环境不受此问题影响。按执行约束不重复 full pytest，跨版本结果以 GitHub CI 为准。

## 未完成与边界

- 未合并 `main`，未 force push，未部署服务器。
- GitHub CI 已全绿；等待按集成顺序执行 PR #97 的正常合并。
- 预览使用仓库已有静态 Spine PNG 和合成 fixture，不代表真实账号数据、QQ/NapCat 送达或生产资源许可。
