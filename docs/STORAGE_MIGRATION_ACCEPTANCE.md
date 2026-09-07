# SQLite Storage Migration 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/storage-migration-v1`
- 主题：为本地 SQLite 存储增加 schema 版本元数据和事务化 migration。
- 覆盖：旧 `accounts` 表补齐 `xcommon_cipher` / `user_agent`、重复启动、部分失败回滚、未来 schema 拒绝降级。
- 不涉及：真实生产数据库、部署、自动 rollback、消息发送或 main。

## 合同

启动时在单个 `BEGIN IMMEDIATE` 事务中创建基础表、执行兼容字段迁移并写入 `schema_meta`。migration 重复运行保持幂等；任何异常统一 rollback；检测到高于当前插件的 schema 版本时拒绝启动，不尝试降级或覆盖数据。

这是代码和离线临时 SQLite 的验证，不是对真实生产数据库执行 migration 的授权或现场证据。

## TDD 与验证

```text
pytest -q tests/test_storage_migration.py
4 passed
```

测试使用合成密钥和临时 SQLite，验证旧行保留、字段补齐、版本写入、重复初始化、迁移失败回滚和未来版本保护。
