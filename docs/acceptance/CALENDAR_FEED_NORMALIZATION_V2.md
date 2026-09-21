# Calendar Operations Feed v2 验收记录

## 范围与基线

- 主题分支：`feat/calendar-feed-normalization-v2`
- 基线：`origin/main@d79650ae442c7c31e740b281e1332da640b31409`
- 仅修改 Calendar 内容质量、身份合并、Operations Feed 展示排序及其行为测试；未修改 Character Card、Spine、Tarot、Raid、Profile、Signin、Voice、Daily/CDK、QQ/NapCat、部署或 `canonical_models.active_sort_key`。
- 当前证据均为离线/公开只读或合成预览，不代表真实账号、QQ 送达、部署或资源授权。

## 实时数据诊断

2026-09-21 通过现有 `GameKeeScheduleAdapter` 对公开 `activity/page-list` 执行一次只读抓取：`SUCCESS_DATA`，rows `123`、valid `123`、malformed `0`、duplicates `0`、visual `123`。适配器只使用一次请求，不为单条活动追加请求。

实际字段合同为 `id/title/begin_at/end_at/description/tag/activity_kind_name/link_url` 加图片字段；当前公开行的 `tag` 与 `activity_kind_name` 多为空，因此分类证据以明确标题优先、再看结构化字段和描述。选定样本：

| source_id | 标题 | 原始辅助字段 | 分类 | 时间/详情 |
| --- | --- | --- | --- | --- |
| 7828 | `【活动PASS】LET'S DRINK PASS` | tag/kind 为空；描述含 PASS | `pass` | 2026-09-16T16:00Z → 2026-10-07T16:00Z；GameKee 721020 |
| 7827 | `【转盘】KILLER BUNNY` | tag/kind 为空；描述含时装抽取 | `costume_gacha` | 同上；GameKee 721020 |
| 7639 | `【限时通关】Trail Marker` | tag/kind 为空；描述含限时通关 | `limited_stage` | 2026-08-12T16:00Z → 2026-10-07T20:59Z；GameKee 716193 |

当前公开快照的分类计数：`event 76`、`pass 20`、`costume_gacha 18`、`recruit 6`、`double_reward 1`、`mini_game 1`、`limited_stage 1`。指定英文样例未出现在该快照，已用离线行为测试覆盖，未把样例冒充实时行。

## 实现结果

1. 新增 `classify_explicit_title()`，明确标题语义优先于错误的 tag/activity_kind/description；增加 `mini_game`、`limited_stage`、`costume_gacha`、`limited_costume`、`announcement`、`package` 等分类。
2. 新增 `canonical_event_title()` 与 `canonical_identity_match()`。只在 canonical title 完全相同、分类族兼容、起止时间均在 10 分钟容差内、server scope/cycle/source ID 无冲突时合并；证据写入 `identity_match`，不削弱原有 `score_identity()` / `strong_identity_gate`。
3. 对 `SSR Anne`/`SSR Mica`、不同限定时装角色等明确身份冲突增加 fail-closed 保护，即使详情页被复用也不跨角色合并。
4. 新增独立 `operations_display_group` 与 `sort_operations_display_events`：活动族 → 招募 → 转盘时装 → 限定时装 → META；ACTIVE 组内为 EXACT 结束时间、DATE_ONLY、UNKNOWN、相关性、稳定身份，UPCOMING 组内为开始时间、稳定身份。
5. 服务文本查询、旧分组接口和 Calendar T2I payload 共用新排序；`resolve_next_ending()` 和 `canonical_models.active_sort_key` 保持未改。
6. `CAT_LABELS` 补齐全部新分类，META 仍保留在 canonical/feed 数据集，不静默丢弃。

## 预览与视觉验收

公开数据预览（非账号数据）实际输出：

- [公开快照 page-1.png](E:/DevCache/nikke-calendar-feed-v2-preview-20260921/page-1.png)，1600×900，SHA-256 `6A5FE426D60CA50FFEA3183DD83AE6EB9DED779D4596CFC93315B3C46CE4100B`。
- [公开快照诊断](E:/DevCache/nikke-calendar-feed-v2-preview-20260921/diagnostic.json)，记录源计数和选定行。

分页为独立合成证据，明确不代表实时源：

- [合成 page-1.png](E:/DevCache/nikke-calendar-feed-v2-preview-20260921/synthetic-page-1.png)，1600×1516，SHA-256 `8CE01FE95D6A87E877E8F29C126F4E97CA6386838C42ED1A47311F4606C73A74`。
- [合成 page-2.png](E:/DevCache/nikke-calendar-feed-v2-preview-20260921/synthetic-page-2.png)，1600×1114，SHA-256 `1D5082F75014DD1D890547F506C139D36F1783061C8FCAB485EF2EBEE7D02AB9`。
- [合成分页诊断](E:/DevCache/nikke-calendar-feed-v2-preview-20260921/synthetic-diagnostic.json)，标记 `synthetic_preview: true`、24 条活动、2 页。

已逐张查看公开 page-1、合成 page-1/page-2：标题/分类标签可读，无溢出；活动族先显示，招募随后，转盘/限定时装之后，维护等 META 位于最后；`NEXT ENDING` 在公开页命中最早精确结束项。公开快照当前只有一页，故第二页只能以明确标记的合成分页证据验收。

## 测试与状态

本轮已完成的定向测试：

- Content quality + canonical identity + display sort：`26 passed`。
- Schedule data layer + P0 semantics：`39 passed`。
- Calendar UI/v04/v05/T2I visual/frontend：`115 passed`。
- 定向合计：`180 passed`，另有既有依赖弃用 warning。

最终 `compileall` 与 `git diff --check` 已通过。最终 full pytest 已按规则只执行一次：`1117 passed, 2 skipped, 648 subtests passed, 16 failed`。16 项全部属于既有 Raid/阵容资产 resolver（Boss 11 项、Lineup 5 项），原因是本次干净验证 checkout 从其父目录启动，既有 resolver 使用相对路径 `data/nikke/blabla-assets`，因此没有命中 checkout 内的已跟踪素材；Calendar 定向套件没有失败。没有为此重复 full pytest。

Draft PR #99 的 GitHub CI run `35640293133` 已全绿：Node、Spine 4.0、Python 3.10、3.11、3.12、3.13 全部通过。

当前分支尚未合并 main、未部署、未发送 QQ 消息；上述 full pytest 环境问题已作为明确交接项保留，不把本地失败伪报为全绿。

## 变更文件

- `features/calendar/content_quality.py`
- `features/calendar/schedule_service.py`
- `ui/t2i_payloads.py`
- `tests/test_calendar_content_quality.py`
- `tests/test_calendar_operations_display_v2.py`
- 本验收文档与对应 evidence ledger/index 更新
