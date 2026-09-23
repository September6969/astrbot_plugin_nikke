# Spine Runtime Cache V2 验收记录

## 离线验收门槛

- [ ] bundled PNG、runtime PNG、旧版有效 cache 的读取顺序。
- [ ] 首次缺图立即 fallback，并且 20 个并发请求只入队 1 个 warm job。
- [ ] worker 完成后 PNG、render index 和 metadata 均为原子写入。
- [ ] 进程重启后本地 vendor index、bundle、PNG、metadata 可继续读取。
- [ ] vendor 命中不触发 HTTP；缺失 bundle 才按 allowlist 远端补齐。
- [ ] wrong version、越界路径、错误 PNG/hash、损坏 metadata、worker 不可用和队列满均安全 fallback。
- [ ] c018、c401、c581 的既有 bundled manifest/semantic contract 不被 runtime cache 覆盖。

## 现场验收

本次代码变更不执行服务器写入、容器重启、账号操作或 QQ 消息。合并后需在明确的
server acceptance 任务中记录：

- `/AstrBot/data/vendor/nikke-db/index/l2d.json` 与 cache 目录权限/持久卷。
- 第一次查询的 fallback + warm 日志、第二次查询的 runtime cache hit、第三次重启后的 cache hit。
- 真实 worker major.minor、渲染耗时、PNG/hash/image_size 和 face metadata 来源。
- 缺少 metadata generator 时必须标记 `NEEDS_RUNTIME_METADATA`，不得称为已完成生产联调。

## 证据状态

`READY_FOR_SERVER_ACCEPTANCE` 只表示代码、离线测试和 PR CI 已通过；不表示真实部署、
QQ 送达、账号数据或资源分发授权已经验证。
