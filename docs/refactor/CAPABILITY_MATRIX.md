# CAPABILITY_MATRIX.md — 能力可用性矩阵与双入口收敛基线

> **基线**：PR #150 (`integration/phase2-candidate` @ `164d3b6`)  
> **严格可用性分级**：
> - **`READY`**：逻辑闭环、内置合法完整数据或可完全自主计算，且已在 Linux CI（及/或实机验证）通过自动化验收。
> - **`DEGRADED`**：主链路可用且安全降级，但因缺少无许可外部数据、需运行机额外准备外部仓库，或仅在离线/Mock 下验证尚未在真实玩家账号/QQ 宿主机全链跑通，部分高阶能力需手工参数或外部导入。
> - **`BLOCKED`**：缺少合法授权中文数据或未经授权实号验证上游匿名接口契约，默认关闭或显式阻断，不对外宣称可用。

---

## 一、25 项能力总表

| ID | 能力名称 | QQ 命令入口 | 所需绑定层级 | 关键配置开关（`core/config.py`） | 当前分级 | 自动化验证范围 | 降级策略 / 真实环境待验 | Phase 3–7 规划入口 |
|---|---|---|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 完整绑定 | `/妮姬 账号 绑定`, `/nikke bind` | 无（私聊） | `allow_group_bind` (false), `web_trusted_proxy_ip`, `binding_api_key` | **READY** | Extension Node + Linux CI 全过 | 生产反代 HTTPS/限流需上线现场复验 | 工作台接入 |
| `acct.lifecycle` | 绑定状态 / 换绑 / 解绑 / 凭据失效 | `/妮姬 账号`, `账号 解绑`, `/nikke status\|unbind` | 本人记录 | — | **READY** | Linux CI 全过 | 多账号长周期换绑观察 | 工作台个人状态 |
| `acct.renewal` | 实验性会话续期 & 自动续期 | `/妮姬 账号 续期 [状态]`, `自动续期 开\|关` | 完整绑定（私聊） | `enable_daily_actions` (false) | **DEGRADED** | 离线 Mock + 未知态保护通过 | 长期延长有效期尚未经真实长周期实号证实 | 工作台只读状态 |
| `acct.shiftypad` | ShiftyPad 只读导入绑定 | `/妮姬 我的妮姬 导入\|只读\|同步\|解绑` | 仅只读导入（私聊） | `enable_shiftypad_readonly` (false) | **BLOCKED** | 网页 Cookie/CSRF/`access_log=None` + Caddy `log_skip` 实测通过 | 缺授权测试账号验证 `User/GetUserProfile` 上游契约，保持默认关闭 | 待解封后接入工作台 |
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | `/妮姬 我的`, `/nikke me\|progress` | 完整绑定 | — | **READY** | Playwright + T2I Linux CI 通过 | 真实账号线上拉取现场确认 | 工作台首页 |
| `char.roster` | 角色练度总览 | `/妮姬 查询 练度`, `/nikke roster` | 完整绑定 | — | **READY** | T2I Linux CI 全过 | `AUD-010` 23 次请求批量界面需实号复测 | 工作台总览 |
| `char.detail` | 单角色详细练度（OL/技能/皮肤/Spine） | `/妮姬 查询 练度 <名>`, `/nikke character <name>` | 完整绑定 | `spine_runtime_version` (4.0), `spine_worker_timeout` (4) | **READY** | Spine 4.0/4.1 官方 Worker CI + 白卡实图全过 | 新实装皮肤需同步维护清单 | 工作台详情页 |
| `growth.history` | 养成历史快照与差异 | `/妮姬 养成历史 [清空]` | 完整绑定 + 身份隔离 | — | **READY** | `(actor, identity)` 隔离 + 并发代数回写全过 | 真实多号换绑生产验证 | 工作台时间线 |
| `combat.campaign` | 主线通关阵容 | `/妮姬 战役 <关> [普通\|困难]` | 完整绑定 | — | **READY** | T2I Linux CI 全过 | 实号通关样本拉取 | 工作台 / 大厅辅助 |
| `combat.tower` | 企业塔静态资料 | `/妮姬 塔层 <塔名> <层数>` | 无 | — | **READY** | Linux CI 全过 | — | 公共大厅 |
| `combat.char_info` | 角色基础资料 | `/妮姬 查询 资料 <名>`, `/nikke info <name>` | 无 | `custom_character_aliases` | **READY** | Linux CI 全过 | — | 公共大厅 |
| `combat.guide` | 本地授权攻略 | `/妮姬 攻略 [分类] [页码]` | 无 | — | **READY** | Linux CI 全过 | 需维护本地合规授权图文 | 公共大厅 |
| `combat.union_raid` | 联盟突袭（总览/排行/我的） | `/妮姬 突袭 [排名\|我的] [页码]` | 完整绑定 | — | **READY** | T2I Linux CI 全过 | 实号联盟数据 | 工作台 |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 持有过滤 | `/妮姬 竞技场 解队\|沙盒\|我的\|数据状态` | 沙盒无；持有过滤需完整绑定 | `enable_arena` (false) | **READY** | Linux CI 全过 | 静态评分仅供策略参考 | 大厅 + 工作台 |
| `combat.arena_web` | 竞技场临时网页（单/三队） | `/妮姬 竞技场 编辑\|三队\|结果` | 同上（私聊发链接） | `enable_arena` (false), `arena_web_enabled` (false) | **READY** | Linux CI Chromium Playwright 端到端全过 | 待后续统一底座样式 | 已有网页复用底座 |
| `combat.solo_raid` | 单人突袭五队编组与估伤 | `/妮姬 单人突袭 [赛季\|编组\|阵容图\|保存\|我的\|队]` | 手工无；`账号` 需绑定 | `solo_raid_season_path`, `solo_raid_engine_path` | **DEGRADED** | 真实 `nikke-calc@67835ca` 跑出数值 + 真实子进程强杀/流截断/生命周期测试全过 | 缺随仓赛季 JSON（不内置无许可数据）；需部署机先克隆 `67835ca` 与导入合规赛季 JSON 后完整可用，否则安全降级为无估伤编组 | 大厅沙盒 + 工作台 |
| `event.calendar` | 活动日历与 24h 截止提醒 | `/妮姬 日程 [7\|14\|30] [页]`, `刷新\|订阅\|状态\|取消订阅` | 无 | — | **READY** | Linux Playwright + 订阅状态机全过 | 真实 QQ 群 `@` 推送待宿主机实测 | 大厅 + 工作台订阅 |
| `event.gacha_board` | 卡池与活动分类板 | `/妮姬 卡池 [卡池\|活动\|皮肤\|突袭]` | 无 | — | **READY** | Linux CI + `unclassified` 计分修复全过 | 线上实时活动拉取 | 公共大厅 |
| `event.announcement` | 官方公告查询与全群广播订阅 | `/妮姬 公告 [语言\|分类\|搜索\|诊断\|深度刷新\|订阅\|取消订阅]` | 查询无；订阅/刷新需管理员 | `enable_announcement_push` (false) | **READY** | Linux CI 全过 | 真实 QQ 群广播推送待宿主机验收 | 公共大厅 |
| `event.news_feeds` | 个人新闻/视频/日程订阅 | `/妮姬 新闻 [订阅\|状态\|取消订阅]` | 无（按会话+用户本人隔离） | — | **READY** | 故障重订阅保护基线 + 并发去重 + 跨渠道隔离全过 | YouTube Atom 实网与 QQ 主动发信待宿主机验收 | 工作台订阅管理 |
| `comm.daily_tasks_cdk` | 社区签到 / 领奖 / 浏览点赞 / CDK | `/妮姬 签到`, `日常 [任务]`, `兑换` | 完整绑定 + 独立写授权 | `enable_daily_actions` (false), `enable_cdk_redemption` (false) | **DEGRADED** | 离线 Mock + 崩溃/超时 `UNKNOWN_AFTER_ACTION` 防护全过 | 真实账号写操作尚未（亦禁止盲测）真实提交 | 工作台只读状态 |
| `tool.counsel` | 咨询答案检索 | `/妮姬 咨询 <妮姬> [关键词]` | 无 | `counsel_bank_path` | **BLOCKED** | 检索器与导入器（带 `license` 校验）单测全过 | 未找到合法授权中文题库，默认明确提示未导入并阻断查询 | 导入合法题库后进大厅 |
| `tool.sync_calc` | 同步器升级/库存可升/瓶颈计算 | `/妮姬 同步器 [状态\|计算 ...]` | 可选（`计算 账号`） | `sync_level_cost_table_path` | **DEGRADED** | 可升计算 + 覆盖提示 + `validate_external_data.py` 校验全过 | 未内置无许可成本表；缺失时降级为「手工三项累计成本」模式且不推测未知等级 | 大厅 + 工作台 |
| `tool.overload` | 超限洗词条建议与概率模拟 | `/妮姬 洗词条 ...`, `洗词条模拟 ...` | 可选（`账号[:角色]`） | `overload_recommendations_path` | **DEGRADED** | 跨 4 部位累计 + `SystemRandom` 同件重洗 + 账号对比单测全过 | 官方 `overload_tiers.json` 完备，但未内置无许可角色推荐预设表（降级为命令行自定义目标词条） | 大厅 + 工作台 |
| `tool.wishlist` | 愿望单推荐 | `/妮姬 愿望单 [收集\|均衡\|养成] [角色池]` | 可选（读取账号 SSR） | —（叠加 `data_dir/wishlist-pool-eligibility.json`） | **READY** | 171 SSR 准入表 + Fail-closed `unknown` 拒绝 + 企业 5 席 + 160 墙全过 | 后续新版本新卡上线时需定期核对并更新准入表 | 大厅 + 工作台 |
| `fun.tarot` | 妮姬塔罗 | `/妮姬 塔罗 [单抽\|三张\|今日\|状态\|帮助]` | 今日牌绑定本人身份 | — | **READY** | Linux 完整 `assets/tarot` CI 全过 | — | 大厅随机 + 工作台每日 |
| `fun.favorite_grid` | 本命九宫格 T2I 图卡 & 人气榜 | `/妮姬 九宫格 <9人>`, `/妮姬 本命榜` | 无（每人 1 票可覆盖） | — | **READY** | 1080×1080 Edge 视觉验收 + O(1) `COUNTS_KEY` + Linux CI 全过 | 携带真实本地立绘图的 T2I 端到端渲染待部署机有全量资源验收 | 公共大厅 |
| `fun.voice` | 戳一戳语音 & 语音设置 | 戳一戳；`/妮姬 语音 [开\|关\|语言\|角色\|服装]` | 无 | `voice_dynamic_enabled` (true) | **READY** | Linux CI 全过 | 宿主机需安装 `ffmpeg`/`ffprobe` | 大厅试听 + 工作台设置 |
| `nav.help` | 帮助导航与分类详解 | `/妮姬`, `/妮姬 帮助 [分类\|详解]` | 动态按配置裁剪 | — | **READY** | Linux CI 全过 | — | 统一目录底座 |
| `misc.public_share` | 公开 UID 声明 / 第三方分享资料 / 手工资料 | `/妮姬 uid`, `我的妮姬 资料\|分享\|手工` | 无（不作账号归属证明） | `enable_public_share_api` (false) | **DEGRADED** | 默认关闭开关、外传提示及 `确认` 门禁测试全过 | 第三方 `nikke-api.pages.dev` 默认关闭，开启前需运营者确认外传告知 | 工作台辅助 |
