# 缓存清理 V1 验收记录

## 范围与安全边界

这是离线运维工具，不是自动后台清理，也不读取或写入真实账号接口；`--apply` 必须在插件停止后执行。它只扫描 `data/nikke/cache`、`data/nikke/voice_cache`、`data/nikke/tarot/reversed_cache` 中严格命名的倒置图缓存（`*_reversed_<12 位十六进制>.png` 及其 `.tmp.png`）和公告缓存临时文件；`cards`、`nikke.sqlite3`、`secret.key`、扩展 ZIP、`tarot/daily_draws.json`、`calendar/`、`spine-rendered/`、`spine-manifest.json` 与未知目录均受保护。

PR-6B（G7-misc-dead-f1）收紧默认范围：

- `announcements/announcements_cache.json` 保存公告版本历史与去重状态，删除后可能让合法的公告更新提醒被 SQLite 基线抑制，因此**不再属于默认清理**，只有显式 `--include-announcement-state` 才纳入。
- 离线回退或运行中可能使用的缓存默认受保护：`cache/character-stats/`（刷新失败时的旧统计）、`cache/nikke-db/index/`、`cache/spine-manifest.json`、`cache/spine_manifest.json`、`cache/portraits/`（按 mtime 老化会删除仍常用的运行时立绘，重渲染依赖远程 bundle 与 Spine worker）、`cache/spine-bundles/`（避免打断进行中的渲染）。只有显式 `--include-fallback-caches` 才纳入。
- 临时文件判定与 `core/health.py` 一致（`.tmp` 后缀、`.tmp-` 前缀、`.tmp.` 中缀），并补充 Spine worker 的 `.spine-worker-*.rgba`；这些文件按临时文件保留时长处理。
- PR-6A 对塔罗原图的高保真压缩会改变倒置图指纹，旧倒置图随之成为孤儿，可由本工具按 30 天规则回收。

- 默认只输出 JSON 清理计划，不删除文件。
- 只有显式传入 `--apply` 才逐文件删除已列入计划的陈旧缓存。
- 普通缓存默认保留 30 天；`.tmp` 临时文件默认保留 1 小时，可由参数调整。
- 不删除目录，不跟随符号链接；应用阶段再次检查普通文件、路径边界和文件存在性。
- 清理根目录自身为符号链接时整项跳过；保留时长和当前时间必须是有限非负数；应用阶段再次核对白名单与受保护路径。
- 竞态或权限失败只记录相对路径和异常类型，不输出绝对路径、凭据或账号数据。

## 用法

先预览：

```bash
python -m astrbot_plugin_nikke.scripts.cleanup_cache --data-dir data/nikke
```

停止插件、确认离线计划后才可应用：

```bash
python -m astrbot_plugin_nikke.scripts.cleanup_cache --data-dir data/nikke --apply
```

本 PR 不在真实 `data/nikke` 目录运行 `--apply`，也不把合成目录测试称为生产清理证据。

## 测试

`tests/test_cache_cleanup.py` 覆盖：默认只读、已知目录白名单、临时文件年龄、保护路径、应用删除、应用阶段白名单复核、路径边界、根目录和缓存条目符号链接跳过、异常数值拒绝，以及塔罗倒置图命名门控、`daily_draws.json` 不受影响、新临时文件模式、回退缓存默认保护与公告状态文件默认排除。
