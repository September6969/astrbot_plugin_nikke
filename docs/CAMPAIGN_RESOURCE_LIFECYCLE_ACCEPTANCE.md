# Campaign History 资源生命周期验收

基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 本次变更

- `NikkePlugin` 已将 Campaign History renderer 接到插件已有的共享 `AssetManager`。
- Campaign History 不再在默认构造路径中额外创建自己的缓存目录、数据库 provider 和线程池。
- 插件关闭时，既有的统一 `asset_manager.close()` 可覆盖 Campaign History 使用的资源管理器。
- `CampaignHistoryRenderer` 的独立构造默认仍保留，便于离线预览和测试调用。

## 验证

- `tests/test_campaign_resource_wiring.py` 验证 renderer 构造收到同一个共享 manager。
- 合成测试不访问真实账号、不执行账号写操作、不发送消息。
- 本主题只修复资源复用与生命周期接线，不声称增加或减少官方接口请求次数，也不声称完成真实资源联调。
