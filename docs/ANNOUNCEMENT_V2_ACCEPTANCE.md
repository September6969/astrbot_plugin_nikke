# Announcement V2 Increment A 验收记录

## 主题与边界

- 用户入口：`/妮姬 公告`
- 独立分支：`feat/announcement-v2`
- 起始 base：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 范围：公开公告的有界重扫、locale/category/query、只读诊断、缓存与版本语义。

本增量没有访问真实账号、没有执行账号写操作、没有发送消息，也没有实际调用公开 CMS。公开读取适配器只由合成 transport/fixture 覆盖；这不是产品环境或真实资源授权的证据。

## 已完成行为

- 常规同步为最多 2 页 x 5 条；管理员 `深度刷新 [语言]` 为最多 5 页 x 20 条，只读且不改订阅或发送消息。
- 深度重扫只有 InformationFeeds 成功时才报告成功；不能用 BlaBlaLink 回退源冒充完整范围。常规同步才允许回退。
- 支持 `en`、`ja`、`ko`、`th`、`de`、`fr`，缓存迁移值为 `und`；分类只在本地精确过滤，`活动`、`维护` 等中文别名映射为既有本地标识。
- 查询、分类、语言过滤与诊断均只读本地缓存，不发网络请求；诊断不含正文、订阅 target 或凭据。
- 缓存只清理可证明过期且不含进行中日程的公告；投递基线保留旧版本水位，重订阅不回放，旧文新版本仍可投递。
- 缓存记录新增本地维护时间 `last_changed_at`：首次入库和新内容指纹写入当前 UTC 时间；重复 fetch 与已见旧指纹回放都不刷新。清理同时要求 `published_at` 与 `last_changed_at` 都超过 90 天，且没有活动日程；因此发布时间很早但刚更新的旧公告不会被立即删除。
- `sync_from_source()` 成功完成后自动执行有界缓存清理；旧缓存缺少 `last_changed_at` 时从迁移时刻安全初始化并落盘，无法解析的时间仍保留，不作危险删除。
- 内容指纹覆盖 title、正文、category、locale；已见旧指纹重放不会回滚新版本或日程。未见新指纹仅按到达顺序升级，并把来源顺序标记为 unknown。
- 修复既有 BlaBlaLink 回退循环缩进：多条公开记录不再只保留最后一条。

## 测试与预览

本轮在隔离 Python 3.12 环境执行了主题回归：

```text
python -m compileall -q .                                      PASS
pytest tests/test_announcement_cache_lifecycle.py              10 passed
pytest tests/test_announcement_v2.py (核心回归)                 16 passed, 2 deselected
pytest tests/test_announcements.py                              15 passed, 24 subtests
node --test tests/extension.test.cjs                            3 passed
git diff --check                                                PASS
```

新增 `tests/test_announcement_v2.py` 覆盖：深度范围/语言、来源上限、回退多条记录、重复 fetch、旧指纹乱序、清理后重扫、重启、locale/category/query/diagnostic、管理员鉴权、重订阅基线及投递清理；新增 `tests/test_announcement_cache_lifecycle.py` 覆盖自动清理、旧文新版本、活动日程保护、异常时间、旧缓存迁移、重启保持、重复 fetch、旧指纹回放和新指纹刷新（10 项行为测试）。

实际查看的合成文本预览（未网络请求）显示：语言和分类筛选会显示 `（筛选: 语言=ja · 分类=maintenance）` 与唯一的维护公告；诊断只显示缓存数量、范围、locale/category 聚合和 90 天保留策略，无正文/target/凭据。

## 当前交接状态

- [PR #9](https://github.com/September6969/astrbot_plugin_nikke/pull/9) 仍为 Draft，当前实施提交为 `ea66f16a79d2538556355c6317f1fa67a2151585`。
- 当前 [CI run 34095605055](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34095605055) 的 headSha 与该提交一致，Extension (Node) 及 Python 3.10/3.11/3.12 均 SUCCESS。后续再提交文档时必须重新等待新 head 的 CI。
- `NEEDS_LIVE_EVIDENCE`：获授权时才可验证公开 CMS 当前响应和真实 AstrBot 运行环境；本次不执行。
- `HARD_BLOCKED`：无。
