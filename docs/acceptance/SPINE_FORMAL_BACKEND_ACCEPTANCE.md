# Spine 正式后端离线验收

状态：`READY_OFFLINE`（编排层） / `NEEDS_LIVE_EVIDENCE`（具体 runtime、许可、Linux 和真实素材）。本记录不把合成 FakeRuntime、公开 URL、绿色 CI 或本地 bundle 预检查描述为真实 Spine 联调、资源授权或生产部署。

## 本次实现

- `spine_prerenderer.py` 现在是正式编排实现；`experimental/spine_prerenderer.py` 仅保留历史导出兼容层，不重复维护另一份实现。
- `SpineRuntimeBackend` 通过依赖注入接收具体 runtime，严格比较 `major.minor`；未知或不匹配版本直接回退，不猜测默认 runtime。
- `SpineBundleFetcher` 只接受无账号上下文的 `raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/` HTTPS 路径，按 skeleton、atlas、纹理页和总量限制写入原子缓存。
- `SpinePreRenderer` 负责 bundle 预检查、透明 RGBA 归一化、可见像素裁切、版本化 PNG 缓存和后台队列；runtime 异常不会穿透角色卡线程。
- `AssetManager` 读取已有 L2D 索引，不在角色卡热路径刷新 `l2d.json`；Spine cache hit 可直接作为 portrait，cache miss 仅在匹配 runtime 已注入时后台预热，当前请求继续走静态 FB/几何 fallback。
- `close()` 同时回收图片线程池和 Spine 队列；任务预算从入队时计时，覆盖排队与 bundle 下载阶段。

## 离线证据

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| runtime adapter 输入/输出合同 | `READY_OFFLINE` | `tests/test_spine_formal_backend.py` 的注入式合成 runtime；只验证版本、RGBA、裁切与 animation/skin 透传 |
| 版本不匹配/无 runtime 回退 | `READY_OFFLINE` | 同测试确认不调用 FakeRuntime，返回 `None` 交给 FB/fallback |
| bundle 下载、白名单、原子缓存 | `READY_OFFLINE` | 同测试 mock 公开 raw URL，验证三类文件写入和越界 URL 拒绝 |
| 既有队列、预算、预检查 | `READY_OFFLINE` | `tests/test_spine_spike.py`、`tests/test_spine_inspection.py` |
| 角色卡无索引 N+1 | `READY_OFFLINE` | `NikkeDbProvider.resolve_spine_version(..., allow_remote=False)` 与 AssetManager single-flight/请求测试 |
| 真实 runtime 兼容 | `NEEDS_LIVE_EVIDENCE` | 当前没有安装或注入具体 runtime；不能由 FakeRuntime 推出 |
| Linux headless / benchmark | `NEEDS_LIVE_EVIDENCE` | 尚未执行授权环境动作 |
| runtime 与测试素材许可 | `NEEDS_LIVE_EVIDENCE` | 需人工根据采用的具体 runtime 和素材逐项确认；公开代码不等于项目可任意分发 |

## 固定回退顺序

1. 本地明确 override / costume-aware 现有缓存；
2. 版本化 Spine PNG cache hit；
3. 公开 Nikke-DB 静态 FB；
4. 几何 placeholder。

Spine 后台任务完成后只写缓存，不替换已经发送的卡片，也不新增 QQ 发送动作。

## 未执行事项

- 未安装、下载或执行具体 Spine runtime。
- 未访问真实账号、Cookie、私有接口、QQ 或部署环境。
- 未将 NIKKE 动态素材、公开 URL 或合成 PNG 视为已获授权的产品资源。
- 未声称真实角色的 server-side render、Linux 可运行性、吞吐量或生产出图完成。

具体 runtime 选型应以其官方文档和许可证为准；官方 runtime 入口见 [Spine Runtimes](https://us.esotericsoftware.com/spine-runtimes) 与 [spine-runtimes repository](https://github.com/EsotericSoftware/spine-runtimes)。
