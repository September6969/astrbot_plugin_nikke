# NIKKE 现场证据登记

更新时间：2026-09-09。基线：`origin/main@ad0ef20895dbed36963ce8eea0948c3cb25ca133`。

本登记将“已有离线代码/测试”与“需要现场证据”的问题分开。当前路线图已明确授权真实账号只读、最小必要真实写、QQ/NapCat、Voice、Spine 和部署验证；本登记不扩大该范围，也不替代具体动作的备份、前态/后态和隐私检查。

## 通用现场边界

- 现场动作只在路线图授权的目标环境和最小范围内执行；默认仍为只读，写入、发送和部署必须逐项记录前态、意图、后态与回滚边界。
- 采集前删除 Cookie、完整 OpenID、QQ、game UID、绑定 token、CDK 和群聊标识。只保留最小脱敏响应或字段清单。
- 对写操作必须先记录前态、一次操作意图、后态读取和不可重放结果；超时或取消统一记为 `UNKNOWN_AFTER_ACTION`，不自动重试。
- 消息或音频送达只允许在获授权的测试会话中验证一次；不得把 API 返回或 mock 当作送达证据。
- 任何采集失败只记录 endpoint、HTTP/业务错误类别和脱敏字段，不扩展权限或改用其它账号。

## E-ARCANA-01：三种查询入口与真实 CharacterDetails 结构

**状态**：`AUTHORIZED_LIVE_READ`。现场证据文件：`docs/evidence/arcana_live_20260909.json`。

**已查来源**：仓库 `CharacterDirectoryResolver`/`assets/character_aliases.json`；BlaBlaLink 中英文角色目录；`GetUserCharacters` 与 `GetUserCharacterDetails`。执行环境为 `ssh serv` 上现有 `astrbot` 容器，使用已绑定测试账号做只读请求。

**结果**：`阿爾卡娜`、`阿尔卡娜`、`ARCANA` 均解析到 `name_code=5140`，公开目录 `resource_id=581`；账号持有该角色且现场 `costume_id=0`。详情字段只保存字段名/类型，StateEffect 只保存 option ID、function type、value type 和 value shape；没有保存原始响应或账号标识。

**未决问题**：四个现场 option 尚不足以证明全量 StateEffect 映射、中文标签、divisor、1–15 阶表、HP/ATK/DEF 公式或非默认 Costume。下一步必须分别取得可复核的公开/static metadata 和公式对照，不从这一账号样本扩展推断。

## E-STATE-EFFECT-01：四条公开 StateEffect 数据闭环

**状态**：`PARTIAL_LIVE_VERIFIED`。现场/公开证据文件：`docs/evidence/state_effect_registry_live_20260909.json`。

**已查来源**：当前 BlaBlaLink 公开页面加载的 StateEffect 分组 JSON；同页面公开 JS 的 `getBuffContents` 展示路径；Arcana `CharacterDetails` 只读样本。四条 exact option ID 均同时具备公开 group、现场 function type/value type 和来源 SHA-256。

**已登记**：`7000611`、`7001011`、`7001111`、`7001211`；对应 `StatAccuracyCircle`、`StatChargeTime`、`StatCritical`、`StatCriticalDamage`，显式 `value_divisor=100`。registry 只按 option/function/locale 精确命中，不再按 function type 唯一回退。

**未决问题**：这是四条验证子集，不代表全量 StateEffect；剩余 option 的 function contract、完整 1–15 阶表、HP/ATK/DEF 公式和非默认 Costume 仍需独立证据。公开展示规则也不等于游戏服务端全部数值语义。

## E-STATE-EFFECT-02：批量 OL function 现场闭环

**状态**：`LIVE_READ_ONLY_VERIFIED`。证据文件：`docs/evidence/state_effect_function_inventory_live_20260909.json`、`docs/evidence/live_character_stats_20260909.json`。

**已查来源**：`ssh serv` 上现有 `astrbot` 容器；一次 `GetUserCharacters` 取得 177 个角色后，一次 `GetUserCharacterDetails` 批量请求取得 177 条详情和 109 条 state-effect function 行；原始凭据和响应只在内存中使用。

**已登记**：109 条现场出现的 option/function 精确键进入 `assets/state_effects.json`。Percent 的 divisor=100 有当前公开前端展示规则支持；Integer 的单位保持 unknown，不进入确认汇总。未出现的 option 不扩展推断。

**HP/ATK/DEF 结论**：详情只观察到 `combat`、`arena_combat`，个人资料只观察到 `team_combat`；没有 HP/ATK/DEF 字段或公式来源，不能把战力、等级或静态资料反推成三项属性。

## E-NUMERIC-01：角色卡异常数值语义

**状态**：`READY_OFFLINE`；本主题没有新增现场动作。

**已查来源**：`card_builder.py` 的 `CharacterDetails → CharacterCardData` 链路、现有脱敏 fixture、角色卡 renderer 的 `None → —` 合同和新增异常输入行为测试。

**已完成**：整数只接受整数形状；bool、浮点截断、NaN/Infinity、负数 HP/ATK/DEF 和非法动态词条值不会被当作合法练度。HP/ATK/DEF 异常保留未知，不由 combat、等级或其他静态字段反推；动态词条异常不进入汇总。

**未决问题**：真实账号是否提供 HP/ATK/DEF、字段单位和服务端公式仍需授权现场读取后确认；本主题不把 fixture 或静态推理升级为 live evidence。

## E-PROFILE-01：真实 `/妮姬 我的` 字段兼容

**已查来源**：`main.py` 的 `/妮姬 我的` 命令链；`client.py:get_profile_dashboard`；`profile_builder.py`、`profile_card_renderer.py`；`tests/test_profile_v2.py` 与 `docs/PROFILE_V2_ACCEPTANCE.md` 的合成响应、请求预算和 PNG 证据。

**未决问题**：真实 `basic/outpost/roster` 是否仍符合当前字段合同；缺失、`0`、空列表和部分损坏项在现场的实际组合；不同账号是否仍保持三次请求且没有 `GetUserCharacterDetails`。

**最小授权动作**：在一个明确授权、只读的测试账号上运行一次 `/妮姬 我的`；只保存脱敏字段类型/缺失矩阵、三 endpoint 计数和生成图的人工检查结论。不得保存原始响应或发布图片。

**判定**：通过只表示 `READY_LIVE` 的字段兼容证据；不表示部署或长期稳定性已验收。

## E-RAID-01：联盟突袭 identity 与响应范围

**已查来源**：`client.py` 的 `GetMyGuildInfo`、`GetUnionRaidLevelInfo`、`GetUnionRaidData` 常量与请求链；`scripts/capture_union_raid_fixtures.py` 的完整 `intl_open_id` 与 `guild_id/nikke_area_id` payload；`scripts/raid_evidence.py` 的关系保留脱敏；`tests/test_union_raid.py`、`tests/test_raid_evidence.py` 的离线合同。

**未决问题**：`participate_data` 中哪一个身份字段可与当前账号安全对应；响应是当前轮次、单页还是完整赛季；成员、攻击次数、剩余次数和同分排名的范围语义；历史赛季是否由同一 endpoint 提供。

**最小授权动作**：在一个已加入联盟且授权只读的测试账号上，仅采集一次三 endpoint 的脱敏字段关系：`GetMyGuildInfo`、`GetUnionRaidLevelInfo`、`GetUnionRaidData`。使用仓库 sanitizer 输出关系保持 fixture，不保存原始 identity；记录是否存在分页/游标和当前账号匹配依据。

**禁止推断**：不得从昵称、OpenID 片段、记录数量或单次响应推断成员对应、完整性、历史范围或剩余次数。

## E-ANN-01：公告与日程正式 source

**已查来源**：`announcement_service.py`、`announcement_sources.py`；`tests/test_announcements.py`；`announcement_delivery.py` 与推送接线测试。当前离线测试仅证明解析、缓存和去重合同。

**未决问题**：正式 InformationFeeds/CMS 的可用 source、字段版本、日程时区、分页/重扫边界及变更事件语义。

**最小授权动作**：由维护者提供一个允许只读访问的正式 source URL 或环境，在不订阅、不推送的前提下执行一次公告/日程查询；记录脱敏字段名、时间格式、稳定 ID 和缓存命中/失效结论。

**禁止事项**：本登记不授权创建订阅、向群或用户发送公告、把公开网页抓取结果写成官方 CMS 合同。

## E-DAILY-01：签到写后状态与 Like/Browse endpoint

**已查来源**：`client.py` 的 `TASK_LIST`、`DAILY_CHECK_IN`；`main.py` 的默认关闭日常开关；`storage.py` 的 action/状态记录；`tests/test_daily_safety.py`。当前 main 没有经确认的 Like 或 Browse endpoint，不能依据旧计划或离线 payload 接线。

**未决问题**：签到的写后状态字段、幂等/已完成业务码、超时后实际状态；Like/Browse 的官方 endpoint、前后状态和错误语义。

**最小授权动作**：

1. 先在一个明确授权的测试账号上只读读取任务列表并保存脱敏字段矩阵。
2. 若维护者单独授权一次签到写入，记录前态、一次 intent、后态读取及不可重放结果；不在未知结果后重试。
3. Like 与 Browse 必须分别先提供官方 endpoint 或脱敏写后读取证据；未提供前保持未接线。

**禁止事项**：不自动开启 `enable_daily_actions`，不在群汇总、定时任务或多个账号上试验，不把 mock 状态视为真实写后结果。

## E-VOICE-01：Poke 与实际 Record 送达

**已查来源**：`voice_audio.py`、`voice_pipeline.py`、`voice_resource_provider.py` 的离线资源、缓存、预算和取消边界；`main.py` 的命令/文本路径；`tests/test_voice_*.py`；Draft PR #10/#13 的离线动态管线与映射证据。

**未决问题**：AstrBot/OneBot 当前版本的 poke event 形状、目标用户解析、adapter 对 Record 的接受格式、音频是否实际送达并可播放；角色/皮肤映射与本地音频许可。

**最小授权动作**：维护者在一个隔离测试会话中提供 adapter 版本、事件样例和一份确认可用的本地测试音频；先只读记录事件字段，再由维护者明确授权一次发送，记录 adapter 接收和用户可播放两项独立结论。

**禁止事项**：不得向真实群/用户试探发送；不能用文本 fallback、pipeline completion 或文件生成冒充 Record 送达；不得下载或使用未授权语音资源。

## E-SPINE-01：生产 runtime、许可与代表性渲染

**已查来源**：`spine_prerenderer.py` 的发现、预算、队列和缓存预检查；`tests/test_spine_inspection.py`；Draft PR #12 的队列合同。当前路径不把 Spine 作为首张角色卡的阻塞依赖。

**未决问题**：可合法采用的 runtime 及许可条款；目标 skeleton/atlas 的版本与多纹理兼容性；Linux headless 渲染、透明 PNG、内存/耗时和资源授权。

**最小授权动作**：由维护者先确定 runtime 与许可允许范围，再提供一份可再分发的代表性 fixture；在隔离环境做一次本地 headless PNG 渲染与基准，记录版本、耗时、峰值内存、输出尺寸和许可依据。

**禁止事项**：不得自行下载私有游戏资源、复制不兼容 runtime/source、把预检查/队列存在描述为生产渲染完成，或让首张卡等待 Spine。

## 证据闭环检查表

每一条现场证据完成时，必须同时补充：

1. 授权范围与执行日期；
2. 已查 endpoint/adapter/runtime 的版本或脱敏字段合同；
3. 输入前态、最小动作、输出后态（写/送达项必须三者都有）；
4. 证据等级：`AUTHORIZED_LIVE_READ`、`AUTHORIZED_LIVE_WRITE` 或仍为 `UNVERIFIED`；
5. 未解决问题与下一项最小动作；
6. 是否需要新测试、fixture 或用户决策。

任何一项缺失时，能力保持 `NEEDS_LIVE_EVIDENCE` 或 `NEEDS_HUMAN_DECISION`，不得更新为生产完成。
