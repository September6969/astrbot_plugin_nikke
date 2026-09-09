# NIKKE 长期路线台账

更新时间：2026-09-09。本文件是路线图状态摘要，不是运行时状态源；每次恢复前仍须重新 fetch、核验 GitHub PR/CI、工作树和未提交状态。

## 当前基线

本轮按依赖顺序推进独立 Draft PR。本次主题从已重新核验的 `origin/main@7c164cd1d9814fc7b4530de861813665187e63b5` 建立；恢复任务时仍须重新核验。

## 本轮已合并主题

| 主题 | 结果 |
| --- | --- |
| Post-Merge Sync / Profile V2 | 已合并；Profile 命令离线闭环、字段语义、分区去重和合成预览均有记录；真实账号与部署证据仍未执行 |
| Registration / storage / migration / runtime / shutdown | 已合并；注册 API、连接生命周期、事务迁移、配置边界和幂等回收按依赖顺序落地 |
| Health / backup / cache / deployment preflight | 已合并；健康诊断、备份、清理、Caddy 示例、升级前置检查与发布元数据保持只读/离线边界 |
| Raid / campaign / tower / CDK | 已合并；数值与响应合同、快照和批次幂等语义有行为测试；不宣称真实账号联调 |
| Announcement / daily / voice / character / spine | 已合并；字段合同、状态语义、动态资源边界与日志证据已进入主线；公开资源和合成数据不等于授权或生产证据 |
| Asset lifecycle | 已合并；同键 single-flight、跨实例远端下载槽位、有限预取和 campaign 共享 manager 已组合验证，未宣称真实远端负载或全链路生产 N+1 证据 |
| Log privacy / evidence docs | 已合并；异常、Cookie 上下文和动态日志净化，并保留现场证据登记、需求矩阵与 Profile 状态边界 |
| v4 F1/F2 CDK success contract / no replay | 已合并 PR #41，merge `553b8731668b588fdf8d54a87b083156dc5f30fc`；严格成功字段、持久 claim、unknown-after-action 与单条/批量共享原语均有行为测试 |
| v4 F3/F4 Daily identity / migration-safe recovery | 已合并 PR #42，merge `2a2df3587c9c437437f94483a2f55defabda7151`；按稳定游戏身份分区，旧 QQ 记录保守阻断，缺失任务可安全重试；未执行真实签到 |
| v4 F5 costume-aware cache | 已合并 PR #43，merge `d35bbef94e8c955011608509f17586c185ec3fd0`；default/known/unknown/invalid 分离，远端与本地缓存键保持 costume 语义；未验证真实资源负载 |
| v4 F6 recoverable backup | 已合并 PR #44，merge `9d35655f9f73ba3517d0c9e9a20ac5128794b504`；只读密钥/数据库校验、SQLite backup API、隔离暂存、完整性与加密字段恢复验证已由 CI 覆盖 |
| Offline Raid “我的” | 已合并 PR #45，merge `7b1b07cd89b1b5dbac20bf03f2f162b0b22b65c1`；使用绑定 `game_openid` 精确筛选当前响应、无 N+1、保留完整赛季与 canonical identity 现场缺口 |
| Spine 正式编排基础 | 已合并 PR #52，merge `44266cad2cbc31f95b46ee7fb342c9c19c231f89`；正式 runtime 注入、bundle 白名单/缓存、严格版本匹配、队列和 PNG 回退进入主线 |
| Spine 4.1 headless worker / Costume | 已合并 PR #53，merge `7ad7a3a7bae5a854d289f75a18d6b6bd89c2e195`；官方 4.1 源码固定提交、Linux Docker 构建、SDL dummy/software worker、RGBA CLI adapter 和 Costume 空映射合同进入主线 |
| Resource Registry V2 | 已合并 PR #54，merge `09821816f7489885f4fb33045fd56fe39adda1d3`；Costume registry 合同、来源/hash 清单和 unknown/invalid 隔离进入主线，映射保持空表 |
| Live RC StateEffect Registry | 已合并 PR #62，merge `1a98895e4af19f360b3a2cc79bb40cb0542b415a`；严格 registry 合同和 builder 接线进入主线，真实映射仍待现场来源闭环 |
| Live Data Closure / Arcana evidence | 已合并 PR #63，merge `bd5f518e8dcd5001d9b52d0a3f8882f4d7275df5`；记录 Arcana 只读字段证据、身份解析和隐私边界 |
| Live StateEffect data closure | 已合并 PR #64，merge `7c164cd1d9814fc7b4530de861813665187e63b5`；四条 Arcana observed option 的公开分组/formatter 证据进入 partial registry，解析改为 exact |

## 证据边界

- `READY_OFFLINE` 只表示本地合同、行为测试、合成输出或离线预览已验证。
- `NEEDS_LIVE_EVIDENCE` 仍包括真实账号 Profile/Raid 字段兼容、Daily 写入后的真实状态、Voice 实际播放送达、Spine 生产运行时/许可、真实远端素材负载和部署环境图片。
- Raid “我的”目前只证明了离线的精确 `game_openid` 筛选和当前响应文案；尚未证明响应 `openid` 与绑定身份的现场 canonical 关联，也不把返回条数当作真实出刀次数。
- 未接线模块、mock/fixture、合成 PNG、公开只读访问和静态代码检查不得冒充产品完成、真实联调、消息发送或资源授权。
- 本轮已在获授权环境执行一次服务器内的 Arcana 只读结构采样；没有执行账号写入、发送消息、部署、修改 main 工作树、删除分支或修改 ruleset。现场只保存脱敏字段合同、公开资源 ID、option ID、函数类型和值形状及响应 hash，不保存 Cookie、OpenID、QQ 标识、游戏 UID 或原始响应。随后通过公开页面核验了四个 observed option 的分组标签和 `/100` 展示规则，但不把它扩展为全量数据库或完整阶级表。P4 分支曾因修正已推送提交的 EOF 使用一次 `--force-with-lease`，未触及 main 或其他分支；随后已改为普通提交并保持线性历史。

## 后续工作

下一主题必须从届时最新 `origin/main` 建立独立 worktree、branch 和 Draft PR，并先写清字段合同、请求预算、异常语义、测试和证据缺口。已合并主题不得通过旧 overnight 分支恢复。当前路线图已授权真实账号只读、最小必要真实写、QQ/NapCat、Voice、Spine 与部署验证；环境可用时直接执行对应最小动作，只有不可达、缺少安全凭据、外部服务不可用、需要新的产品/法律决策或不可逆操作无法安全执行时才保留现场缺口。

## Live Data Closure / Arcana 现场证据（当前独立主题）

- `feat/live-data-closure-v1` 已合并为 PR #63；工作树 `E:\DevCache\nikke-live-data-closure-20260909` 保留，不作为当前开发基线。该主题从 `origin/main@1a98895e4af19f360b3a2cc79bb40cb0542b415a` 建立，不使用旧 overnight 或已合并主题工作树作为基线。
- 通过 `ssh serv` 对现有 `astrbot` 容器执行只读采样：三个输入 `阿爾卡娜`、`阿尔卡娜`、`ARCANA` 均解析到 `name_code=5140`，公开目录 `resource_id=581`；绑定账号持有该角色，当前 `costume_id=0`。
- 真实 `CharacterDetails` 观察到四个 option ID：`7000611`、`7001011`、`7001111`、`7001211`，对应 `StatAccuracyCircle`、`StatChargeTime`、`StatCritical`、`StatCriticalDamage`；详情字段名/类型和响应 hash 见 `docs/evidence/arcana_live_20260909.json`。
- 本主题完成 `AUTHORIZED_LIVE_READ` 证据登记与隐私边界测试；没有把单账号样本扩展为全量 StateEffect/OL tier、HP/ATK/DEF 公式或 Costume 映射。公开/static option metadata、精确 divisor/中文标签、1–15 阶表和非默认 Costume 的后续闭环在当前独立主题处理。

## Live RC Stabilization v2（Profile 已合并）

- `feat/live-rc-profile-stabilization-v1` 从实时核验的 `origin/main@d65065b` 建立，PR #58 已合并，merge `a34f6fcae2bc6d89eaa50eb72bcddc6675ebc559`。
- `CampaignStageResolver` 从已验证的 `assets/campaign_stages.json` 一次性建立 `stage_id → CampaignStage` 反向索引；6048044 → NORMAL 48-36、7037041 → HARD 37-33，未知或 mode 不匹配保留 `未映射 · ID …`，不使用经验公式。
- `ProfileBuilder` 已接入共享 resolver；`created_at` 严格支持已确认的秒/毫秒 Unix 时间戳和 ISO-8601，按 UTC+8 输出日期，坏值为未知；战术学院数字字段保持中性未映射语义。
- 离线证据：定向 Profile/Campaign 65 tests、完整 pytest 484 passed / 190 subtests、`compileall`、Node 扩展 3/3、`git diff --check` 均通过；尚未执行真实账号 Arcana/Profile 回归，状态为 `READY_OFFLINE`，现场项仍为 `NEEDS_LIVE_EVIDENCE`。

## Live RC Character Localization（已合并）

- `feat/live-rc-character-localization-v1` 从实时核验的 `origin/main@a34f6fc` 建立，PR #59 已合并，merge `530eeef5faf25cbf5b15bd71fc13ccd193a62f94`；新增 `CharacterDirectoryResolver`，统一角色卡、练度查询、资料查询和练度表名称映射。
- 目录明确区分 `name_zh_tw`、有来源时的 `name_zh_cn`、仅查询用途的 `name_zh_cn_alias`、`name_en` 和 `name_code`；旧 `name_cn` 保留为官方繁中兼容字段。
- `assets/character_aliases.json` 只登记文档已确认的 `阿爾卡娜 → 阿尔卡娜` 查询别名，明确不声称官方 zh-CN；三种输入解析到同一 `name_code`。
- 离线证据：身份/卡片/核心路由定向 53 passed / 10 subtests，完整 pytest 488 passed / 190 subtests，`compileall`、Node 3/3、`git diff --check` 通过；真实目录内容与 Arcana 现场查询仍为 `NEEDS_LIVE_EVIDENCE`。

## Live RC OL Contract（当前独立主题）

- `feat/live-rc-ol-contract-v1` 从实时核验的 `origin/main@530eeef` 建立，PR #60 已合并，merge `bee6d580ab763912afaeb3b855dfd4c617955826`；历史工作树为 `E:\DevCache\nikke-live-rc-ol-20260909`，HEAD 不代表当前 main。
- `EquipmentOption` 记录 option position、原始 option/state-effect ID 和多 function components；每个已装备部位固定生成并渲染 option1/2/3 三行，缺失行显示“空槽 / —”，未知 effect 显示“未识别词条”，多 function 不再挤占后续位置。
- 词条汇总只累加已识别且单位确认的 component；未知单位、复合行和空槽不参与数值汇总，不猜单位或阶级。精确 StateEffect registry、1–15 阶反查和 HP/ATK/DEF 现场字段仍不在本主题中伪造，保留后续证据缺口。
- 离线证据：角色 builder / renderer 定向 16 passed，完整 pytest 490 passed / 190 subtests，`compileall`、Node 3/3、`git diff --check` 通过；合成渲染只证明本地布局与 fallback，不等于真实账号、QQ 送达或生产字段证据，状态为 `READY_OFFLINE`，现场项仍为 `NEEDS_LIVE_EVIDENCE`。

## Live RC Character Stats Evidence（当前独立主题）

- `feat/live-rc-card-evidence-v1` 从实时核验的 `origin/main@bee6d580` 建立，PR #61 已合并，merge `70c811c6feeb5b09cf3115aba38792d85d84b4e7`；历史工作树为 `E:\DevCache\nikke-live-rc-card-evidence-20260909`，HEAD 不代表当前 main。
- 新增脱敏 CharacterDetails 结构诊断：只记录字段名、类型、非空状态、位数和符号形状；过滤 Cookie、token、Authorization、openid、邮箱、密码和 secret，不输出账号原始值。
- 已核对本地脱敏 fixture、Exia 的 simulated stats 说明和 monster 的 Bla CDN state-effect extractor；未确认真实 HP/ATK/DEF 字段，角色卡继续对缺失/坏值显示 `—`，不从 combat、等级或模拟值反推。
- 离线证据：诊断定向 2 passed；脱敏 fixture CLI 可输出结构报告；真实 CharacterDetails 字段和游戏内数值对照仍为 `NEEDS_LIVE_EVIDENCE`。

## Live RC StateEffect Registry（已合并）

- `feat/live-rc-state-effect-registry-v1` 从实时核验的 `origin/main@70c811c` 建立，PR #62 已合并，merge `1a98895e4af19f360b3a2cc79bb40cb0542b415a`；历史工作树为 `E:\DevCache\nikke-live-rc-state-effect-20260909`，HEAD 不代表当前 main。
- `StateEffectRegistry` 严格要求 option/state-effect/group identity、function type、localized label、value kind/divisor、locale、无凭据 HTTPS 来源、来源 SHA-256 和核验日期；重复/非法/无来源记录拒绝加载。原始合并时 `assets/state_effects.json` 保持空表，等待现场来源闭环。
- builder 命中来源记录时按显式 formatter 解析动态 `state_effects` 值；未命中继续既有安全 mapping，unknown 不进入确认单位汇总。没有猜测 1–15 阶表、相邻 ID 或单位。
- 离线证据：registry + card builder 定向 15 passed；真实 Bla CDN metadata、完整 function_type 覆盖、精确 1–15 tier lookup 和现场角色卡仍待证据。

## Live StateEffect Data Closure（已合并）

- `feat/live-state-effect-data-v1` 已合并为 PR #64，merge `7c164cd1d9814fc7b4530de861813665187e63b5`；历史工作树为 `E:\DevCache\nikke-live-state-effect-data-20260909`，不复用旧 overnight 或历史 StateEffect worktree作为当前基线。
- 依据 Arcana 现场四个 option ID 与公开 BlaBlaLink StateEffect 分组表，登记四条 exact 映射：`7000611 → StatAccuracyCircle`、`7001011 → StatChargeTime`、`7001111 → StatCritical`、`7001211 → StatCriticalDamage`；来源 URL、SHA-256、标签和 group ID 保存在 `assets/state_effects.json` 及 `docs/evidence/state_effect_registry_live_20260909.json`。
- 当前页面的 `getBuffContents` 公开展示路径明确使用 `abs(function_value) / 100` 后格式化为百分比；四条记录显式使用 `value_divisor=100`，不依据 option 相邻 ID 或名称顺序猜测。
- 这是 `PARTIAL_LIVE_VERIFIED` 的四条子集，不是完整 StateEffect registry；其余 option、完整 1–15 阶数值、HP/ATK/DEF 公式和非默认 Costume 继续保留现场缺口。registry 解析已收紧为 exact option/function/locale，不再以唯一 function_type 跨 option 回退。

## Live Numeric Semantics（当前独立主题）

- `feat/live-numeric-semantics-v1` 从最新 `origin/main@7c164cd1d9814fc7b4530de861813665187e63b5` 建立，工作树为 `E:\DevCache\nikke-live-numeric-semantics-20260909`；不在已合并 StateEffect worktree 或旧 overnight 分支上追加。
- `CharacterCardBuilder` 的整数解析现在只接受 JSON 整数或十进制整数字符串，显式拒绝 bool、浮点截断、NaN/Infinity、非标量和负数 HP/ATK/DEF；动态词条值拒绝非有限值，异常词条显示“未识别词条”且不进入汇总。
- HP/ATK/DEF 仍只使用源端确认字段；缺失、负数或异常保持 `None`，由角色卡渲染为 `—`。level/combat/skill/grade/core 的异常输入采用安全零值以保持现有数据合同，不由其他字段反推。
- 本主题只需离线行为证据，不执行账号读取、账号写入、消息发送、部署或现场数值公式推断；现场 HP/ATK/DEF 字段是否存在仍按 `NEEDS_LIVE_EVIDENCE` 保留。

## Live OL Tier Registry（当前独立主题）

- `feat/ol-tier-registry-v1` 从最新 `origin/main@75edaaa0288222337b6d2609447db1a6405d7198` 建立，使用 `ssh serv -> curl` 实时取得公开 BlaBlaLink 分组源，不使用旧 overnight 分支。
- 新增 `assets/overload_tiers.json` 与 `OverloadTierRegistry`：精确登记 9 个 OL 分组、27 条来源记录、135 个 state-effect ID，覆盖每组 1--15 阶；排除同响应中的 3 条通用 `931xxxx` 记录。
- `CharacterCardBuilder` 在 option 等级缺失时接入已核验等级；未知 function type、单位和动态数值仍不猜测、不进入确认汇总。
- 证据与验收：`docs/evidence/overload_tier_registry_live_20260909.json`、`docs/OL_TIER_REGISTRY_ACCEPTANCE.md`；状态为 `READY_OFFLINE` + `LIVE_PUBLIC_SOURCE_VERIFIED`。

## FB 静态立绘路线（进行中）

- P0 静态 FB / Costume 主链：`feat/fb-static-mainline-v1`，从 `origin/main@c4f1755a50903f7d47ac8904715b61c880c4605b` 建立；已补 costume 字段贯通、严格空映射清单和普通路径零 Spine 合同，状态 `READY_OFFLINE`，PR #47 CI 全绿。
- Costume 实际映射及完整角色目录覆盖：`NEEDS_LIVE_EVIDENCE`；没有制造映射，也没有把可构造 URL 当作远端存在性证据。
- P1 单角色练度卡最终版：`feat/character-card-final-v1`；完成非透明像素三色主题、企业低透明水印、属性弱 accent、Abnormal 深紫黑、装备图标放大和六张合成预览，状态 `READY_OFFLINE`，PR #48 CI 全绿。
- P1 卡片视觉：PR #48 已合并；P1 Item/Cube 完整性：PR #49 已合并；P2 Guide/Help 素材：PR #50 已合并；P4 Spine 隔离：PR #51 已并入当前 main。本轮正式 Spine backend 从最新 main 独立建立，不回退已合并隔离提交。
- Raid / Campaign / Tower 既有离线主题已在当前 main 基线中具备合同、fixture 和行为测试；真实 canonical identity、赛季范围和账号进度仍标为 `NEEDS_LIVE_EVIDENCE`，本轮未重复制造现场证据。
- 真实账号、QQ 发送与部署保持未授权/未执行。
## 六项 Guide / Help（已合并）

- `feat/guide-assets-v1` 从 `origin/main@c4f1755a` 独立建立；六类路由、16 个图片输出、红球白名单链接、哈希清单与授权 caption 已接入，状态 `READY_OFFLINE`，PR #50 已合并。
- 已逐张查看处理副本；真实 QQ 压缩、送达和部署仍为 `NEEDS_LIVE_EVIDENCE`，本主题未执行发送或部署。
## Favorite Item / Cube 完整性（已合并）

- `test/item-resource-integrity-v1` 从 `origin/main@c4f1755a` 独立建立；补齐未登记、404、超时、损坏缓存与解码失败行为证据，状态 `READY_OFFLINE`，PR #49 已合并。
- 未发现带来源证据的新映射，故没有扩充当前 4 个 Favorite Item / 8 个 Cube 清单；完整覆盖仍为 `NEEDS_LIVE_EVIDENCE`。
## Spine 正式后端（当前独立主题）

- `feat/spine-formal-backend-v1` 从 `origin/main@492e1f56` 独立建立；根目录实现正式依赖注入、版本匹配、bundle 白名单缓存、后台队列、版本化 PNG 与 FB/占位回退，`experimental/` 仅保留兼容导出层。
- 编排层与合成 adapter 测试状态 `READY_OFFLINE`；具体 runtime、真实 bundle/素材许可、Linux headless 和 benchmark 状态为 `NEEDS_LIVE_EVIDENCE`，不因缺少现场证据阻塞离线开发。
- 角色卡热路径只消费已有 L2D 索引，不为每个角色单独刷新索引；Spine cache miss 不同步等待，当前请求继续静态 FB/几何 fallback。

## Spine 4.1 headless worker / Costume（已合并）

- `feat/spine-runtime-costume-v1` 从合并后的 `origin/main@44266cad2cbc31f95b46ee7fb342c9c19c231f89` 建立，PR #53 已合并；没有复用旧 formal worktree。
- 新增 `runtime/spine_worker` 的 C++/SDL worker、Docker 构建文件和 Python 受限 CLI adapter。构建默认锁定官方 `spine-runtimes` 4.1 commit `77a5db0ec6d16331f5efbaa7662bba9355bd3424`；官方源码与二进制不入库。
- AstrBot 主入口已支持通过 `spine_worker_path`、`spine_runtime_version`、`spine_worker_timeout` 可选接线；配置为空或 worker 不存在时保持静态 FB/占位回退。共享 `data/nikke/cache/spine-bundles`，worker 无账号 header、仅 dummy/software SDL。
- `assets/costumes.json` 当前仍为空；没有可核验的 API costume ID → Nikke-DB asset ID 证据，因此不制造映射。default/known/unknown/invalid 状态隔离由现有 provider 与行为测试覆盖。
- Python adapter 离线测试已通过 12 项（worker RGBA 协议、路径越界、坏输出、超时、配置接线及 formal backend）；官方 Linux 编译、合法 bundle 实渲染、benchmark 和服务器恢复后的现场证据仍为 `NEEDS_LIVE_EVIDENCE`，不可由合成测试替代。

## 资源 Registry V2（已合并）

- `feat/resource-registry-v2` 从已合并的 `origin/main@7ad7a3a7bae5a854d289f75a18d6b6bd89c2e195` 独立建立，PR #54 已合并；新增 `costumes.json` registry 合同、manifest 来源/hash/许可边界和 AssetManager 暴露字段。
- `costumes.json` 当前保持空对象。没有 API costume ID → Nikke-DB asset ID 的来源证据时不制造映射；unknown/invalid 不推导相邻 ID，也不回退默认服装。
- `tests/test_static_registry.py` 覆盖空表、显式 costume ID/value、hash mismatch、重复键、目录穿越和 bool ID；状态目标为 `READY_OFFLINE`。
- CDN 完整覆盖、实际资源存在性、游戏美术授权和服务器现场渲染仍为 `NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION`，不可由可构造 URL、fixture 或绿色 CI 替代。

## Voice Pipeline V2（当前独立主题）

- `feat/voice-pipeline-v2` 从合并后的 `origin/main@09821816f7489885f4fb33045fd56fe39adda1d3` 建立；接入本地音频 → 精确证据映射的官方动态资源 → 文本三级回退。
- `VoiceMapRegistry` 要求 `character + costume + locale` 完整精确键、HTTPS 来源和核验日期；`assets/voice_poke_map.json` 当前保持空表，未把剧情语音或 Alice 映射猜成 Poke 语音。
- `VoicePipeline` 共享下载/编码任务，响应预算为 4 秒、最大 5 秒；插件关闭时回收 pipeline、provider 和 encoder。工具缺失或动态映射不存在时保持文本回退。
- 离线状态目标为 `READY_OFFLINE`；角色/服装映射、资源授权、NapCat/OneBot 实际 Record 播放和 QQ 送达仍为 `NEEDS_LIVE_EVIDENCE`。

## 最终回归与发布准备（当前独立主题）

- `feat/final-acceptance-v1` 从 `origin/main@2f969756b18ad7e28c41564b07ba0aa60b0dc59d` 建立；核对 README、CHANGELOG、配置合同、Caddy/HTTPS 示例、healthz、backup、upgrade preflight、日志隐私、shutdown 和资源生命周期。
- 新增 `docs/RELEASE_CHECKLIST.md` 与 `docs/FINAL_ACCEPTANCE_REPORT.md`，集中列出已合并 PR、离线测试、当前无开放 PR、现场阻塞原因和最小人工动作。
- 本次 `ssh serv` 复核在 banner 阶段超时；不修改现有 `astrbot`、`napcat`、`nikke-caddy` 容器，不把旧快照当本次现场证据。
- 本主题状态为 `READY_OFFLINE`；真实账号、QQ Record 送达、Spine 实构建/合法 bundle/许可、Costume/Voice 映射、部署、迁移和回滚仍按具体条目标为 `NEEDS_LIVE_EVIDENCE` 或 `NEEDS_HUMAN_DECISION`。
