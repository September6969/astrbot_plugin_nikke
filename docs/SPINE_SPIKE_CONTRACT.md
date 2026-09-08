# Spine 技术预研契约

状态：`FORMAL_BACKEND_OFFLINE` / `NEEDS_LIVE_EVIDENCE`。本文件描述正式编排层的离线合同，不代表已安装、授权或联调具体 Spine runtime，也不代表已取得 NIKKE 资源授权。

## 本次增量范围

本增量只验证不依赖真实运行时的外围行为：

- `SpinePreRenderer.inspect_bundle()` 对本地 atlas/JSON 做大小、路径、纹理页和 `major.minor` 预检查；注入的 runtime 只能消费严格匹配的版本。
- `SpineEvidenceReport` 分开记录资源发现、bundle 完整性、版本、运行时兼容性、素材许可、Linux headless、真实渲染和 benchmark。
- `SpineTaskQueue` 保持每 key 去重、容量上限、1～2 个 worker，并提供显式启动、空闲等待和优雅停止。
- `SpineJob.budget_seconds` 从任务创建时间开始计时，因此保守覆盖排队等待、bundle 下载和渲染；worker 开始执行前若已过期则回退，不调用运行时。
- `SpineBundleFetcher` 仅允许无账号上下文的 Nikke-DB raw GitHub 路径，按文件/总量限制写入版本化 bundle 缓存。
- AssetManager 只消费已有 L2D 索引，防止每张角色卡触发索引 N+1；Spine cache hit 可直接返回，miss 仅后台预热。

## 明确不在范围内

- 不下载、安装、加载或执行 Spine runtime。
- 不访问 NIKKE 生产账号、Cookie、私有接口或真实消息发送。
- 不把公共资源 URL 访问当作再分发授权。
- 不将合成 atlas/JSON 或 Pillow 图像当作真实 Spine 渲染。
- 不同步等待后台预渲染，也不在缓存 miss 时补发迟到替换卡；当前默认没有具体 runtime，因此生产环境仍走静态 FB/几何 fallback。

## 证据值语义

`SpineEvidenceReport` 的 `NOT_EXECUTED` 和 `NOT_VERIFIED` 是有意保留的状态，不允许在没有现场证据时改写为成功：

| 字段 | 当前本地预检查允许的值 | 不能据此推出 |
| --- | --- | --- |
| `resource_discovery` | `LOCAL_INPUT_ONLY` | 已发现公开或生产资源 |
| `bundle_integrity` | `PASS` / `FAIL` | 运行时可加载 |
| `spine_version` | 观测到的 `major.minor` 或 `SPINE_VERSION_UNKNOWN` | 已确认兼容 |
| `runtime_compatibility` | `NOT_EXECUTED` | 已安装或已授权 runtime |
| `legal_test_asset` | `NOT_VERIFIED` | 测试素材可生产分发 |
| `linux_headless` | `NOT_EXECUTED` | Linux 服务端可运行 |
| `render_verified` | `NOT_EXECUTED` | 已生成真实透明 RGBA PNG |
| `benchmark` | `NOT_EXECUTED` | 已满足出卡预算 |

## 生命周期约束

生产出卡不能同步等待 Spine。运行时接入时，bundle 加载、解析、纹理加载、渲染、裁切、PNG 编码和缓存写入纳入同一个硬预算；超时必须回退到现有静态全身像或占位图。后台任务不能在已经发送的卡片之后补发“迟到替换”。

