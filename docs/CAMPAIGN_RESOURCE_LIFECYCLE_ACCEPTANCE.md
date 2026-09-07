# Campaign History 资源生命周期验收

基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 当前验证检查点

- 本地 Python 3.10.11：全量 `pytest -q` → 259 passed、2 warnings、43 subtests passed。
- 资源生命周期与 Campaign 定向测试 → 24 passed、2 warnings。
- `node --test tests\\extension.test.cjs` → 3 passed；`compileall -q .` 与 `git diff --check` 通过。
- 合成共享 AssetManager 预览已实际查看：`E:/DevCache/nikke-campaign-lifecycle-preview-20260907-v2/campaign-ddb348a54ded4ce5ac3d9e468838b25b.png`。
- 本次文档修订前代码检查点为 `a09493b`，对应 CI run `34116765420`；文档提交后的最终 head 与 CI 必须重新查询，不能在此处自引用未来提交。

## 本次变更

- `NikkePlugin` 已将 Campaign History renderer 接到插件已有的共享 `AssetManager`。
- Campaign History 不再在默认构造路径中额外创建自己的缓存目录、数据库 provider 和线程池。
- 插件关闭时，既有的统一 `asset_manager.close()` 可覆盖 Campaign History 使用的资源管理器。
- `CampaignHistoryRenderer` 的独立构造默认仍保留，便于离线预览和测试调用。
- 同一张卡片内相同 `(tid, resource_id)` 的 portrait 资源键只解析一次，避免重复资源检查；不同资源键仍逐项解析。

## 验证

- `tests/test_campaign_resource_wiring.py` 验证 renderer 构造收到同一个共享 manager。
- `tests/test_campaign_resource_wiring.py` 验证同一张合成卡片内重复 portrait 键只调用一次资源管理器。
- `tests/test_campaign_resource_wiring.py` 验证不同 `(tid, resource_id)` 键不会被错误合并。
- 合成测试不访问真实账号、不执行账号写操作、不发送消息。
- 本主题只修复资源复用与生命周期接线，不声称增加或减少官方接口请求次数，也不声称完成真实资源联调。
