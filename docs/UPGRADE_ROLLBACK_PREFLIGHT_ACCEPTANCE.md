# 升级/回滚前置检查验收

本切片只提供升级或回滚前的离线、只读检查，不执行数据库迁移、回滚、复制、删除、覆盖或生产写入。它不构成真实部署、恢复演练或生产数据验收。

## 检查内容

- `storage_pair`：检查数据根目录不是符号链接且 `nikke.sqlite3` 与 `secret.key` 同时为非空普通文件；备份根目录同样拒绝符号链接。
- `database`：使用 SQLite `mode=ro` URI 执行 `integrity_check`，并检查当前主线所需表和 `accounts` 字段。
- `backup_pair` / `backup_database`：只有传入 `--backup-dir` 时检查备份集；不会复制、覆盖或删除备份。
- `disk_capacity`：仅在数据根目录为普通目录时检查其所在文件系统余量；结果不输出路径、容量细节、账号标识或凭据。

## 状态语义

- `READY`：存储成对存在、SQLite 完整性和字段合同通过、磁盘余量达标。
- `MIGRATION_REQUIRED`：SQLite 可读且基础表存在，但仍缺少当前版本的可迁移字段；本命令不会执行迁移。
- `BLOCKED`：缺少或不是普通文件、SQLite 损坏/不可读、表合同不支持、备份集缺失或磁盘余量不足。
- 数据根目录或备份根目录为符号链接时不读取其目标内容，直接返回 `BLOCKED`。

## 使用

在离线检查目录执行：

```powershell
python scripts/upgrade_preflight.py --data-dir .\data\nikke --min-free-bytes 0 --min-free-percent 0
python scripts/upgrade_preflight.py --data-dir .\data\nikke --backup-dir .\backup\nikke
```

默认最低余量是 1 GiB 且 10%。退出码为 `0`（READY）、`2`（MIGRATION_REQUIRED）或 `1`（BLOCKED）。示例目录只用于离线验证；在本 PR 中没有对真实账号、生产数据库、部署环境或备份介质执行操作。

## 证据边界

测试使用临时目录和合成 SQLite/密钥文件，验证不会改变文件内容或修改时间。通过测试不等于真实数据已备份、迁移或可回滚；生产迁移和回滚仍需单独的人为授权、现场备份和恢复证据。
