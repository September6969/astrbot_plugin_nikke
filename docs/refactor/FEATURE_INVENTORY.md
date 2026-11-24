# FEATURE_INVENTORY.md — NIKKE 综合助手全量功能盘点清单

> **盘点基线（2026-11-24）**：
> - `origin/main`：`71e664f`（已合入 PR #141 与 PR #142）
> - 本地提交备份：`9968a50`（worktree `E:/_codex_work/nikkehub-ds`，分支 `codex/nikkehub-on-pr141`）
> - 开放 Issue：`#143`（「接入并维护 NikkeHub 公开数据与单人突袭估伤」）
>
> **状态分类标准**：
> - `COMPLETE`：业务闭环且达到验收标准（同时区分“代码完成 / 自动化测试完成 / 真实环境验收完成”）
> - `PARTIAL`：已有实现但存在功能、规则、边界或持久化缺口
> - `BROKEN`：功能存在但当前存在阻断性缺陷导致核心场景不可正常使用
> - `BLOCKED`：受外部接口契约、数据授权许可、依赖或真实环境条件阻塞
> - `PLANNED`：尚未实现（归属 Phase 3–6）

---

## 一、既有核心功能（基于 `origin/main`）

### 1.1 账号系统

| ID | 功能名称 | 实现位置 | 命令与参数 | 数据来源 | 绑定与权限要求 | 输入/输出契约 | 测试覆盖 | 已知限制 | 真实环境验收 | 网页/群反馈 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 完整绑定 | `application/commands/account.py`, `features/account/application.py`, `integrations/web/{service,bind_template}.py`, `extension/*` | `/妮姬 账号 绑定`, `/nikke bind` | 扩展采集 BlaBlaLink Cookie & 上下文 | 默认仅私聊（`allow_group_bind=false`），需 HTTPS+反代 | 扩展提交 → 加密存 SQLite + 状态页轮询 | `test_bind_tutorial.py`, `test_binding_ui_accessibility.py`, `extension.test.cjs` | 需自建 HTTPS 与 `web_trusted_proxy_ip` 现场验证 | 历史主链已验；新反代限流待复验 | 工作台 / 仅私聊 | **COMPLETE** |
| `acct.lifecycle` | 绑定状态 / 换绑 / 解绑 / 凭据失效 | `core/storage.py`, `features/account/application.py`, `application/commands/errors.py` | `/妮姬 账号`, `/妮姬 账号 解绑`, `/nikke status\|unbind` | 本地 SQLite (`accounts`, `bind_sessions`) | 本人操作 | 脱敏状态；换绑更新 `binding_generation`/`binding_revision` 并保留 `action_runs` | `test_account_command_contract.py`, `test_storage_authorization_boundary.py` | 与 `9968a50` `growth_history` 联合使用时须做身份隔离（P0） | 离线+历史已验 | 工作台 / 否 | **COMPLETE** |
| `acct.renewal` | 实验性会话续期 & 自动续期 | `features/account/renewal.py`, `integrations/blablalink/session_renewal.py`, `application/commands/community_automation.py` | `/妮姬 账号 续期 [状态]`, `自动续期 开\|关` | BlaBlaLink 续期 + 扩展采集 `session_material` | 仅私聊 + `enable_daily_actions` + 独立授权 | `OperationResult`；24h 频控 + `UNKNOWN_AFTER_ACTION` 不重试 | `test_session_renewal.py`, `test_community_automation_commands.py` | 长期延长有效期尚未证实 | 否（纯 Mock） | 工作台只读 / 否 | **PARTIAL** |
| `acct.shiftypad` | ShiftyPad 只读绑定（来自 `9968a50`） | `features/shiftypad/*`, `integrations/shiftypad/official.py`, `integrations/web/shiftypad_service.py` | `/妮姬 我的妮姬 导入\|只读\|同步\|解绑` | 推测的 BlaBlaLink 公开 `User/GetUserProfile`（未实测） | 仅私聊发链接，绝无写权限；不作所有权证明 | 短时网页导入 → `shiftypad_readonly_v1` 快照 | `test_shiftypad_*.py`（纯 Mock） | 上游契约未经真实只读验证（BLOCKED）；网页端 token 非一次性、暴露于 URL 查询串且缺独立 CSRF/`frame-ancestors`（P0） | **否** | 工作台 / 否 | **BLOCKED** |

### 1.2 个人数据

| ID | 功能名称 | 实现位置 | 命令与参数 | 数据来源 | 绑定与权限要求 | 输入/输出契约 | 测试覆盖 | 已知限制 | 真实环境验收 | 网页/群反馈 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | `application/commands/profile.py`, `features/profile/*`, `templates/t2i/profile.html` | `/妮姬 我的`, `/nikke me\|progress` | BlaBlaLink `GetUserProfile` + `GetUserGamePlayerInfo` | 完整绑定 | `ProfileDashboardData` → T2I 图卡 + 文本回退 | `test_t2i_frontend.py`, `test_profile_v04_*` | 群聊触发会展示个人进度 | 是 | 工作台 / 确认分享 | **COMPLETE** |
| `char.roster` | 角色练度总览（含魔方/收藏品/词条摘要） | `application/commands/character.py`, `features/character/roster_ranking.py`, `templates/t2i/roster.html` | `/妮姬 查询 练度`, `/nikke roster` | BlaBlaLink `GetUserCharacters` + 详情 | 完整绑定 | 总表 DTO → T2I 图卡 + 文本回退 | `test_roster_t2i.py`, `test_t2i_render_gate.py` | `AUD-010` 23 次请求优化待真机批测确认 | 是 | 工作台 / 确认分享 | **COMPLETE** |
| `char.detail` | 单角色详细练度（装备/OL/技能/皮肤） | `features/character/{application,builder,stat_calculator,visual_resolver}.py`, `templates/t2i/character.html` | `/妮姬 查询 练度 <名>`, `/nikke character <name>` | BlaBlaLink 详情 + `overload_tiers.json` + Spine 资源 | 完整绑定 | 角色卡 DTO → 白色竖版 T2I 图卡 + 文本回退 | `test_character_pixel_calibration.py`, `test_spine_*` | 新角色/皮肤需同步 Spine 清单与 `face_anchors.json` | 是 | 工作台按需懒加载 / 确认分享 | **COMPLETE** |
| `growth.history` | 养成历史（来自 `9968a50`） | `features/growth/history.py`, `application/commands/{profile,character,growth}.py` | `/妮姬 养成历史 [清空]` | 监听 `profile`/`character` 成功查询写入本地 SQLite | 完整绑定 | 成长时间线 + 角色变化摘要 | `test_growth_history.py` | **P0 跨账号污染**：未按稳定游戏账号身份隔离；`清空` 漏清 `roster_growth` 且无并发反回写保护；缺失值转 `0`；同日覆盖 `changes`；无时间范围查询 | **否** | 工作台 / 确认分享 | **PARTIAL** |

### 1.3 战斗与攻略

| ID | 功能名称 | 实现位置 | 命令与参数 | 数据来源 | 绑定与权限要求 | 输入/输出契约 | 测试覆盖 | 已知限制 | 真实环境验收 | 网页/群反馈 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `combat.campaign` | 主线通关阵容 | `application/commands/campaign.py`, `features/campaign/*`, `templates/t2i/campaign.html` | `/妮姬 战役 <关> [普通\|困难]` | BlaBlaLink 关卡通关记录 + `campaign_stages.json` | 完整绑定 | `StageClearRecord` → 1600×900 图卡 + 文本回退 | `test_campaign_ui_statuses.py`, `test_t2i_campaign.py` | 仅展示上游返回的通关样本 | 是 | 工作台 / 可选 | **COMPLETE** |
| `combat.tower` | 企业塔静态资料 | `application/commands/tower.py`, `features/tower/*` | `/妮姬 塔层 <塔名> <层数>` | `assets/data/tower_floors.json` | 无 | 静态楼层资料文本 | 路由与单测覆盖 | 静态资料，非玩家进度 | 是 | 公共大厅 / 可选 | **COMPLETE** |
| `combat.char_info` | 角色基础资料 | `application/commands/character.py` (`info`) | `/妮姬 查询 资料 <名>`, `/nikke info <name>` | `character_master.json` | 无 | 基础资料文本 | `test_command_parser_and_help.py` | 未含技能倍率 | 是 | 公共大厅 / 可选 | **COMPLETE** |
| `combat.guide` | 本地授权攻略 | `application/commands/guide.py`, `features/guide/*` | `/妮姬 攻略 [分类] [页码]` | `assets/guides/registry.json` | 无 | 分页图文 + 授权/作者/过期提示 | `test_guide_application_contract.py` | 需维护本地授权素材 | 是 | 公共大厅 / 群发图 | **COMPLETE** |
| `combat.union_raid` | 联盟突袭（总览/排行/我的） | `application/commands/raid.py`, `features/raid/*`, `templates/t2i/union_*.html` | `/妮姬 突袭 [排名\|我的] [页码]` | BlaBlaLink 联盟突袭接口 | 完整绑定 | 3 类 T2I 战报卡 + 文本回退 | `test_t2i_frontend.py` | 不推断未返回的剩余刀数 | 是 | 工作台 / 确认分享 | **COMPLETE** |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 持有过滤 | `application/commands/arena.py`, `features/arena/*`, `templates/t2i/arena_*.html` | `/妮姬 竞技场 解队\|沙盒\|我的\|数据状态` | 内置模板与静态评分 + 私聊持有名单 | 沙盒无；持有过滤需完整绑定；`enable_arena` | P1–P5 推荐 T2I 卡片 + 文本 | `test_arena_core.py`, `test_arena_commands.py` | 静态模型不含实时技能/魔方/超频 | 离线通过 | 大厅+工作台 / 确认发卡 | **COMPLETE** |
| `combat.arena_web` | 竞技场临时网页（单/三队） | `integrations/arena/{sessions,web_routes}.py`, `templates/arena_web/*` | `/妮姬 竞技场 编辑\|三队\|结果` | 同上 + 会话草稿/幂等分析 API | 私聊发起；`enable_arena` + `arena_web_enabled` | 一次性 token → Cookie 会话 + JSON API + QQ 回查 | `test_arena_web.py`（含 320px Playwright） | 暂无一键回推来源群机制 | Playwright 通过 | 已是网页（复用底座） | **COMPLETE** |
| `combat.solo_raid` | 单人突袭五队编组与估伤（来自 `9968a50`） | `features/solo_raid/*`, `integrations/nikke_calc/engine.py`, `templates/t2i/solo_raid.html` | `/妮姬 单人突袭 [赛季\|编组\|阵容图\|保存\|我的\|队]` | 导入赛季 JSON + MIT `Jgaram/nikke-calc@67835ca` | 手工/沙盒无；账号/ShiftyPad 可选 | 5×5 互斥、爆裂检查、可选估伤、T2I 阵容图 | `test_solo_raid_{engine,five_teams,real_engine}.py` | **多处 P0/P1 缺陷**：Boss 弱点与属性写反；并发信号量未共享；透传 `os.environ` 密钥；`version_ok` 假阳性；漏查 `resource_id`；T2I 写死标签；无授权赛季 JSON 需合规移出内置 | 仅离线引擎 smoke | 大厅+工作台 / 确认发卡 | **PARTIAL** |

### 1.4 活动、社区、养成工具、娱乐与导航

| ID | 功能名称 | 实现位置 | 命令与参数 | 数据来源 | 绑定与权限要求 | 输入/输出契约 | 测试覆盖 | 已知限制 | 真实环境验收 | 网页/群反馈 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `event.calendar` | 活动日历与截止订阅 | `application/commands/calendar.py`, `features/calendar/*` | `/妮姬 日程 [7\|14\|30] [页]`, `刷新\|订阅\|状态\|取消订阅` | BlaBlaLink `GetCalendarDetail` | 无（不依赖公告推送开关） | 分页 T2I 日程卡；截止前 24h @本人一次 | `test_calendar_*.py` | 真实群 @ 推送待部署验收 | 模拟全过 | 大厅+工作台 / 是 | **COMPLETE** |
| `event.gacha_board` | 卡池与活动分类板（来自 `9968a50`） | `features/calendar/board.py` | `/妮姬 卡池 [卡池\|活动\|皮肤\|突袭]` | 复用官方日程快照 | 无 | 4 组文本 + 倒计时 | `test_calendar_board_view.py` | 按组过滤误计 `unclassified`；无 UP 概率字段；纯文本 | **否** | 大厅 / 是 | **PARTIAL** |
| `event.announcement` | 官方公告与订阅 | `application/commands/announcement.py`, `features/announcement/*` | `/妮姬 公告 [语言\|分类\|搜索\|诊断\|深度刷新\|订阅\|取消订阅]` | 官方 InformationFeeds | 订阅/刷新需管理员 + `enable_announcement_push` | 公告列表/诊断 + 推送 | `test_announcement_*.py` | 真实群推送待现场验收 | 模拟全过 | 大厅 / 是 | **COMPLETE** |
| `event.news_feeds` | 统一新闻/视频/日程订阅（来自 `9968a50`） | `features/announcement/feeds.py`, `integrations/announcement/youtube_atom.py` | `/妮姬 新闻 [订阅\|状态\|取消订阅]` | 公告/日程仓储 + 官方油管 Atom | 调度器常开（缺开关控制） | 个人分源推送 | `test_announcement_feeds.py`, `test_video_feed_source.py` | 与公告/日程形成三套订阅；重订阅异常丢 baseline；`reminder_hours` 死字段；缺开关门禁 | **否** | 工作台 / 可选 | **PARTIAL** |
| `comm.daily_tasks_cdk` | 社区签到 / 免费领奖 / 浏览点赞 / CDK | `application/commands/{daily,community_automation,cdk}.py` | `/妮姬 签到`, `日常 [任务]`, `兑换` | BlaBlaLink 社区/兑换 API | 完整绑定 + 写开关与独立授权 | 状态/执行；`UNKNOWN_AFTER_ACTION` 禁自动重试，需两步 `确认恢复` | `test_daily_*.py`, `test_community_automation_commands.py`, `test_cdk*.py` | 写操作需真实环境复验 | 模拟全过 | 工作台只读 / 仅私聊 | **COMPLETE** |
| `tool.counsel` | 咨询答案查询（来自 `9968a50`） | `features/counsel/bank.py` | `/妮姬 咨询 <妮姬> [关键词]` | 严格导入格式（需授权题库） | 无 | 来源题号 + 答案序号 + 选项顺序提示 | `test_counsel_bank.py` | `9968a50` 原内置文件为无开源许可且纯韩文（中文=0），必须移除内置并标 `BLOCKED` 等待合法中文题库 | **否** | 大厅 / 发简洁文本 | **BLOCKED / BROKEN** |
| `tool.sync_calc` | 同步器等级计算（来自 `9968a50`） | `features/sync/*`, `scripts/operations/update_sync_level_costs.py` | `/妮姬 同步器 [状态\|计算 ...]` | 可选导入成本表 / 手工三项累计成本 | 可选（`计算 账号`） | 资源需求、缺口、天数、预计日期、瓶颈 | `test_sync_level_calculator.py`, `test_public_source_updaters.py` | 缺 1–200 级成本与前哨日产/箱子辅助，命令行参数繁琐；不得在公开仓随仓分发无许可抓取表 | **否** | 大厅+工作台 / 发结果卡 | **PARTIAL** |
| `tool.overload` | 超限洗词条助手（来自 `9968a50`） | `features/overload_advice/advisor.py` | `/妮姬 洗词条 ...`, `洗词条模拟 ...` | 官方 `overload_tiers.json` + 可选导入推荐表 | 无（未接个人装备） | 保留/重洗建议与模拟结果 | `test_overload_advice.py` | 不计跨部位已有目标行数；低阶词条也盲锁；模拟每次仅洗 1 条且生产硬编码 `seed=0`；未接个人装备对比 | **否** | 大厅+工作台 / 发分析卡 | **PARTIAL** |
| `tool.wishlist` | 愿望单推荐（来自 `9968a50`） | `features/wishlist/advisor.py` | `/妮姬 愿望单 [收集\|均衡\|养成] [角色池]` | `character_master.json` + 可选持有名单 | 可选 | 候选名单与理由 | `test_wishlist_advisor.py` | 按爆裂而非企业分组、含 SR/R、160 墙错计 3 星 SR、排序键不匹配、手工不支持别名、缺卡池准入规则 | **否** | 大厅+工作台 / 发推荐卡 | **BROKEN** |
| `fun.tarot` | 塔罗（单抽/三张/今日/状态） | `application/commands/tarot.py`, `features/tarot/*` | `/妮姬 塔罗 [单抽\|三张\|今日\|状态\|帮助]` | 内置 78 张牌图文 | 无 | 牌图（逆位无损旋转缓存）+ 解读 | `test_tarot_service.py` | 每日塔罗绑定个人身份，大厅仅限随机抽牌 | 是 | 大厅随机+工作台每日 / 是 | **COMPLETE** |
| `fun.favorite_grid` | 本命九宫格 & 本命榜（来自 `9968a50`） | `features/favorite_grid/grid.py`, `ui/payloads/favorite_grid.py`, `templates/t2i/favorite_grid.html`, `ui/renderers/favorite_grid_png.py` | `/妮姬 九宫格 <9人>`, `/妮姬 本命榜` | `character_master.json` + 头像 + SQLite 投票 | 无 | 3×3 图片 + 人气榜 TOP 10 | `test_favorite_grid.py` | 存在双套布局且均损坏：Pillow 标题叠压第 1 格/未裁剪溢出/Linux 中文变方块；T2I 1080×1080 高度溢出裁底行；排行 N+1 读库 | **否** | 大厅 / 生成发图 | **BROKEN** |
| `fun.voice` | 戳一戳语音 & 语音设置 | `adapters/astrbot/voice_adapter.py`, `features/voice/*` | 戳一戳；`/妮姬 语音 [开\|关\|语言\|角色\|服装]` | 官方有证音频缓存 | 无（需 `ffmpeg`/`ffprobe`） | 语音消息 | `test_voice_*.py` | 依赖宿主机 `ffmpeg` | 是 | 大厅试听+工作台设置 / 直发 | **COMPLETE** |
| `nav.help` | 帮助导航与详解（PR #142） | `application/commands/help.py`, `features/help/*` | `/妮姬`, `/妮姬 帮助 [分类\|详解]` | `features/help/catalog.py` | 动态门禁 | 8 类用户入口 + 独立管理入口纯文本 | `test_help_detail.py`, `test_help_navigation_v2.py` | 待融合 `9968a50` 新主题并在 Phase 3 升级为统一目录 | CI 全过 | 统一底座 / 是 | **COMPLETE**（既有基线） |
| `misc.public_share` | 公开 UID 声明 / 第三方分享 ID / 手工资料（来自 `9968a50`） | `features/identity/public_profile.py`, `integrations/nikke_api/share_profile.py` | `/妮姬 uid`, `我的妮姬 资料\|分享\|手工` | `nikke-api.pages.dev` + 本地手工 | 无（需加默认关闭管理员开关与传输披露） | 声明 / 只读字段 | `test_public_share_profile.py`, `test_public_uid_profile.py` | 向第三方服务发送数据缺管理员配置开关与用户明确告知 | **否** | 工作台辅助 / 否 | **PARTIAL** |
