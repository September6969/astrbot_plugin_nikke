# 发布元数据 V1 验收记录

## 合同

- `_version.py` 的 `PLUGIN_VERSION` 是插件运行时版本唯一来源。
- `metadata.yaml` 的 `version` 必须与 `PLUGIN_VERSION` 完全一致。
- `_conf_schema.json` 是 14 个配置键、类型和默认值的交接合同；配置说明必须覆盖每个键。
- `CHANGELOG.md` 只记录当前 main 基线 `0.1.8`，未合并 Draft PR 不写入已发布版本。

## 离线验证

`tests/test_release_metadata.py` 读取实际文件并验证：

- 两处版本值一致；
- schema 的 14 个键和默认值保持合同；
- 配置说明覆盖全部 schema 键；
- 更新记录明确当前基线且没有把 Draft PR 当作已发布内容。

这些检查不创建发行包、不上传资源、不部署，也不替代现场账号、消息发送或生产运行时证据。
