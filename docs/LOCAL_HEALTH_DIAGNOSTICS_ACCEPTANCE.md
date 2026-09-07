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

已知缓存范围为 `cache`、`voice_cache`、`announcements` 三个数据子目录；统计不跟随符号链接，避免越出数据目录。

## TDD 与验证

```text
pytest -q tests/test_runtime_health.py
5 passed
```

测试覆盖完整数据目录、缺失目录、根目录符号链接不跟随、缓存字节/临时文件统计、异常磁盘数值降级为未知、敏感值不出现在文本中，以及管理员命令真实接线。测试只使用临时合成目录；没有现场账号或生产数据证据。
