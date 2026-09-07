# Announcement V2 Increment A 合同

## 范围与边界

本增量只完善公开公告的查询、受限重扫和可诊断的本地状态：

- `deep rescan`、locale、category、query UX 与只读 diagnostic；
- 有界的公告缓存与既有投递基线状态；
- 旧文更新、版本、重订阅与乱序的明确语义。

它不新增账号请求、真实消息发送、自动开启推送、第三方正文抓取或未证实的 CMS 分类 endpoint。InformationFeeds 的公开匿名读取仍使用已记录的 `official_news` 栏目；`category` 是本地已知字段筛选，不推断官网栏目或正文分类。

## 查询与重扫

| 操作 | 合同 |
| --- | --- |
| 常规同步 | 默认英文，最多 2 页、每页 5 条；InformationFeeds 不可用时才尝试既有 BlaBlaLink 只读回退；两者失败保留缓存。 |
| 深度重扫 | 仅管理员触发的公开只读操作；仅接受 InformationFeeds 成功结果，最多 5 页、每页 20 条（上限 100 条）。失败保留缓存，不以旧回退源冒充完整重扫；不会发送消息或修改订阅。 |
| locale | 仅 `en`、`ja`、`ko`、`th`、`de`、`fr` 和缓存迁移值 `und`；不把任意语言代码传给官网。 |
| category | 只做 `AnnouncementRecord.category` 的精确本地过滤；未知或未分类记录保持 `general`。 |
| query | 对本地标题/正文作受长度限制的大小写无关查询；不触发网络。 |
| diagnostic | 只输出同步范围、缓存数量、locale/category 计数、保留策略与顺序证据等级；不输出账号、订阅 target、Cookie 或正文。 |

## 有界状态与投递基线

- 公告缓存保留期为 90 天；只能移除具有可解析时区的过期公告，仍有未结束日程或时间未知的记录保留。
- 投递成功记录也默认保留 90 天；清理后把成功版本压缩到每目标的 `baseline` 水位，防止同一旧版本因重扫再次投递。
- 首次订阅和重新订阅都以当时可见版本建立 baseline，不回放旧公告或已错过的截止提醒。
- 已订阅目标仍可接收其 baseline 之后的版本升级，即使原公告的 `published_at` 已超过查询/重扫窗口。
- 这是 **best-effort de-duplication**：发送成功到落盘前进程崩溃仍可能导致重复，不能称 exactly-once。

## ID、版本与乱序

- 缺少稳定 `content_id` 的记录拒绝入库；不得以 `"None"` 或内容猜 ID。
- `content_version` 比较 title、正文、category、locale 的内容指纹；日程变化单独决定 `deadline_version`。
- InformationFeeds 已确认 `pub_timestamp`，但未确认公告修改时间或单调 revision。它只能表达发布时间，不能作为更新顺序。
- 每个公告保留最多 8 个已见内容指纹。已见的旧指纹在更新后再次出现时视为乱序回放并忽略，不回滚版本或日程。
- 从未见过的不同指纹按成功扫描到达顺序成为新版本，diagnostic 必须标记 `source_order: unknown`。这不是对官网修改时序的声明。

## 行为验收

至少覆盖深度重扫范围/报告、locale/category/query、重复 fetch、旧文升版、乱序回放、清理后重扫、进程重启、重新订阅和无消息发送的 diagnostic。
