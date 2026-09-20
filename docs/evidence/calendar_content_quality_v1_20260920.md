# Calendar Content Quality v1 验收记录

状态：`READY_OFFLINE`（共享解析、分类、相关性、身份合并和官方截止日期过滤已完成；真实 GameKee 仅做公开只读统计，未部署、未访问真实账号、未发送 QQ 消息）

基线：`origin/feat/calendar-pixel-contract-v1@ecc5495`。该分支保留已验收的 Calendar 像素契约，内容质量改动独立于 UI。

工作分支：`feat/calendar-content-quality-v1`

## Architecture

数据路径固定为：

```text
GameKee raw row
  -> gamekee_parser.parse_gamekee_row
  -> ParsedGameKeeActivity / ParseFailure
  -> CanonicalEvent + FieldEvidence + metadata
  -> identity score / field arbitration
  -> display relevance and stable Operations Feed ordering
```

Canonical dataset 保留全部合法事件。`DisplayTier` 只影响展示排序，不改变 `EventStatus`、LKG、Freshness、Coverage 或 Reminder 语义。

## Parser

- `features/calendar/gamekee_parser.py` 是唯一共享 GameKee row parser。
- ID、标题、`begin_at/end_at` 与兼容字段统一读取；非法时间和 `end_at <= start_at` 返回稳定失败桶。
- `http/https` URL 才允许进入视觉候选；`javascript/data/file`、空值、无 host、带凭据 URL 拒绝。
- `image_list` 递归深度上限为 5，候选上限为 12；`big_picture -> image_list -> picture` 去重并保持顺序。
- `sources.py` 与 `schedule_adapters.py` 均复用共享 parser；未保留第二套 GameKee 字段解析逻辑。
- CanonicalEvent 以向后兼容的 `metadata` 保存 description、tag、activity_kind、importance、key visual 和候选图；旧缓存缺少 metadata 时载入阶段补算相关性。

## Category

分类权重集中在 `content_quality.py`：title `+100`、tag `+70`、activity kind `+70`、description `+20`。已覆盖 coop、solo raid、union raid、special arena、recruit、double reward、maintenance、update、pass 别名。描述中的 `updated rewards` 不会单独触发 `update`。

## Relevance

`RelevancePolicy` 固定基础分与阈值：`>=55 CORE`、`>=30 SUPPORTING`、其余 `META`。精确起止、GameKee 主源、官方证据、视觉候选和 importance 有明确加分；“available after maintenance”、礼包/套餐类描述有降权。英文或标题较长本身不降权。

ACTIVE 按结束紧迫度优先，随后 tier/score；UPCOMING 按 tier/score/start/id。META 不从 canonical dataset 删除，只排到 feed 后段。

## Identity

`score_identity()` 使用 MATCH `>=75`、AMBIGUOUS `50–74`、DISTINCT `<50`。覆盖同源显式 ID、cycle、detail URL、类别、标题归一化和起止时间证据；区服/cycle 冲突、同源不同 ID 和不重叠区间按 fail-closed 处理。AMBIGUOUS 不自动合并，保留独立事件并写入 debug metadata/telemetry，不冒充已确认合并。

## Official

`should_parse_deadlines(title, body)` 要求时间关键词与日期/时间形态同时出现，普通公告不会启动正文 DeadlineParser。MATCH 的官方截止日期进入现有 FieldEvidence 仲裁；DISTINCT 才计为新建官方事件；AMBIGUOUS 保留为待证据的独立记录。

## Telemetry

刷新摘要只记录计数，不记录完整 payload、header 或秘密：

`gamekee_rows/gamekee_valid/gamekee_malformed/gamekee_duplicates/with_visual/canonical_total/identity_matches/identity_ambiguous/identity_distinct/official_deadlines_seen/official_deadlines_filtered/official_deadlines_parsed/official_enriched_existing/official_created_new/relevance_core/relevance_supporting/relevance_meta/display_selected/display_deprioritized`。

### Public GameKee read-only diagnostic

2026-09-20 本次本机公开只读请求结果：

- outcome：`SUCCESS_DATA`
- rows：`123`
- valid：`123`
- malformed：`0`
- duplicates：`0`
- with_visual：`123`
- category counts：event `95`、pass `20`、recruit `7`、double_reward `1`
- 抽样标题：`COIN RUSH SHOWDOWN`、`LET'S DRINK PASS`、`Trail Marker`、`SIN EDITOR`

这是公开源统计，不是账号数据、QQ 送达、部署或资源授权证据。

## Before / after

- Before：两个 GameKee 解析入口各自解析字段，CanonicalEvent 丢失描述/标签/视觉候选，分类仅覆盖部分别名，Operations Feed 按时间排序。
- After：共享 parser + bounded visual scan + weighted category classifier；CanonicalEvent 保留内容元数据；身份合并保守评分；Feed 使用可解释 tier/score 排序且保留 META。
- UI 像素合同未改动，继续使用 `docs/evidence/calendar_pixel_contract_v1_20260920.md` 中的既有预览与 DOM 证据。

## Tests

本轮已执行：

- `python -m pytest -q tests/test_calendar_content_quality.py`：13 passed。
- `python -m pytest -q tests/test_calendar_v04.py tests/test_calendar_v05.py tests/test_schedule_data_layer.py tests/test_calendar_p0_semantics.py`：66 passed，1 warning。
- 共享 parser 的 999 行性能测试通过，离线运行低于 5 秒门槛。
- `python -m py_compile` 覆盖本轮 7 个 Python 改动文件：通过。
- 最终唯一完整回归 `python -m pytest -q`：`1031 passed, 2 skipped, 653 subtests passed, 1 warning`，耗时 `127.53s`。
- 最终 `python -m compileall -q .`：通过；`node --check extension/background.js` 与 `node --check extension/popup.js`：通过。
- `git diff --check`：通过（仅 Windows 换行提示）。

本轮没有重复执行完整回归；GitHub CI 仍需在远端分支上完成跨版本验证。

## Verdict

P0 内容质量主链为 `READY_OFFLINE`。真实公开源可达且结构统计正常；真实账号、QQ、部署、运营后台和资源权利方证据不属于本轮，不声明为已完成。当前剩余工作是 review、远端 CI 和按用户决定的 PR 交接，不自动合并或部署。
