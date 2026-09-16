# 缓存清理 V1 验收记录

## 范围与安全边界

这是离线运维工具，不是自动后台清理，也不读取或写入真实账号接口。它只扫描 `data/nikke/cache`、`data/nikke/voice_cache` 和公告缓存文件；`cards`、`nikke.sqlite3`、`secret.key`、扩展 ZIP 与未知目录均受保护。

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

确认离线计划后才可应用：

```bash
python -m astrbot_plugin_nikke.scripts.cleanup_cache --data-dir data/nikke --apply
```

本 PR 不在真实 `data/nikke` 目录运行 `--apply`，也不把合成目录测试称为生产清理证据。

## 测试

`tests/test_cache_cleanup.py` 覆盖：默认只读、已知目录白名单、临时文件年龄、保护路径、应用删除、应用阶段白名单复核、路径边界、根目录和缓存条目符号链接跳过，以及异常数值拒绝。
