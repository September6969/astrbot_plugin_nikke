# NIKKE 长期路线台账

更新时间：2026-09-07。当前基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 已合并

| 主题 | 状态 | 证据 |
| --- | --- | --- |
| Post-Merge Sync | DONE | PR #6 已合并 |
| Profile V2 | DONE | PR #7 已合并 |
| Raid contract/evidence hardening | DONE on main | `8afacc4`、`b964f18`、`26e9e10`；相关行为测试通过 |

## 独立 Draft PR

| PR | 分支 | 主题 | 当前状态 |
| --- | --- | --- | --- |
| #8 | `feat/union-raid-v2` | Union Raid Increment A | OPEN / Draft / CI green；head `c4a6fe4`；CI `34120205125` |
| #9 | `feat/announcement-v2` | Announcement Increment A + cache lifecycle P1 | OPEN / Draft / CI green；head `6cb544b`；CI `34147704300` |
| #10 | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | OPEN / Draft / CI green；head `528fcdf`；CI `34148538180` |
| #11 | `feat/character-data-v2` | Character Data V2 Increment A | OPEN / Draft / CI green；head `80f3087`；CI `34149471006` |
| #12 | `feat/spine-spike-v2` | Spine technical spike | OPEN / Draft / CI green；head `e5b9efc`；CI `34149003554` |
| #13 | `feat/voice-mapping-v2` | Voice mapping public research | OPEN / Draft / CI green；head `68138bc`；CI `34115632353` |
| #14 | `feat/roadmap-ledger-v3` | Roadmap status reconciliation | OPEN / Draft；台账与工作树索引已同步；当前 head 与 CI 以 PR #14 最新检查为权威 |
| #15 | `feat/campaign-history-contract-v2` | Campaign History numeric contract | OPEN / Draft / CI green；head `bd7c4dc`；CI `34149977507` |
| #16 | `feat/campaign-resource-lifecycle-v2` | Campaign renderer asset lifecycle | OPEN / Draft / CI green；head `1a70d7d`；CI `34150449419` |
| #17 | `feat/asset-request-dedup-v2` | AssetManager same-key single-flight | OPEN / Draft / CI green；head `28b8dfb`；CI `34156636777` |
| #18 | `feat/daily-evidence-p1` | Daily Evidence sign-in recovery safety | OPEN / Draft / CI green；head `a3de03d`；CI `34162799034` |
| #19 | `feat/storage-connection-lifecycle` | SQLite connection lifecycle + Python 3.13 evidence | OPEN / Draft / CI green；head `ffd96a5`；CI `34145647733` 五项全绿（Node、Python 3.10–3.13） |
| #20 | `feat/runtime-config-hardening` | Runtime configuration and scheduler boundary hardening | OPEN / Draft / CI green；head `6e00c5a`；CI `34163558500` |
| #21 | `feat/plugin-shutdown-lifecycle` | Plugin shutdown lifecycle idempotency | OPEN / Draft / CI green；head `f21cdb1`；CI `34163964573` |
| #22 | `feat/data-backup-hardening` | Offline database and secret.key backup hardening | OPEN / Draft / CI green；head `69fb952`；CI `34164382428` |
| #23 | `feat/health-diagnostics-v1` | Read-only runtime health diagnostics | OPEN / Draft / CI green；head `79340a9`；CI `34164857009` |
| #24 | `feat/storage-migration-v1` | Transactional SQLite schema migration | OPEN / Draft / CI green；head `16c9ac5`；CI `34106285962` |
| #25 | `feat/healthz-readiness-v1` | Healthz storage readiness contract | OPEN / Draft / CI green；head `7e5e928`；CI `34106867556` |
| #26 | `feat/log-privacy-v1` | Plugin log privacy hardening | OPEN / Draft / CI green；head `b1f17a2`；CI `34146296068` 四项全绿（Node、Python 3.10–3.12） |
| #27 | `feat/cache-cleanup-v1` | Safe offline cache cleanup | OPEN / Draft / CI green；head `bb94d18`；CI `34108821103` |
| #28 | `feat/release-metadata-v1` | Release metadata and configuration contract | OPEN / Draft / CI green；head `1f379d6`；CI `34109454981` |
| #29 | `feat/caddy-hardening-v1` | Caddy example privacy hardening | OPEN / Draft / CI green；head `160cb25`；CI `34110061494` |
| #30 | `feat/upgrade-preflight-v1` | Read-only upgrade/rollback preflight | OPEN / Draft / CI green；head `e9bf5eb`；CI `34110890912` |
| #31 | `feat/requirement-evidence-matrix-v1` | Final product review requirement/evidence matrix | OPEN / Draft / CI green；head `369cc98`；CI `34112221252` |
| #32 | `feat/tower-snapshot-contract-v1` | Tower static snapshot contract | OPEN / Draft / CI green；head `eede5ab`；CI `34127584276` |
| #33 | `feat/profile-post-merge-v1` | Post-Profile V2 status reconciliation | OPEN / Draft / CI green；head `8bb9cd5`；CI `34143501124` |
| #34 | `feat/cdk-batch-contract-v1` | CDK batch idempotency contract reconciliation | OPEN / Draft / CI green；head `c0f1e65`；CI `34135996980` |
| #35 | `feat/daily-result-contract-v1` | Structured DailyTaskResult status contract | OPEN / Draft / CI green；head `df7fa7f`；CI `34137301772` |
| #36 | `feat/daily-auto-per-account-v1` | Per-account daily automation preference | OPEN / Draft / CI green；head `0ba8b5d`；CI `34138915642` |
| #37 | `feat/asset-global-concurrency-v1` | AssetManager global remote-download limit | OPEN / Draft / CI green；head `43df09a`；CI `34157041468` |
| #38 | `feat/asset-prefetch-lifecycle-v1` | AssetManager bounded prefetch lifecycle | OPEN / Draft / CI green；head `cd27fb3`；CI `34157376854` |
| #39 | `docs/live-evidence-register-v1` | Authorized live-evidence register | OPEN / Draft / CI green；head `9877fc9`；CI `34142711091` |
| #40 | `feat/astrbot-registration-api-v1` | AstrBot registration API migration | OPEN / Draft / CI green；head `311a41e`；CI `34144460942` |

## 当前推进

| 主题 | 分支 | 基线 | 状态 |
| --- | --- | --- | --- |
| Roadmap status reconciliation | `feat/roadmap-ledger-v3` | `bada0b3` | Draft PR #14；台账与工作树索引已同步；本轮补充 PR #19 的 Python 3.13 证据及 PR #26 的 AstrBot 本地矩阵证据；当前 head 与 CI 以 PR #14 最新检查为权威 |
| Post-Profile V2 status reconciliation | `feat/profile-post-merge-v1` | `bada0b3` | Draft PR #33；在既有 `PROFILE_V2_ACCEPTANCE.md` 合并状态记录之外，同步 `POST_MERGE_STATUS.md` 与 `POST_MERGE_PHASE2_PLAN.md`：当前入口明确 PR #6/#7 已合并、Profile 为 `READY_OFFLINE` 且现场证据仍独立；新增状态入口回归测试；本地专项 1 passed、全量 pytest 257 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；head `8bb9cd5`；CI `34143501124` 四项全绿；不访问真实账号、不部署 |
| CDK batch idempotency contract reconciliation | `feat/cdk-batch-contract-v1` | `bada0b3` | Draft PR #34；确认主命令逐码复用 `action_runs`，run key 为 `cdk:{qq_id}:{game_uid}:{SHA256(code)}`，unknown/终态不自动重放，失败/过期可原子重领；更新 README/DEVELOPMENT_PLAN 并新增验收记录；本地专项 42 passed、12 subtests，全量 pytest 256 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；CI `34135996980` 四项全绿；未访问真实账号、未执行兑换或部署 |
| Structured DailyTaskResult status contract | `feat/daily-result-contract-v1` | `bada0b3` | Draft PR #35；签到主链统一 `SUCCESS`、`ALREADY_DONE`、`PENDING`、`FAILED`、`RATE_LIMITED`、`COOKIE_EXPIRED`、`UNKNOWN_AFTER_ACTION`、`UNAVAILABLE`，持久化改为严格 JSON-safe 记录，旧/损坏记录不静默冒充成功；本地定向 10 passed、全量 pytest 262 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；head `df7fa7f`；CI `34137301772` 四项全绿；不访问真实账号、不执行签到、不发送消息、不部署，Like/Browse 与现场证据仍未完成 |
| Per-account daily automation preference | `feat/daily-auto-per-account-v1` | `bada0b3` | Draft PR #36；新增默认关闭的 `accounts.auto_daily_enabled` 与 `/妮姬 日常 自动 开|关`；定时签到和汇总补跑同时筛选 `push_enabled=1` 与自动偏好，手动签到和管理员显式执行保持原选择语义；本地定向 48 passed、4 subtests，全量 pytest 263 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；head `0ba8b5d`；CI `34138915642` 四项全绿；不访问真实账号、不执行签到、不发送消息、不部署，Like/Browse 与现场调度证据仍未完成 |
| Announcement cache lifecycle P1 | `feat/announcement-v2` | `bada0b3` | Draft PR #9；有界深度重扫、locale/category/query、旧文版本/乱序、`last_changed_at` 自动清理与安全迁移；版本字段严格为正整数，损坏缓存不静默截断；head `6cb544b`；本地主题回归 39 passed、42 subtests，全量 pytest 278 passed、61 subtests、Node 3 passed、compileall/diff check 通过；CI `34147704300` 全绿；未访问真实 CMS、账号或发送消息 |
| Campaign History numeric contract | `feat/campaign-history-contract-v2` | `bada0b3` | Draft PR #15；严格 tid/lv/combat/slot 数值与槽位合同，拒绝空白/带符号数字字符串；非映射响应、缺失/非列表 `data.list`、非五人列表返回 ERROR，明确空列表保持 UNAVAILABLE，并对超长列表提前失败；本地 Python 3.10.11 定向 29 passed、7 subtests，全量 pytest 264 passed、50 subtests、2 warnings，Node 3 passed、compileall/diff check 通过；已实际查看 1400×820 合成 NORMAL 46-40 预览；head `bd7c4dc`；CI `34149977507` 四项全绿；不访问真实账号或宣称真实联调/资源授权 |
| Campaign renderer asset lifecycle | `feat/campaign-resource-lifecycle-v2` | `bada0b3` | Draft PR #16；复用共享 AssetManager；同一张卡片内相同 `(tid, resource_id)` 的 portrait 只解析一次，不同 `(tid, resource_id)` 不错误合并；本地 Python 3.10.11 全量 pytest 259 passed、43 subtests、2 warnings，资源生命周期/Campaign 定向 24 passed、Node 3 passed、compileall/diff check 通过；已实际查看共享 manager 生成的 1400×820 合成 Campaign 预览；head `1a70d7d`；CI `34150449419` 四项全绿；不宣称全局 N+1 已消除或真实资源联调 |
| AssetManager request dedup | `feat/asset-request-dedup-v2` | `bada0b3` | Draft PR #17；同一缓存键 5 个并发调用只发 1 次模拟请求，缓存写入失败时等待者复用内存结果；新增不同键并发边界测试，`fire`/`water` 保持 2 次独立请求；本地 Python 3.10.11 定向 36 passed、全量 pytest 259 passed、43 subtests、2 warnings，Node 3 passed、compileall/diff check 通过；已实际查看 `remote=False` 脱敏角色卡 red-hood/alice/fallback 合成预览；head `28b8dfb`；CI `34156636777` 四项全绿；仍不宣称全局 N+1、真实资源或账号证据 |
| AssetManager global remote-download limit | `feat/asset-global-concurrency-v1` | `bada0b3` | Draft PR #37；公共 HTTPS 素材下载跨 `AssetManager` 实例共享四槽非阻塞限额，缓存命中不占槽；满额立即走既有 fallback，且不写入失败冷却；新增请求异常释放槽行为测试；本地 Python 3.10.11 专项 13 passed、全量 pytest 259 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；已实际查看 `remote=False` 脱敏角色卡 red-hood/alice/fallback 合成预览；head `43df09a`；CI `34157041468` 四项全绿；与 PR #17 同属资源子系统但不替代其同键 single-flight，合并时需协调 `asset_manager.py`；未访问远端素材、账号或消息，也未宣称 Pillow/Spine/生产多群负载证据 |
| AssetManager bounded prefetch lifecycle | `feat/asset-prefetch-lifecycle-v1` | `bada0b3` | Draft PR #38；角色卡预取在每个 `AssetManager` 限为 16 项，满额不提交任务而直接 fallback；预算到期取消尚未启动的 future，已运行线程只能保留底层 I/O timeout 边界；新增正常完成归还槽位测试；本地 Python 3.10.11 专项 13 passed、全量 pytest 259 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；已实际查看 `remote=False` 脱敏角色卡 alice/fallback 合成预览；head `cd27fb3`；CI `34157376854` 四项全绿；与 PR #17/#37 均修改 `asset_manager.py`，合并时需协调；未访问远端素材、账号或消息，也未宣称已强杀运行中线程、Pillow/Spine 或真实多群负载证据 |
| Authorized live-evidence register | `docs/live-evidence-register-v1` | `bada0b3` | Draft PR #39；新增 Profile、Raid、公告、Daily、Voice、Spine 的现场登记，逐项记录本地来源、未决问题、最小授权动作和禁止事项；新增文档合同测试；本地专项 1 passed、全量 pytest 257 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；此前将 Node 测试误记为不存在，已在本分支工作树重新执行 `tests/extension.test.cjs` 并更正；head `9877fc9`；CI `34142711091` 四项全绿；不读取真实账号、不写入、不发送消息、不访问远端资源、不部署，也不把 mock/离线代码描述成现场证据 |
| AstrBot registration API migration | `feat/astrbot-registration-api-v1` | `bada0b3` | Draft PR #40；移除废弃 `register_star` 装饰器，保留 `Star` 自动子类注册，并将仓库地址写入 `metadata.yaml`；新增子进程弃用警告回归测试与验收文档；本地全量 pytest 258 passed、43 subtests、1 个 FAISS/NumPy 依赖 warning、Node 3 passed、compileall/diff check 通过；head `311a41e`；CI `34144460942` 四项全绿；未访问真实账号、未发送消息、未部署，也不宣称生产实例已升级或重载 |
| Daily Evidence sign-in recovery | `feat/daily-evidence-p1` | `bada0b3` | Draft PR #18；intent 先于读取，running/unknown 只读恢复，终态 success/expired/failed 不进入恢复读取或重发，未确认进入 unknown、Cookie 失效进入 expired；执行中取消也将已持有 daily/signin intent 收敛为 unknown 后继续传播取消；本地 Python 3.10.11 专项 11 passed、全量 pytest 262 passed、43 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；head `a3de03d`；CI `34162799034` 四项全绿；不宣称 Like/Browse 或真实账号证据 |
| SQLite connection lifecycle + Python 3.13 evidence | `feat/storage-connection-lifecycle` | `bada0b3` | Draft PR #19；每次存储操作成功提交、异常回滚并明确关闭连接；新增异常回滚/原异常传播/连接关闭行为测试；补充 D-14 Python 3.13 兼容性证据与 CI 矩阵 3.10–3.13；Windows Python 3.13.13 本地全量 pytest 258 passed、43 subtests、1 warning，现有 Python 3.10 环境 258 passed、43 subtests、2 warnings，Node 3 passed、compileall/diff check 通过；修复前同一 3.13 回路为 238 passed/32 failed，失败均为 WinError 32 SQLite 文件句柄；head `ffd96a5`；CI `34145647733` 五项全绿；Python 3.14、真实进程/数据库/账号仍未验证 |
| Runtime config hardening | `feat/runtime-config-hardening` | `bada0b3` | Draft PR #20；非法数值配置和损坏持久化调度字段按合同回退，不让调度循环退出；新增持久化读取 `TypeError`/`ValueError` 按字段隔离回退，避免损坏 JSON 退出调度；本地 Python 3.10.11 专项 3 passed、全量 259 passed、43 subtests、2 warnings，Python 3.13.13 专项 3 passed、1 warning，Node 3 passed、compileall/diff check 通过；head `6e00c5a`；CI `34163558500` 四项全绿；Python 3.13 全量仍受未合并 PR #19 的 WinError 32 句柄问题限制，不宣称 3.13 全量兼容 |
| Plugin shutdown lifecycle | `feat/plugin-shutdown-lifecycle` | `bada0b3` | Draft PR #21；顺序/并发 terminate 只回收一次资源；反馈、素材或 Web 回收异常时仍继续尝试后续资源，重新抛出首个异常且不设置完成标记，后续可重试；本地 Python 3.10.11 专项 5 passed、全量 259 passed、43 subtests、2 warnings，Node 3 passed、compileall/diff check 通过；head `f21cdb1`；CI `34163964573` 四项全绿；无 UI/渲染变化，不宣称现场或生产证据 |
| Data backup hardening | `feat/data-backup-hardening` | `bada0b3` | Draft PR #22；离线备份 `nikke.sqlite3` 与 `secret.key`，SQLite integrity_check、SHA-256 manifest、临时目录落盘和禁止覆盖；输出目录占用、损坏 SQLite 等异常统一为 `BackupError`，备份密钥收紧为 `600`；本地 Python 3.10.11 专项 3 passed、全量 259 passed、43 subtests、2 warnings，Node 3 passed、compileall/diff check 通过；head `69fb952`；CI `34164382428` 四项全绿；仅合成数据，无真实恢复/部署声明 |
| Runtime health diagnostics | `feat/health-diagnostics-v1` | `bada0b3` | Draft PR #23；`/妮姬 管理 健康` 接入只读数据/缓存/临时文件/磁盘摘要，拒绝跟随数据根目录符号链接并将异常磁盘容量降级为未知，不删除缓存、不输出路径或凭据；head `79340a9`；CI `34164857009` 全绿；仅合成数据，无现场/部署声明 |
| Storage migration hardening | `feat/storage-migration-v1` | `bada0b3` | Draft PR #24；schema_meta 版本化、显式事务/rollback、旧 accounts 字段兼容、未来 schema 拒绝降级；head `16c9ac5`；CI `34106285962` 全绿；仅临时 SQLite，无生产 migration 声明 |
| Healthz readiness | `feat/healthz-readiness-v1` | `bada0b3` | Draft PR #25；`/healthz` 仅在 SQLite 与密钥均为普通文件时返回 200/ready，否则 503/unavailable；head `7e5e928`；CI `34106867556` 全绿；仅合成文件，无部署声明 |
| Plugin log privacy | `feat/log-privacy-v1` | `bada0b3` | Draft PR #26；统一异常/动态日志文本脱敏，覆盖主流程、公告、素材、卡片、Spine、反馈与绑定错误摘要；补充 Python 3.10.11 + AstrBot 4.14.6 本地完整矩阵 `260 passed`、43 subtests、2 warnings；head `b1f17a2`；CI `34146296068` 四项全绿；warning 为 FAISS/NumPy 与基线注册 API 弃用提示；无真实账号/线上日志/部署声明 |
| Safe offline cache cleanup | `feat/cache-cleanup-v1` | `bada0b3` | Draft PR #27；默认只读计划，显式 `--apply` 仅清理白名单缓存和公告缓存，保护 cards/SQLite/secret.key/扩展 ZIP 并跳过符号链接；head `bb94d18`；CI `34108821103` 全绿；本地 pytest 259 passed、Node 3 passed；未在真实 data/nikke 应用清理 |
| Release metadata and configuration | `feat/release-metadata-v1` | `bada0b3` | Draft PR #28；新增当前 main 基线 `0.1.8` CHANGELOG、14 项配置合同及版本/schema/文档一致性测试；head `1f379d6`；CI `34109454981` 全绿；本地 pytest 259 passed、57 subtests、Node 3 passed；未创建发行包或部署 |
| Caddy example privacy | `feat/caddy-hardening-v1` | `bada0b3` | Draft PR #29；关闭示例 access log，避免 `/bind/{token}` 令牌进入反代日志；静态验证安全头、只读挂载、外部网络及无 6210 宿主机映射；head `160cb25`；CI `34110061494` 全绿；本地 pytest 258 passed、48 subtests、Node 3 passed；未部署 |
| Upgrade/rollback preflight | `feat/upgrade-preflight-v1` | `bada0b3` | Draft PR #30；只读检查 SQLite integrity/schema、数据库与 `secret.key` 成对存在、可选备份集和磁盘余量，输出 READY/MIGRATION_REQUIRED/BLOCKED；head `e9bf5eb`；CI `34110890912` 全绿；本地 pytest 263 passed、43 subtests、Node 3 passed；不执行迁移/回滚/复制/删除/生产写入 |
| Final product review evidence matrix | `feat/requirement-evidence-matrix-v1` | `bada0b3` | Draft PR #31；覆盖路线图 27 个 `REQ-*`，区分主线代码/接线、Draft PR、离线测试、现场证据和人工授权；head `369cc98`；CI `34112221252` 全绿；本地 pytest 258 passed、43 subtests、Node 3 passed；不执行真实账号/消息/部署/生产 migration/rollback |
| Tower static snapshot contract | `feat/tower-snapshot-contract-v1` | `bada0b3` | Draft PR #32；静态塔层快照在加载时校验来源标识、严格日期、来源 hash 文本、塔层键、正整数 `stage_id`/战力和唯一 stage ID；损坏快照安全失败，未知层明确未收录，异常或非规范输入不被静默归一化；已实际查看内置“极乐净土 1”文本输出；本地定向 pytest 5 passed、11 subtests，全量 pytest 259 passed、54 subtests、Node 3 passed、compileall/diff check 通过；head `eede5ab`；CI `34127584276` 全绿；未更新数据、访问来源、读取账号或宣称来源新鲜度/授权/玩家进度 |
| Character Data V2 registry and cache identity boundary | `feat/character-data-v2` | `bada0b3` | Draft PR #11；静态 Equipment/Cube/Favorite Item registry 保持精确 ID 与 hash 校验；运行时拒绝布尔、浮点、空白和带符号 ID，未知 ID 不会通过 `sources.json`、同名本地缓存或远程请求显示资源；预览脚本可从仓库根目录直接运行并回收资源，已重新实际查看 red-hood/alice/fallback 离线合成卡；本地 Python 3.10.11 定向 26 passed、6 subtests，全量 pytest 261 passed、49 subtests、2 warnings、Node 3 passed、compileall/diff check 通过；head `80f3087`；CI `34149471006` 四项全绿；仍不宣称完整角色数值、真实账号字段、远程素材授权或产品合成联调 |
| Spine queue contract boundary | `feat/spine-spike-v2` | `bada0b3` | Draft PR #12；队列入口拒绝布尔/非整数容量、空白任务标识、路径型 `cache_key` 和异常预算/runtime 类型；本地 Python 3.10.11 pytest 265 passed、53 subtests、2 warnings，Spine 专项 9 passed、Node 3 passed、compileall/diff check 通过；head `e5b9efc`；CI `34149003554` 四项全绿；仍不宣称 runtime、许可、Linux headless、真实渲染或生产接线 |
| Voice mapping duplicate-evidence boundary | `feat/voice-mapping-v2` | `bada0b3` | Draft PR #13；story 审计显式记录 duplicate map/detail ID，重复 detail 行不再因集合去重而报告完整覆盖；本地 pytest 259 passed、专项 10 passed、Node 3 passed、compileall/diff check 通过；head `68138bc`；CI `34115632353` 全绿；仍不宣称 Poke 映射、QQ 播放、音频授权或真实账号操作 |
| Dynamic voice cache and lifecycle boundary | `feat/dynamic-voice-v2` | `bada0b3` | Draft PR #10；pipeline/provider 拒绝布尔、字符串、NaN、无穷和非正预算，pipeline 也拒绝非法 pending 容量；source cache 只有请求 `map_key`、`source_path`、SHA-256、MP3 头和非未来 24 小时有效期均匹配时才命中，关闭会取消在途共享下载并释放任务索引；本地 Python 3.10.11 Voice 专项 21 passed、12 subtests，全量 pytest 262 passed、55 subtests、Node 3 passed、compileall/diff check 通过；head `528fcdf`；CI `34148538180` 全绿；仍不宣称真实 Poke 映射、OneBot 播放、资源授权或账号联调 |
| Union Raid Increment A identifier boundary | `feat/union-raid-v2` | `bada0b3` | Draft PR #8；范围/HP/重复记录语义保持保守；overview 仅接受非空文本/明确整数 Boss ID，坏标识保留记录但标记未知覆盖并隐藏聚合；排名拒绝空白身份、空/非标 Boss ID 与角色 ID；head `c4a6fe4`；本地定向 24 passed、16 subtests，全量 pytest 267 passed、59 subtests、Node 3 passed、compileall/diff check 通过；CI `34120205125` 全绿；分页完整性、canonical identity、历史赛季和“我的战斗”仍未宣称完成 |
| Announcement V2 source/record boundary | `feat/announcement-v2` | `bada0b3` | Draft PR #9；深度读取不回退旧源；稳定 ID 与核心文本字段严格校验；版本字段严格为正整数，损坏缓存不静默截断；head `6cb544b`；本地主题回归 39 passed、42 subtests，全量 pytest 278 passed、61 subtests、Node 3 passed、compileall/diff check 通过；CI `34147704300` 全绿；未访问真实 CMS、账号或发送消息 |

本轮核验确认：D-01/D-02 已在当前 main，不再重复开实现 PR；D-03、D-04、D-07 也有现行代码和测试证据。

## 任务池

- `WAITING_REVIEW`：Announcement V2 / PR #9；Union Raid A / PR #8；Campaign History / PR #15；Campaign renderer lifecycle / PR #16；AssetManager request dedup / PR #17；Daily Evidence / PR #18；SQLite connection lifecycle / PR #19；Runtime config hardening / PR #20；Plugin shutdown lifecycle / PR #21；Data backup hardening / PR #22；Runtime health diagnostics / PR #23；Storage migration hardening / PR #24；Healthz readiness / PR #25；Plugin log privacy / PR #26；Safe offline cache cleanup / PR #27；Release metadata and configuration / PR #28；Caddy example privacy / PR #29；Upgrade/rollback preflight / PR #30；Tower snapshot contract / PR #32；Post-Profile V2 status reconciliation / PR #33；CDK batch idempotency contract reconciliation / PR #34；Structured DailyTaskResult status contract / PR #35；Per-account daily automation preference / PR #36；AstrBot registration API migration / PR #40；其余已创建 Draft PR。
- `READY`：在不依赖上述未合并分支的前提下，继续做可离线验证的独立主题。
- `WAITING_DEPENDENCY`：Raid Increment B/C 等待相关基线进入 `main`；不从旧 overnight 分支继续开发。
- `NEEDS_LIVE_EVIDENCE`：真实 Profile、Raid canonical identity、Daily Like/Browse 写入、Voice QQ 实际播放、Spine 生产许可/运行时。
- `NEEDS_HUMAN_DECISION`：自动 merge、ruleset、部署、真实生产 migration、价值 CDK 消费。

## 依赖与暂缓

- Raid Increment B/C 等待 Raid A 的接口语义进入可复用基线，不能把未合并分支当作当前 main。
- Character Data V2 后续字段等待 registry A 的独立变更合并或明确依赖处理。
- Voice QQ 实际播放、Daily 写入、真实 Profile 和 Spine production runtime 仍需要现场/人工证据。
- 公开只读研究、合成测试和离线 payload 不得冒充真实联调、消息发送或资源授权。
