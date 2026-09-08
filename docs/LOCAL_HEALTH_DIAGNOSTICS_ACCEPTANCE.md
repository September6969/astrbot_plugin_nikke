# Local Health Diagnostics 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/health-diagnostics-v1`
- 主题：把现有 `/妮姬 管理 健康` 扩展为只读的本地运行健康诊断。
- 覆盖：数据目录、`nikke.sqlite3`、`secret.key`、已知缓存目录体积、临时缓存文件数量、磁盘容量。
- 不涉及：缓存删除、网络、真实账号、Cookie、消息发送、部署、生产迁移和 main。

## 合同

```text
/妮姬 管理 健康
```

管理员输出只包含状态和聚合数字，不输出绝对路径、文件名、Cookie、QQ 号或账号内容。诊断不会创建目录、修改数据库、读取密钥内容或自动清理缓存；发现临时文件时仅给出提示。

已知缓存范围为 `cache`、`voice_cache`、`announcements` 三个数据子目录；统计不跟随数据目录路径或缓存条目中的符号链接，避免越出数据目录。磁盘容量必须是可表示的非负整数且 `free <= total`，异常或不可表示值按未知处理并进入“需关注”。

## TDD 与验证

```text
pytest -q tests/test_runtime_health.py
7 passed
```

测试覆盖完整数据目录、缺失目录、根目录及父级路径符号链接不跟随、缓存字节/临时文件统计、异常及不可表示磁盘数值降级为未知、敏感值不出现在文本中，以及管理员命令真实接线。测试只使用临时合成目录；没有现场账号或生产数据证据。

本轮修复提交：`ce76135`。直接运行不依赖 AstrBot 的 `runtime_health` 边界检查与 `compileall`、`git diff --check` 已通过；当前环境的完整 targeted wiring 测试因缺少 `astrbot` 包无法本地导入，未将其冒充为通过。CI 运行 `34186436721` 对最终 head 四项全绿，Python 3.10 全量 `263 passed、43 subtests、3 warnings`，Python 3.11/3.12 与 Node 扩展检查均成功。
