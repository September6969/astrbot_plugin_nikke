# Spine Runtime Cache V2

## 目标

角色卡请求线程只消费已经验证的 PNG。缺少角色/服装 PNG 时立即返回既有 fallback，
同时向受控后台队列提交一次 warm；后台才允许读取或补齐 Nikke-DB bundle、调用匹配
major.minor 的 Spine runtime、裁切透明 RGBA PNG，并以原子写入方式保存缓存。

## 存储合同

生产默认目录由 AstrBot data root 推导：

```text
/AstrBot/data/vendor/nikke-db/index/l2d.json
/AstrBot/data/vendor/nikke-db/l2d/<render_id>/
/AstrBot/data/nikke/cache/spine-rendered/
/AstrBot/data/nikke/cache/spine-meta/
```

测试和离线脚本可以通过 `nikke_db_local_root`、`spine_runtime_cache_dir`、
`spine_runtime_meta_dir` 注入临时目录。没有显式配置的旧调用仍使用原 cache 子目录，
以保持旧测试和离线工具兼容。

## 请求与后台边界

1. `AssetManager.get_character_portrait()` 顺序读取 bundled verified PNG、runtime PNG、旧版有效 PNG。
2. 仍然缺失时只记录一次 per-key warm 任务并返回中性 fallback；不会在请求线程发 HTTP、解析 Spine 或等待 worker。
3. warm 任务优先读取本地 vendor；只有 `nikke_db_remote_fetch_enabled` 打开时才访问公开 Nikke-DB HTTPS allowlist。
4. bundle 下载、skeleton 版本探测、runtime 渲染、PNG 与 metadata 写入都在后台执行。
5. 任务 key 包含 render id、costume token、source identity、runtime、renderer、animation；队列按 key 去重。

## 安全与失败语义

- 只允许 `raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/` 的 HTTPS URL，拒绝凭据、查询串、片段和重定向。
- skeleton、atlas、texture 和总 bundle 均有大小上限；路径必须位于对应根目录。
- actual skeleton header 决定 runtime 4.0/4.1；无法识别或不匹配时 fail closed。
- 临时文件只在同一文件系统原子替换；损坏 PNG、错误 hash、损坏 metadata 不进入可用缓存。
- runtime metadata 绑定 `pixel_sha256` 和 `image_size`，bundled metadata 优先，runtime metadata 仅作为同身份 variant。
- 不提交全量 raw 游戏 bundle；vendor 镜像是部署数据目录，不是仓库资源分发。

## 工具

`python scripts/sync_nikkedb_resources.py` 默认 dry-run；需要落地公开资源时显式使用
`--apply`，可用 `--index-only`、`--render-id`、`--missing-from-character-registry` 或
`--prefetch-all-spine` 限定范围。

`python scripts/audit_nikkedb_cache.py` 默认只读审计；只有明确传入 `--prune-orphans`
才删除不在索引中的 vendor bundle 目录。

## 运行时元数据

正式 extractor/worker 通过 `SpinePreRenderer.metadata_writer` 注入，必须生成带真实
像素 hash、尺寸、point 和必要 core axis 的记录；本模块不会从角色名称、序号或静态
图片外观猜测坐标。未提供 generator 时只保存 PNG 和 render index，状态仍是
`NEEDS_RUNTIME_METADATA`，不可冒充完整 face-anchor 联调。
