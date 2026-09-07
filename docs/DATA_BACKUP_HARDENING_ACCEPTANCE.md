# Local Data Backup Hardening 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/data-backup-hardening`
- 主题：离线备份 `nikke.sqlite3` 与 `secret.key`
- 用户可见变化：新增本地备份命令；备份包含 SQLite 完整性校验和 SHA-256 manifest，不覆盖已有备份，也不允许输出目录位于源数据目录内。
- 不涉及：网络、真实账号、部署、生产数据库、消息发送、自动迁移、main 和 ruleset。

## 使用合同

```text
python -m astrbot_plugin_nikke.scripts.backup_nikke_data \
  --data-dir <AstrBot>/data/nikke \
  --destination <安全的备份目录> \
  --label <可选的备份名称>
```

源目录必须同时存在 `nikke.sqlite3` 与 `secret.key`。工具使用 SQLite online backup 读取数据库，在临时目录中完成完整性检查、密钥复制和 manifest 写入后再落盘；已有目标不会覆盖。manifest 不包含 Cookie、QQ 或 OpenID，只记录文件名、创建时间和哈希。

## TDD 与验证

```text
pytest -q tests/test_data_backup.py
3 passed
```

测试覆盖数据库内容可恢复、密钥字节保持一致、manifest 文件合同、禁止源目录内备份、禁止同名覆盖、不可用输出目录和损坏 SQLite 的统一错误语义。备份密钥文件会明确收紧为 `600`（在 Windows 上仅作平台允许的权限映射）。测试只使用临时合成 SQLite 与合成密钥；未读取或写入真实 `data/nikke`，没有现场证据或部署声明。
