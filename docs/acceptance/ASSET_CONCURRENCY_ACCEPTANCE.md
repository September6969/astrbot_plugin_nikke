# AssetManager 远端资源并发验收

## 范围

- 仅限制 `AssetManager` 的公共 HTTPS 素材下载。
- 限额跨 `AssetManager` 实例共享，默认最多四个不同缓存键同时下载。
- 本地缓存与项目内置资源不占用下载名额。
- 限额已满时立即返回调用方既有占位图路径，不排队、不写入五分钟失败冷却。

## 离线验收

- 两个独立实例、两个不同键的合成 HTTPS 请求在单槽测试中只允许第一个进入请求上下文。
- 第二个请求在 0.2 秒内降级，且其缓存键不进入 `_failed`。
- 缓存命中即使全局下载槽已占满也能正常解码，且不调用 HTTP 客户端。
- 请求异常后释放全局下载槽，后续不同键仍可获得名额；失败键只记录既有冷却。
- 所有测试通过模拟 `httpx.stream` 执行；没有访问远端素材、账号或消息通道。

当前本机 Python 3.10.11：`tests/test_asset_manager.py` 13 passed；全量 pytest 259 passed、43 subtests、2 warnings；Node 扩展测试 3 passed，compileall 与 `git diff --check` 通过。

使用 `remote=False` 的脱敏 fixture 生成并实际查看了角色卡合成预览：`E:\DevCache\nikke-asset-global-preview-20260907-v2\red-hood.png`、`alice.png`、`fallback.png`。这只验证离线出图与 fallback，不代表真实 CDN 可访问。

## 未覆盖的边界

- 本变更不合并或替代 Draft PR #17 的同键 single-flight。
- 本变更不限制 Pillow 渲染、Spine 队列或其它后台任务；`A-ASSET-08` 的超时后线程生命周期债仍待独立治理。
- 未取得真实 CDN 性能、资源授权或生产多群负载证据。
