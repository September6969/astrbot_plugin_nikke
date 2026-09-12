# Profile Dashboard v0.4 与本地 Spine 实现记录

## 范围与状态

本文件记录 `fix/live-runtime-v03` 上本次实现的离线合同、代码边界和验证结果。
最终交接状态最多为 `READY_FOR_RETEST`：合成 fixture、离线渲染和服务器只读检查不能代替用户 QQ 客户端验收。

本次不改变 Daily/CDK 的执行语义，不在 Profile 卡中执行写请求，也不把真实账号、Cookie、Token、OpenID、QQ ID 或私有 header 写入仓库。

## Profile v0.4 数据源

- `GetUserProfileBasicInfo`：基础资料、主线、`currencies` 与 Overclock 分数。
- `GetUserProfileOutpostInfo`：同步器、前哨、循环室和遗失物统计。
- `GetUserCharacters`：花名册统计。
- `GetUserDailyContentsProgress`：`data.daily_progress[0]` 中的每日内容进度。

四路读取由 `BlaBlaClient.get_profile_dashboard()` 并发发起；基础资料是必需数据，其余接口各自降级为独立不可用状态，仍允许卡片生成。

## Daily API contract

Daily builder 保留来源语义：

- `outpost_battle_storage_fullness` 保存原始比例，展示时使用 `raw * 100` 并限制在 `0..100`。
- `intercept_remaining_tickets`、`counsel_remaining_count`、`rookie_arena_remaining_count`、`special_arena_remaining_count` 均是 remaining，不改名为 completed。
- `dispatch_completed_count` 与 `dispatch_in_progress_count` 分开保留。
- `tower_daily_info_list` 进入结构化模型并保留每项完整字段，renderer 只读取已解析摘要，界面标签固定为“无尽塔”。
- `sim_room_daily_best_record` 进入结构化模型；chapter 1/2/3 展示 A/B/C，因此 `{chapter: 3, difficulty: 5}` 为 `5-C`。
- Overclock 的当前/最新赛季最高分来自 `basic_info`，不是 Daily 响应。

## Currency 与 Memorial mapping

`CurrencyRegistry` 只登记已确认类型：99 珠宝、1000 战斗数据辑、2000 信用点、3000 芯尘、5100 普通招募券、5200 高级招募券、11000 躯体标签、12000 黄金积分券。`CurrencyItem` 同时保留整数 `value` 与 `compact_value`；compact formatter 使用项目已有 K/M/B 规则，底层数值不改写。未登记的 type 98 保留在底层审计数据，但按用户要求不放上卡面，不猜名称或图标。

`MemorialCategoryRegistry` 按类别 key 映射四个最终格位：`HandWriting`→手机、`CallLog`→通话记录、已验证的 `Data`/`OldTales`/`UnbreakableSphere` 数据组→数据资料，`jukebox_count`→BGM。未知 key 不按数组顺序归类，进入诊断并在 UI 中保持未知安全状态；遗落传说和奇迹之球不单独成格。

## UI layout

Profile 卡保持 Astra dark style、宽度 1200px，正常高度目标 1500–1800px，异常上限 2200px。顺序为 HEADER、BASIC/CAMPAIGN、TODAY、OUTPOST、ROSTER、RECYCLE ROOM、COLLECTION、RESOURCES、MORE。普通未完成字段使用 muted，真正异常使用 warning/error；容量无效时不绘制负宽度。

循环室保持两列，`General/Attacker/Defender/Supporter/Elysion/Missilis/Tetra/Pilgrim/Abnormal` 分别显示为通用研究、火力型、防御型、辅助型、极乐净土、米西里斯、泰特拉、朝圣者、反常；EXP 为 0 时只显示 `Lv.X`。

## Local Nikke-db architecture

维护路径使用本地 Nikke-db checkout：

`vendor/nikke-db` → `LocalSpineBundleResolver` → 读取真实 skeleton 版本 → 4.0/4.1 对应 worker → idle@t=0 → RGBA crop + 16px padding → 持久化 PNG 与 manifest。

checkout 使用 blobless、no-checkout、非 cone sparse 规则，只取目标 `/l2d/<canonical>/` 中实际需要的 `.skel`、`.atlas`、纹理页。Resolver 采用 UTF-8-SIG atlas、受限路径和唯一命名合同；无法唯一选择 bundle 或缺纹理时显式失败。

## Spine hot path / maintenance path

生产 `get_character_portrait()` 只按已验证 `resource/costume → canonical spine asset → manifest/PNG → Pillow` 读取本地文件，禁止 HTTP、Git、Worker、动态队列和 FB 回退。manifest 没有 entry 时按兼容策略处理；一旦 entry 存在，路径、PNG、解码和 SHA-256 失效即记录 `STATIC_SPINE_ASSET_INVALID` 并立即返回，由 UI 使用抽象占位图，不再读取旧 Spine cache；未声明 entry 的缺失仍记录 `STATIC_SPINE_ASSET_MISSING`。占位图不计为成功立绘。

维护脚本 `scripts/update_nikke_db.sh` 与 `scripts/sync_spine_assets.py` 仅由人工维护期调用，不配置 cron，也不从 QQ 命令调用。

## Manifest v2 与 coverage

manifest 每项包含 asset、source repo/commit、runtime version、相对 bundle 路径、纹理数量、animation、PNG 尺寸、alpha bbox、SHA-256 和更新时间；顶层包含 source commit、目标计数、成功/失败/缺失计数。完整 PNG 留在服务器持久化目录，Git 只保留代码、最小 fixture 和 schema 证据。

coverage 报告分别统计 character master、default、verified costume、unique targets、bundle found/missing、4.0/4.1、render success/fail/missing 及失败 ID，不以少量示例角色代替全量覆盖率。

仓库中原有的 `assets/spine_manifest.json` 是历史 v1 离线兼容夹具；本次维护脚本输出并校验 v2，未把没有本地 bundle source commit 的历史夹具升级成虚假的来源证据。生产目录必须使用维护期生成的 v2 manifest。

## Deployment / rollback boundary

本次代码只更新现有 PR 分支；部署和真实 QQ 发送不属于本次自动动作。服务器维护时使用 `/opt/nikke-bot/astrbot/data/vendor/nikke-db`、`nikke/spine-rendered` 和 `nikke/spine-manifest.json`，并先检查磁盘与已有备份。回滚使用已存在的 Git 提交和既有持久化 PNG/manifest，禁止删除分支、覆盖账号数据库或修改 ruleset。

## Tests

定向覆盖 Daily、容量比例、模拟室、Currency、Memorial、循环室、partial failure、local resolver、路径/atlas/纹理/版本、manifest、hot path zero-network，以及 Campaign capture 的 resume/privacy/rate-limit/TID/Costume/snapshot replay。交接前运行完整 pytest、compileall、Node extension tests、`git diff --check`，并区分离线合成证据与现场证据。

## 2026-09-12 接管续作现场记录

- 当前分支 `fix/live-runtime-v03` 的完整 Profile 图标代码提交为 `be7e2ce`；PR #79 保持 OPEN、非 Draft，未修改 main、未合并、未部署。
- Profile v0.4 现代数据路径将 BASIC/CAMPAIGN、OUTPOST/ROSTER 并列，TODAY 使用紧凑多列，COLLECTION 为四格，RESOURCES 为 4×2，RECYCLE ROOM 为双列。合成 after 为 `1200×1619`，原图、50% 和 30% 预览已实际查看；12 个 warmup 后样本 median `126.2293 ms`、p95 `134.312 ms`。
- `serv` 只读 shape 核验确认 `tower_daily_info_list` 元素字段为 `type`、`is_opened`、`remaining_count`；当前只统计开放条目，未发现可靠 total 时不生成 `0/3`。
- `CurrencyRegistry` 的 8 项已知资源均有核验图标：信用点、战斗数据辑、芯尘来自 Nikke-db 固定提交；珠宝、两类招募券、躯体标签、黄金积分券来自用户提供图标及同日数量对照图。每项记录 SHA-256，AssetManager 的 `get_currency_icon()` 不联网、不读取未经 registry 证明的图标。
- `serv` 授权账号只读 Profile 已在隔离代码目录实渲染并脱敏查看：`1200×1715`，底层 9 项实际资源、4 项塔信息；卡面只放 8 项已知资源，图标缩放、透明边缘和文字避让正常。外部证据图为 `E:/DevCache/nikke-live-runtime-v03-artifacts/profile-v04/live-profile-v04-known-currency.png`，SHA-256 `ea09d416f57f2cef3c235833c3a3cc0969f01786c2e651ddd2491ce707037f30`，不提交仓库。
- `serv` 隔离 Nikke-db 维护已按两阶段 sparse 规则完成：source commit `a2358b72bd1335c30737e46482a99947f3788bc7`，240 bundles found，runtime 4.0/4.1 为 102/138，渲染成功 2、失败 238、无效 0、缺失 0。失败是缺少可执行匹配 Spine worker/runtime，属于 `PARTIAL`，不是产品完成证据。
- Campaign NORMAL Chapter 1 只读 smoke 为 4/4 `UNAVAILABLE`，full NORMAL→HARD 抓取已在服务器后台运行，快照不进仓库；最终统计以服务器脱敏 manifest 为准。
