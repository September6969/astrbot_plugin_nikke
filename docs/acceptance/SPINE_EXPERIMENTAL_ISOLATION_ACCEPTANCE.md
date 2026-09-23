# Spine 遗留隔离验收

状态：`EXPERIMENTAL` / `NEEDS_LIVE_EVIDENCE`（2026-09-08）。本主题不代表生产动态渲染完成，也不代表已取得 Spine runtime、NIKKE 动态素材或编辑器许可。

> 历史快照说明：以下条目记录 2026-09-08 的实验隔离状态，不代表当前代码结构。R21（2026-09-23）审计确认实验转发模块及 `enqueue_experimental_spine()` 没有生产、测试调用器、脚本、扩展或动态导入消费者，已删除；正式编排仍由 `integrations/spine/prerenderer.py` 唯一拥有。静态角色卡路径仍不启动后台预渲染。

- 实现移入 `experimental/spine_prerenderer.py`；根目录 `spine_prerenderer.py` 仅保留历史兼容导出壳。
- `AssetManager` 普通构造、`get_character_portrait()`、`resolve_character_assets()` 不导入实验模块，不创建 Spine 队列，不探测 runtime，不下载 skel/atlas。
- 唯一实验调用为显式 `enqueue_experimental_spine()`；它要求调用者明确选择，并继续受版本、预算、缓存、队列和 fallback 合同约束。
- 现有 L2D 索引/URL 方法和专项测试保留，因为它们仍被兼容入口或预研验证使用；没有把预检查、队列或 synthetic bundle 当成真实渲染证据。
- 未来 GIF/WebP/动态页面应以新 feature 独立评估，不回绑静态角色卡。

证据：`tests/test_asset_manager.py` 验证普通路径没有 Spine 模块导入；`tests/test_spine_spike.py` 与 `tests/test_spine_inspection.py` 仅验证队列/本地预检查。真实 runtime 兼容性、Linux headless、合法测试素材和 benchmark 均为 `NOT_EXECUTED`。

本 PR 的提交历史保持线性；后续修正只追加普通提交，不重写远端历史。
