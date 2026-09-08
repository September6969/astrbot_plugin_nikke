# NIKKE 需求证据矩阵

更新时间：2026-09-07。

本矩阵按路线图第 4、5、54、55 节建立，审计基线为 `origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。开放 Draft PR 的代码不视为已进入主线；表中明确标注的 PR 只表示可审阅的后续证据。

## 状态语义

- `IMPLEMENTED`：主线已有对应代码；不等于真实环境验收。
- `WIRED`：主线已有用户命令或服务入口接线。
- `SYNTHETIC_VERIFIED`：有离线合成响应、行为测试或渲染检查。
- `READY_OFFLINE`：当前离线合同和测试达到本阶段可交付边界。
- `DRAFT_PENDING_REVIEW`：证据只存在于独立 Draft PR，不能写入主线完成度。
- `PARTIAL`：主线只有部分字段、映射或框架，不能视为完整需求合同。
- `NEEDS_LIVE_EVIDENCE`：需要授权现场数据、真实账号、真实送达或真实状态变化。
- `NEEDS_HUMAN_DECISION`：需要人工决定许可、生产迁移、部署或有价值数据消费。
- `DEFERRED_BY_USER`：路线图明确暂缓，不作为当前 release 阻塞项。

## 需求矩阵

| requirement_id | 原需求 / 用户能力 | 生产入口 | `origin/main` 代码与离线证据 | 现场证据 / 授权边界 | 产品状态 | 剩余任务 |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-ACCOUNT-001 | 安全绑定 | `/妮姬 账号 绑定` | `main.py`、`web_service.py`、`storage.py`；`tests/test_core.py` 覆盖合成绑定会话、来源校验和脱敏 | 未读取真实账号；真实浏览器绑定需用户提供目标环境并明确授权 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 在授权环境做一次最小绑定链路核验，确认 cookie/key 不越界保存 |
| REQ-ACCOUNT-002 | 解绑 / 状态 | `/妮姬 账号`、`/妮姬 账号 解绑` | `main.py`、`storage.py`；核心测试覆盖状态、解绑和凭据错误语义 | 未对真实账号执行解绑或状态读取 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 授权后核对真实状态显示与解绑结果，不自动执行 |
| REQ-PROFILE-001 | `/妮姬 我的` 个人概览出图 | `/妮姬 我的` | 已合并 PR #7；`profile_builder.py`、`profile_card_renderer.py`；`docs/PROFILE_V2_ACCEPTANCE.md`、`tests/test_profile_v2.py`、`tests/test_profile_structured.py`，含缺失/异常值、分区归属、请求预算和合成 PNG | 未使用真实账号；真实字段兼容和现场图片未验收 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 授权后用真实账号核对字段合同；不能把合成预览当作现场证据 |
| REQ-CHAR-001 | 单条角色练度卡 / 资料卡 | `/妮姬 查询 练度 [角色名]`、`/妮姬 查询 资料 <角色名>` | `character_card_renderer.py`、`card_models.py` 已有渲染链；`tests/test_character_card_renderer.py` 覆盖残留词条清理；角色静态 registry 的后续补强在 Draft PR #11 | 未确认完整角色详情字段覆盖；不为未观察字段推断数值或公式 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`DRAFT_PENDING_REVIEW` | 审阅 PR #11 的静态 registry；真实字段仍需授权响应 |
| REQ-CAMPAIGN-001 | 主线历史 / 阵容查询 | `/妮姬 战役 [普通/困难] <关卡>` | `campaign_stage_resolver.py`、`campaign_history_builder.py`、`campaign_history_renderer.py`；`tests/test_campaign_history.py` 有合成合同；严格数值合同增强在 Draft PR #15 | 未宣称完整账号联调；未知关卡和上游覆盖仍需证据 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`DRAFT_PENDING_REVIEW` | 审阅 PR #15，补充已确认的章节/fixture；未知错误不得静默猜测 |
| REQ-TOWER-001 | 塔层静态资料 | `/妮姬 塔层 <塔名> <层数>` | `tower_registry.py`、`assets/tower_floors.json`、`tests/test_tower_registry.py`；输出明确是静态快照，不保证通关 | 不需要真实账号；静态资源来源/版本仍按快照管理 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE` | 仅在有授权素材或新快照时更新，不把静态值写成玩家进度 |
| REQ-RAID-001 | 联盟突袭 overview | `/妮姬 联盟突袭` | `client.py`、`union_raid_builder.py`、`union_raid_renderer.py`；`tests/test_union_raid.py`、`tests/test_raid_evidence.py` 覆盖响应范围和异常语义 | canonical identity、完整范围和多轮覆盖未现场确认 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 需要授权响应来确认 scope；不从返回记录数推断完整赛季 |
| REQ-RAID-002 | 联盟突袭 ranking | `/妮姬 联盟突袭 排名` | 主线只有基础查询边界；完整响应语义和排名加固在 Draft PR #8，含离线行为测试和 synthetic preview | 成员关系、分页、排名范围仍未现场确认 | `DRAFT_PENDING_REVIEW`；`NEEDS_LIVE_EVIDENCE` | 先审阅 PR #8；获得 canonical identity / scope 证据后再扩展 |
| REQ-RAID-003 | 联盟突袭“我的” | `/妮姬 联盟突袭 我的` | 主线未形成可宣称完成的个人出刀合同；相关数据模型受 Draft PR #8 约束 | `openid`、`member_id`、nickname 不能互相猜测；需要真实响应证据 | `NEEDS_LIVE_EVIDENCE` | 记录最小现场动作：授权账号、脱敏响应、确认 identity 关联和次数语义 |
| REQ-RAID-004 | 联盟突袭历史 | `/妮姬 联盟突袭 历史` | 主线没有完整历史赛季闭环；路线图将其与分页、覆盖和去重证据分开 | 历史端点、赛季覆盖和时间字段未确认 | `NEEDS_LIVE_EVIDENCE` | 先确认官方响应是否提供历史范围；没有合同时保持未实现 |
| REQ-CDK-001 | 单条 CDK | `/妮姬 兑换 <CDK>`、`/妮姬 兑换 历史` | `cdk_service.py`、`storage.py`、`main.py`；`tests/test_cdk.py` 覆盖超时 unknown、业务错误、取消和持久状态；真实兑换默认关闭 | 不自动消费有价值 CDK；真实兑换需用户明确确认具体码和环境 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_HUMAN_DECISION` | 仅在明确确认后做最小真实兑换；结果未确认时禁止重试 |
| REQ-CDK-002 | 批量 CDK | `/妮姬 兑换 批量 <CDK...>`、`/妮姬 兑换 可用` | 主线有串行、账号锁、失败中止、输入去重和 `action_runs` 持久幂等；`tests/test_cdk_persistence.py`、`tests/test_cdk_stale_runs.py` 覆盖重启复用、unknown 不重放、过期 running 隔离和可重试终态 | 不执行真实批量兑换，不读取真实历史 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_HUMAN_DECISION` | 仅在明确确认具体码和环境后做最小现场兑换；结果未确认时禁止重试 |
| REQ-ANN-001 | 公告查询 | `/妮姬 公告` | `announcement_service.py`、`announcement_sources.py`；`tests/test_announcements.py`；查询边界和深度重扫增强在 Draft PR #9 | 未访问真实 CMS；公开/合成 payload 不能证明线上源可用 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`DRAFT_PENDING_REVIEW` | 审阅 PR #9；现场只需在明确授权下验证来源，不发送消息 |
| REQ-ANN-002 | 日程查询 | `/妮姬 日程` | 与公告服务共用当前 source/cache 边界；离线测试覆盖时间解析和过期语义 | 未确认线上日程源的完整字段和时区语义 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 记录真实 source 的字段合同和时区证据，不把 fallback 当完整 CMS |
| REQ-ANN-003 | 自动推送 | `/妮姬 账号 汇总 开|关`、后台公告订阅 | `announcement_delivery.py`、`main.py`；`tests/test_announcement_delivery.py`、`tests/test_announcement_push_wiring.py` 覆盖持久去重/重启恢复 | 未向真实群或用户发送消息；送达证据需明确授权 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 现场仅验证目标会话、频率和失败回收；不能宣称 exactly-once |
| REQ-DAILY-001 | Check-in | `/妮姬 签到`、`/妮姬 签到 状态` | `main.py`、`client.py`、`storage.py`；`tests/test_daily_safety.py` 覆盖 intent、unknown 和不自动重放；写入默认关闭 | 未执行真实签到；状态变化需真实账号前后读取证据 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 授权后一次最小 write/read 现场核验；崩溃/unknown 不自动重试 |
| REQ-DAILY-002 | Like | 日常框架（未作为默认可用命令） | 主线没有可宣称完成的真实 Like 闭环；仅有受控状态框架和安全测试 | 真实 endpoint 和状态变化未确认 | `NEEDS_LIVE_EVIDENCE` | 先取得官方响应/写后读取证据；没有证据不接线 |
| REQ-DAILY-003 | Browse | 日常框架（未作为默认可用命令） | 主线没有可宣称完成的真实 Browse 闭环；不得用离线 payload 冒充 | 真实 endpoint 和状态变化未确认 | `NEEDS_LIVE_EVIDENCE` | 与 Like 分开确认 endpoint、前后状态和失败语义 |
| REQ-VOICE-001 | Poke Voice | `/妮姬 戳一戳 [角色名]` | `voice_audio.py`、`voice_pipeline.py`、`voice_resource_provider.py` 已有离线资源管线；`tests/test_voice_*.py` 覆盖预算、并发、取消、缓存和迟到发送禁止；动态接线/映射仍在 Draft PR #10/#13 | 未发送真实 QQ 音频；角色/皮肤映射和实际播放未确认 | `IMPLEMENTED / WIRED`（文本路径）；`DRAFT_PENDING_REVIEW`；`NEEDS_LIVE_EVIDENCE` | 分层审阅 resource/pipeline/lifecycle/delivery；必须取得真实播放授权后再声称完成 |
| REQ-SPINE-001 | 服务端 Spine 渲染 | 预渲染/角色卡资源链（生产入口未接线） | `spine_prerenderer.py` 有发现、队列、预算、缓存和预检查；`tests/test_spine_inspection.py`；技术 spike 在 Draft PR #12 | 未采用可授权生产 runtime，未做真实 server-side render 或 Linux benchmark | `SYNTHETIC_VERIFIED`；`NEEDS_HUMAN_DECISION` | 由人工决定 runtime/license，再做代表性素材 benchmark；第一张卡不能等待 Spine |
| REQ-DATA-001 | Equipment registry | 角色卡/`/妮姬 查询 练度` 数据 | 主线有 equipment 数据模型和安全渲染，但没有可宣称完整 registry；`tests/test_character_card_renderer.py` 只证明展示合同 | 未确认完整 equipment 字段和权威静态源 | `PARTIAL`；`DRAFT_PENDING_REVIEW` | 依观察到的字段补 registry；不推断未观测属性 |
| REQ-DATA-002 | Cube registry | Profile / 角色数据 | 主线没有独立完整 cube registry；未知数据保持中性或缺失 | 未确认 cube 属性和等级公式 | `PARTIAL`；`NEEDS_LIVE_EVIDENCE` | 先取得字段合同，再做本地静态映射和异常测试 |
| REQ-DATA-003 | Favorite Item | 角色资料/卡片（当前无独立完成入口） | 主线没有完整 Favorite Item 合同；Character Data V2 Draft PR #11 仅是后续审阅材料 | 未确认字段、稀有度和角色关系 | `DRAFT_PENDING_REVIEW`；`NEEDS_LIVE_EVIDENCE` | 审阅公开静态 registry，未知项不得显示伪造名称 |
| REQ-DATA-004 | Skill | `/妮姬 查询 资料 <角色名>`（字段覆盖受限） | 主线保留角色资料框架，未证明完整 skill registry；不对缺失字段补公式 | 未确认 skill 字段和版本覆盖 | `PARTIAL`；`NEEDS_LIVE_EVIDENCE` | 以实际观察到的字段为最小合同，补离线异常测试 |
| REQ-DATA-005 | Costume | 角色资源/角色资料 | `nikke_db_provider.py` 有 costume 映射和资源 cache key；完整公开 registry 在 Draft PR #11 | 未确认完整 skin 映射和资源授权 | `IMPLEMENTED`（基础映射）；`DRAFT_PENDING_REVIEW`；`NEEDS_LIVE_EVIDENCE` | 审阅静态映射和授权边界，不下载未授权资源 |
| REQ-GUIDE-001 | Guide 框架 | `/妮姬 攻略 [分类]` | `guide_registry.py` 保留来源、作者、许可、版本和分页校验；无授权素材时保持占位 | 路线图明确禁止自动抓第三方内容、下载图片或生成正式攻略 | `DEFERRED_BY_USER`；非当前 release 阻塞项 | 等用户提供/授权素材；不为填矩阵而接入第三方内容 |
| REQ-RELEASE-001 | 部署、升级、回滚 | Docker/Caddy、`/healthz`、离线运维脚本 | 主线已有基础部署与健康入口；备份、迁移、日志、清理、版本、Caddy、upgrade preflight 分别在 Draft PR #22–#30，均未进入 main | 未部署、未改 ruleset、未对生产 DB migration/rollback；需人工授权 | `DRAFT_PENDING_REVIEW`；`NEEDS_HUMAN_DECISION` | 审阅各独立 PR；生产升级前须有授权、备份、回滚演练和现场证据 |

## 当前验收结论

1. `/妮姬 我的` 的代码、命令接线、离线行为测试和合成图片证据已经在主线达到 `READY_OFFLINE`；真实账号兼容仍是 `NEEDS_LIVE_EVIDENCE`。
2. 公开 Draft PR #8–#30 不改变 `origin/main` 的产品状态；它们必须各自通过审阅和 CI 后才能重新计算主线矩阵。
3. 本矩阵没有执行真实账号读取、账号写入、消息发送、真实 CDK 消费、部署、生产 migration、rollback 或 ruleset 修改。
4. 下一步按优先级是：审阅 Draft PR；对 Raid identity/scope、Daily Like/Browse、Voice 实际播放、Spine runtime/license 收集最小授权证据；Guide 保持用户暂缓状态。

## 证据类型边界

合成 fixture、离线 payload、测试 PNG、公开只读资料、绿色 CI 和模块存在只能证明代码或离线合同的一部分。它们不能替代真实账号响应、真实写后状态、QQ 送达、生产部署、资源授权、数据库迁移或回滚证据。
