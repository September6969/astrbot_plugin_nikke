# Spine 遗留隔离验收

状态：`EXPERIMENTAL` / `NEEDS_LIVE_EVIDENCE`（2026-09-08）。本主题不代表生产动态渲染完成，也不代表已取得 Spine runtime、NIKKE 动态素材或编辑器许可。

- 实现移入 `experimental/spine_prerenderer.py`；根目录 `spine_prerenderer.py` 仅保留历史兼容导出壳。
- `AssetManager` 普通构造、`get_character_portrait()`、`resolve_character_assets()` 不导入实验模块，不创建 Spine 队列，不探测 runtime，不下载 skel/atlas。
- 唯一实验调用为显式 `enqueue_experimental_spine()`；它要求调用者明确选择，并继续受版本、预算、缓存、队列和 fallback 合同约束。
- 现有 L2D 索引/URL 方法和专项测试保留，因为它们仍被兼容入口或预研验证使用；没有把预检查、队列或 synthetic bundle 当成真实渲染证据。
- 未来 GIF/WebP/动态页面应以新 feature 独立评估，不回绑静态角色卡。

证据：`tests/test_asset_manager.py` 验证普通路径没有 Spine 模块导入；`tests/test_spine_spike.py` 与 `tests/test_spine_inspection.py` 仅验证队列/本地预检查。真实 runtime 兼容性、Linux headless、合法测试素材和 benchmark 均为 `NOT_EXECUTED`。
