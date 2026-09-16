# Favorite Item / Cube 资源完整性验收

状态：`READY_OFFLINE`（2026-09-08）。

- 当前 registry 仅声明 4 个 Favorite Item TID 与 8 个 Cube TID；来源登记日期为 2026-09-06，清单 SHA-256 由 `assets/registry_manifest.json` 校验。
- 本主题没有发现新的、带来源证据的 TID，因此没有扩充映射，也不把少量清单描述为完整数据库。
- 未登记 TID 不访问通用 source、不命中残留同名缓存、不映射到相邻资源，直接返回抽象 fallback。
- 对 Favorite/Cube 分别模拟 HTTP 404、读取超时、响应解码失败与损坏缓存；每种情况均返回 128×128 RGBA 抽象图，整卡可继续生成。
- 已登记资源继续使用同一缓存/解码链；缓存命中不重复发请求。

`NEEDS_LIVE_EVIDENCE`：完整 TID 列表、当前 CDN 存在性和资源权利边界。最小现场动作是从明确公开来源读取单个候选 TID/资源 ID，记录 URL、日期与内容哈希；不需要玩家 Cookie，本 PR 未执行真实账号或消息动作。
