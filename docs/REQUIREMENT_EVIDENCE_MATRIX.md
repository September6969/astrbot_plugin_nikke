# NIKKE 需求证据矩阵

更新时间：2026-09-11。

本矩阵按路线图第 4、5、54、55 节建立；历史条目保留其当时基线，当前接管主题基线为已核验的 `origin/main` `e4a9ff9867dc9a92c203484c748562e4c0a7f1d0`。开放 PR 的代码不视为已进入主线；表中明确标注的 PR 只表示可审阅的后续证据。

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
| REQ-RAID-003 | 联盟突袭“我的” | `/妮姬 联盟突袭 我的` | `raid_participants.py` 按绑定账号已有的稳定 `game_openid` 精确筛选当前响应；`tests/test_raid_participants.py`、`tests/test_union_raid.py` 覆盖身份筛选、畸形记录、空结果和命令路由；不新增请求 | 未访问真实账号；`game_openid` 与响应 `openid` 的现场关联、完整范围和次数语义仍需确认 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 记录最小现场动作：授权账号、脱敏响应，确认 identity 关联和响应覆盖；不得把“条返回记录”改称实际出刀次数 |
| REQ-RAID-004 | 联盟突袭历史 | `/妮姬 联盟突袭 历史` | 主线没有完整历史赛季闭环；路线图将其与分页、覆盖和去重证据分开 | 历史端点、赛季覆盖和时间字段未确认 | `NEEDS_LIVE_EVIDENCE` | 先确认官方响应是否提供历史范围；没有合同时保持未实现 |
| REQ-CDK-001 | 单条 CDK | `/妮姬 兑换 <CDK>`、`/妮姬 兑换 历史` | `cdk_service.py`、`storage.py`、`main.py`；`tests/test_cdk.py` 覆盖超时 unknown、业务错误、取消和持久状态；真实兑换默认关闭 | 不自动消费有价值 CDK；真实兑换需用户明确确认具体码和环境 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_HUMAN_DECISION` | 仅在明确确认后做最小真实兑换；结果未确认时禁止重试 |
| REQ-CDK-002 | 批量 CDK | `/妮姬 兑换 批量 <CDK...>`、`/妮姬 兑换 可用` | 主线有串行、账号锁、失败中止、输入去重和 `action_runs` 持久幂等；`tests/test_cdk_persistence.py`、`tests/test_cdk_stale_runs.py` 覆盖重启复用、unknown 不重放、过期 running 隔离和可重试终态 | 不执行真实批量兑换，不读取真实历史 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_HUMAN_DECISION` | 仅在明确确认具体码和环境后做最小现场兑换；结果未确认时禁止重试 |
| REQ-ANN-001 | 公告查询 | `/妮姬 公告` | `announcement_service.py`、`announcement_sources.py`；`tests/test_announcements.py`；查询边界和深度重扫增强在 Draft PR #9 | 未访问真实 CMS；公开/合成 payload 不能证明线上源可用 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`DRAFT_PENDING_REVIEW` | 审阅 PR #9；现场只需在明确授权下验证来源，不发送消息 |
| REQ-ANN-002 | 日程查询 | `/妮姬 日程` | 与公告服务共用当前 source/cache 边界；离线测试覆盖时间解析和过期语义 | 未确认线上日程源的完整字段和时区语义 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 记录真实 source 的字段合同和时区证据，不把 fallback 当完整 CMS |
| REQ-ANN-003 | 自动推送 | `/妮姬 账号 汇总 开|关`、后台公告订阅 | `announcement_delivery.py`、`main.py`；`tests/test_announcement_delivery.py`、`tests/test_announcement_push_wiring.py` 覆盖持久去重/重启恢复 | 未向真实群或用户发送消息；送达证据需明确授权 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 现场仅验证目标会话、频率和失败回收；不能宣称 exactly-once |
| REQ-DAILY-001 | Check-in | `/妮姬 签到`、`/妮姬 签到 状态` | `main.py`、`client.py`、`storage.py`；`tests/test_daily_safety.py` 覆盖 intent、unknown 和不自动重放；写入默认关闭 | 未执行真实签到；状态变化需真实账号前后读取证据 | `IMPLEMENTED / WIRED / SYNTHETIC_VERIFIED`；`NEEDS_LIVE_EVIDENCE` | 授权后一次最小 write/read 现场核验；崩溃/unknown 不自动重试 |
| REQ-DAILY-002 | Like | 日常框架（未作为默认可用命令） | 主线没有可宣称完成的真实 Like 闭环；仅有受控状态框架和安全测试 | 真实 endpoint 和状态变化未确认 | `NEEDS_LIVE_EVIDENCE` | 先取得官方响应/写后读取证据；没有证据不接线 |
| REQ-DAILY-003 | Browse | 日常框架（未作为默认可用命令） | 主线没有可宣称完成的真实 Browse 闭环；不得用离线 payload 冒充 | 真实 endpoint 和状态变化未确认 | `NEEDS_LIVE_EVIDENCE` | 与 Like 分开确认 endpoint、前后状态和失败语义 |
| REQ-VOICE-001 | Poke Voice | `/妮姬 戳一戳 [角色名]` | `voice_audio.py`、`voice_mapping.py`、`voice_pipeline.py`、`voice_resource_provider.py`、`voice_encoder.py`；PR #55 接入本地 → 证据映射动态资源 → 文本回退，Voice 专项行为测试与 Record 序列化测试覆盖预算、并发、取消、缓存、格式和生命周期 | `assets/voice_poke_map.json` 当前为空；未发送真实 QQ 音频，角色/皮肤映射、资源授权和实际播放未确认 | `IMPLEMENTED / WIRED / READY_OFFLINE`; `NEEDS_LIVE_EVIDENCE` | 仅在取得精确角色/服装/locale 映射和授权资源后补清单；恢复 `ssh serv` 后做最小 NapCat/OneBot Record 现场验证，不采集秘密 |
| REQ-SPINE-001 | 服务端 Spine 渲染 | 角色卡资源链中的正式异步编排入口；cache hit 可供 portrait 使用，miss 不同步等待 | `spine_prerenderer.py`、`spine_runtime_worker.py`、`spine_runtime_config.py`、`runtime/spine_worker/`；PR #52/#53 已合并；worker RGBA/路径/超时测试与 formal backend 测试通过，Docker 构建已进入自动化检查 | 远端 `serv` 的隔离 Docker 编译会话曾在 SSH banner 阶段超时，尚未取得编译、合法 bundle 实渲染或 benchmark 证据；runtime 与 NIKKE 素材许可仍需逐项核验 | `READY_OFFLINE`（编排、adapter、构建合同）；`NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION`（服务器实构建、素材、许可、现场） | 恢复 SSH 后重试隔离 Docker 构建；只用合法测试 bundle 做 headless/benchmark；不改现有容器，不把公开 URL 当分发授权 |
| REQ-DATA-001 | Equipment registry | 角色卡/`/妮姬 查询 练度` 数据 | 主线有 `StaticDataRegistry` 精确 ID、manifest 来源/hash 合同和安全渲染；完整上游覆盖仍未声称 | 未确认完整 equipment 字段和权威静态源 | `IMPLEMENTED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 仅在有来源证据时扩充映射；不推断未观测属性 |
| REQ-DATA-002 | Cube registry | Profile / 角色数据 | 主线有 `StaticDataRegistry` 精确 ID、manifest 来源/hash 合同和未知 fallback；公式/完整属性不在本合同 | 未确认 cube 属性和等级公式 | `IMPLEMENTED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 先取得字段合同，再补有证据的静态映射 |
| REQ-DATA-003 | Favorite Item | 角色资料/卡片（当前无独立完成入口） | 主线有 `StaticDataRegistry` 精确 ID、manifest 来源/hash 合同和未知 fallback；未宣称完整 Favorite Item 数据库 | 未确认字段、稀有度和角色关系 | `IMPLEMENTED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` | 仅补有来源证据的映射，未知项不得显示伪造名称 |
| REQ-DATA-004 | Skill | `/妮姬 查询 资料 <角色名>`（字段覆盖受限） | 主线保留角色资料框架，未证明完整 skill registry；不对缺失字段补公式 | 未确认 skill 字段和版本覆盖 | `PARTIAL`；`NEEDS_LIVE_EVIDENCE` | 以实际观察到的字段为最小合同，补离线异常测试 |
| REQ-DATA-005 | Costume | 角色资源/角色资料 | `nikke_db_provider.py` 有 costume-aware cache key；PR #53/当前 registry 合同保持 `costumes.json` 空表，精确 ID/value 校验、manifest 来源/hash 和 unknown/invalid 隔离已覆盖 | 未确认完整 skin 映射、CDN 存在性和资源授权 | `IMPLEMENTED / READY_OFFLINE`（合同）；`NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION`（映射、素材、授权） | 只在 API costume ID → Nikke-DB asset ID 来源证据齐全时补映射，不回退默认服装 |
| REQ-GUIDE-001 | Guide 框架 | `/妮姬 攻略 [分类]` | `guide_registry.py` 保留来源、作者、许可、版本和分页校验；无授权素材时保持占位 | 路线图明确禁止自动抓第三方内容、下载图片或生成正式攻略 | `DEFERRED_BY_USER`；非当前 release 阻塞项 | 等用户提供/授权素材；不为填矩阵而接入第三方内容 |
| REQ-RELEASE-001 | 部署、升级、回滚 | Docker/Caddy、`/healthz`、离线运维脚本 | 主线已有 `deploy/Caddyfile`、Caddy compose、`/healthz` readiness、backup、upgrade preflight、cache cleanup、shutdown、日志隐私和配置验收；`docs/RELEASE_CHECKLIST.md` 与 `docs/FINAL_ACCEPTANCE_REPORT.md` 汇总收口 | `ssh serv` 本次在 SSH banner 阶段超时；未部署、未改 ruleset、未对生产 DB migration/rollback；需人工授权 | `IMPLEMENTED / READY_OFFLINE`；`NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION` | 恢复 SSH 后执行只读容器/健康/日志检查；生产升级前须有授权、备份、回滚演练和现场证据 |

## 当前验收结论

1. `/妮姬 我的` 的代码、命令接线、离线行为测试和合成图片证据已经在主线达到 `READY_OFFLINE`；真实账号兼容仍是 `NEEDS_LIVE_EVIDENCE`。
2. 公开 Draft PR #8–#30 不改变 `origin/main` 的产品状态；它们必须各自通过审阅和 CI 后才能重新计算主线矩阵。
3. 本矩阵没有执行真实账号读取、账号写入、消息发送、真实 CDK 消费、部署、生产 migration、rollback 或 ruleset 修改。
4. 主题 PR #52–#55 已按依赖顺序合并；当前只剩现场证据、许可与人工发布决定，不把它们伪装成离线完成。既有模块回归和部署准备已由主线代码、验收文档和最终清单收口。

## 证据类型边界

合成 fixture、离线 payload、测试 PNG、公开只读资料、绿色 CI 和模块存在只能证明代码或离线合同的一部分。它们不能替代真实账号响应、真实写后状态、QQ 送达、生产部署、资源授权、数据库迁移或回滚证据。

## PR #79 接管续作增补（2026-09-11）

以下记录只覆盖现有 PR #79 的工作树，不改写上方历史主线结论：

| 范围 | 当前离线实现 | 离线证据 | 现场边界 |
| --- | --- | --- | --- |
| Profile Dashboard v0.4 | `client.py` 四路 Profile/Daily 读取、`profile_builder.py` 结构化字段、`profile_card_renderer.py` TODAY/RECYCLE/COLLECTION/RESOURCES 分区 | 新增 Profile/Daily/partial/height 行为测试；合成前后 PNG 已查看 | 真实账号字段兼容和 QQ 图片送达仍未在本轮确认 |
| Local Nikke-db Spine | `local_spine_resolver.py`、manifest v2 schema、维护期 sparse checkout/预渲染脚本；正式头像热路径禁 HTTP/Worker/FB | 多纹理、BOM、4.0/4.1、损坏图片、路径越界、symlink escape、manifest hash 行为测试 | `serv` 本地 checkout 全量预渲染、生产 runtime 许可与现场稳定性仍需核验 |
| Campaign capture | `scripts/capture_campaign_history.py` 只处理 NORMAL/HARD，支持状态、限流、resume/force、脱敏 JSONL、TID/Costume inventory | 捕获、隐私、回放、限流退避和静态目标过滤测试 | 真实已授权账号快照与最小现场请求尚未执行 |

本增补的状态上限为 `READY_OFFLINE`；不把测试 fixture、合成图或静态 schema 写成真实联调、QQ 送达、部署或资源授权。
