# AssetManager 素材请求去重验收

## 范围

- 分支：`feat/asset-request-dedup-v2`
- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 实现提交：`e2d709f`（Draft PR #17 当前 head）
- 用户可见目标：同一素材首次缓存未命中时，并发卡片渲染不会为同一个缓存键重复发起网络请求。

## 实现合同

- `AssetManager` 以 `kind/key.png` 为 single-flight 键；首个调用负责下载，其余调用等待同一完成事件后重新读取缓存。
- 等待者不自行重试或发起第二个请求；下载失败仍沿用原有 300 秒失败冷却和占位图 fallback。
- owner 下载成功但原子缓存写入失败时，等待者复用同一内存图片结果，不因缓存缺失误降级或重复请求。
- 保留原有 HTTPS、大小、像素、总时限和原子缓存写入限制。
- 该增量只证明同一缓存键的并发请求去重，不把合成 HTTP 测试冒充公开资源现场访问、真实账号联调、资源授权或所有产品路径的全局 N+1 证明。

## 行为验证

```text
pytest tests/test_asset_manager.py tests/test_character_card_renderer.py tests/test_campaign_history.py
36 passed
```

新增行为测试使用模拟响应和 5 个并发调用，断言 `httpx.stream` 只调用 1 次，并且所有调用均拿到同一图片尺寸；另验证缓存写入失败时等待者仍复用内存结果。未访问真实账号、未发送消息、未下载公开资源。

另有并发不同资源键边界测试，确认 `fire` 与 `water` 不会错误共享 single-flight 状态，仍分别发起 2 次请求并保留各自素材。

当前本机 Python 3.10.11：目标测试 `36 passed`；全量 pytest `259 passed、43 subtests、2 warnings`；Node 扩展测试 3 passed，compileall 与 `git diff --check` 通过。GitHub Actions 仍需以本次最终 head 的新 run 为准；不把合成 HTTP 测试表述为公开资源现场访问。

使用 `remote=False` 的脱敏 fixture 生成并实际查看了角色卡合成预览：`E:\DevCache\nikke-asset-dedup-preview-20260907-v3\red-hood.png`、`alice.png`、`fallback.png`。预览验证出图闭环与素材缺失 fallback，不证明真实资源可访问。

## 未覆盖/交接

- 仍只证明同一缓存键的并发请求去重，不证明所有产品路径的全局 N+1 消除。
- 不包含 Spine production runtime、真实资源许可或部署变更。
