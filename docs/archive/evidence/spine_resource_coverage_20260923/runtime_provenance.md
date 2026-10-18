# c018 离线渲染运行时取证

- 运行时来源：官方 `@esotericsoftware/spine-core` npm 包。
- 运行时包版本：`4.1.56`。
- c018 skeleton 实际解析版本：`4.1.20`。
- 生成方式：官方 Spine Core 解析 face anchor；服务器现有、匹配 4.1 的 headless worker 生成 idle `t=0` 透明 PNG。
- 运行时文件、raw `.skel`、`.atlas` 与原始纹理仅作为离线输入，没有提交到仓库。
- 仓库仅提交渲染 PNG、manifest 元数据、哈希、face-anchor 元数据与覆盖审计证据。
- 许可边界：Spine runtime 的使用与分发遵循官方 runtime/license 条款；公开 Nikke-db URL 不被当作 NIKKE 美术资产再分发授权。
- 本证据属于 `READY_OFFLINE`，不代表真实账号、QQ 送达或生产部署验收。
