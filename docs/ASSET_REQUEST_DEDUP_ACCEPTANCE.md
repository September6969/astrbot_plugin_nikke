# AssetManager 素材请求去重验收

## 范围

- 分支：`feat/asset-request-dedup-v2`
- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 实现提交：`b8a44b9`（Draft PR #17）
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
34 passed
```

新增行为测试使用模拟响应和 5 个并发调用，断言 `httpx.stream` 只调用 1 次，并且所有调用均拿到同一图片尺寸；另验证缓存写入失败时等待者仍复用内存结果。未访问真实账号、未发送消息、未下载公开资源。

GitHub Actions final-head CI：run `34096636216`，Node、Python 3.10、3.11、3.12 全部通过。Windows 本机全量 pytest 曾得到 `238 passed, 31 failed`；失败集中在既有 AstrBot/SQLite 临时目录清理的 `WinError 32` 文件占用，未出现在本增量的目标测试中，因此以隔离环境 CI 作为全量回归证据。

## 未覆盖/交接

- 仍只证明同一缓存键的并发请求去重，不证明所有产品路径的全局 N+1 消除。
- 不包含 Spine production runtime、真实资源许可或部署变更。
