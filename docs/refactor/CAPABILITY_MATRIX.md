# CAPABILITY_MATRIX.md — 能力可用性矩阵与双入口收敛基线

> **代码与实测基线**：PR [#150](https://github.com/September6969/astrbot_plugin_nikke/pull/150) (`integration/phase2-candidate` @ `e749746`，含后续文档同步提交)  
> **双维分层口径（严禁混同）**：
> - **代码状态（Code Ready）**：
>   - `READY`：代码闭环、内置合法完整数据或可自主计算，静态门禁与自动化测试完备。
>   - `DEGRADED`：主链路已实现且具备明确安全降级，但因缺无许可外部数据、需运行机外部仓或高风险写操作默认关闭而功能受限。
>   - `BLOCKED`：缺合法授权中文题库或未验证上游匿名接口契约，默认阻断/关闭。
> - **真实环境验收（Real-Env Acceptance，详见 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)）**：`PASS` / `DEGRADED` / `BLOCKED` / `NOT_TESTED`（仅依据 `ssh serv` 隔离只读实测记账）。

---

## 一、30 项能力总表

| ID | 能力名称 | QQ 命令入口 | 所需绑定层级 | 关键配置开关（`core/config.py`） | 代码状态 | 自动化 CI | 真实环境验收 | 降级与外部边界说明 | Phase 3–7 规划入口 |
|---|---|---|---|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 完整绑定 | `/妮姬 账号 绑定`, `/nikke bind` | 无（私聊） | `allow_group_bind` (false), `web_trusted_proxy_ip`, `binding_api_key` | **READY** | Extension Node + Linux CI 全过 | **PASS**（监听生命周期；未重绑覆盖实号） | 宿主机 `Caddyfile` 启用 ShiftyPad 前须同步 `/shiftypad/*` 跳日志规则 | 工作台接入 |
| `acct.lifecycle` | 绑定状态 / 换绑 / 解绑 / 凭据失效 | `/妮姬 账号`, `账号 解绑`, `/nikke status\|unbind` | 本人记录 | — | **READY** | Linux CI 全过 | **PASS**（`***9910` 有效读出；`***0455` 识别 `CookieExpired`） | 实际解绑/换绑写操作按约束仅离线验证 | 工作台个人状态 |
| `acct.renewal` | 实验性会话续期 & 自动续期 | `/妮姬 账号 续期 [状态]`, `自动续期 开\|关` | 完整绑定（私聊） | `enable_daily_actions` (false) | **DEGRADED** | 离线 Mock + 未知态保护通过 | **NOT_TESTED** | 约束禁止实号写测试，长期延寿待后续人工授权确认 | 工作台只读状态 |
| `acct.shiftypad` | ShiftyPad 只读导入绑定 | `/妮姬 我的妮姬 导入\|只读\|同步\|解绑` | 仅只读导入（私聊） | `enable_shiftypad_readonly` (false) | **BLOCKED** | Web CSRF/`access_log=None` + Caddy 配置实测通过 | **BLOCKED** | 部署机无 ShiftyPad 测试凭据，维持默认关闭 | 待解封后接入工作台 |
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | `/妮姬 我的`, `/nikke me\|progress` | 完整绑定 | — | **READY** | Playwright + T2I Linux CI 通过 | **PASS**（`profile.png` `1080×3148`） | 普通新章 `ID 6050044` 未映射时明确标「未映射」 | 工作台首页 |
| `char.roster` | 角色练度总览 | `/妮姬 查询 练度`, `/nikke roster` | 完整绑定 | — | **READY** | T2I Linux CI + 重试单测全过 | **DEGRADED**（26/2 请求含限流单次重试，`roster.png` 清晰） | 上游突发限流偶发 2/20 详情降级并可于热查询补齐 | 工作台总览 |
| `char.detail` | 单角色详细练度（OL/技能/皮肤/Spine） | `/妮姬 查询 练度 <名>`, `/nikke character <name>` | 完整绑定 | `spine_runtime_version` (4.0), `spine_worker_timeout` (4) | **READY** | Spine 4.0/4.1 官方 Worker CI + 白卡实图全过 | **PASS**（`character.png` `1600×2400`） | 小红帽 104 阶 OL 精确渲染；冷网超 6s 预算时安全降级剪影 | 工作台详情页 |
| `growth.history` | 养成历史快照与差异 | `/妮姬 养成历史 [清空]` | 完整绑定 + 身份隔离 | — | **READY** | `(actor, identity)` 隔离 + 并发代数回写全过 | **PASS**（9 项字段实盘写入读出） | 按规范以绑定身份键隔离跨号数据 | 工作台时间线 |
| `combat.campaign` | 主线通关阵容 | `/妮姬 战役 <关> [普通\|困难]` | 完整绑定 | — | **READY** | T2I Linux CI 全过 | **PASS**（`campaign.png` `1600×900`） | 1 次 HTTP 查得 5 人阵容（`25,025` 战力）并完整渲染 | 工作台 / 大厅辅助 |
| `combat.tower` | 企业塔静态资料 | `/妮姬 塔层 <塔名> <层数>` | 无 | — | **READY** | Linux CI 全过 | **PASS** | 本地静态表精准输出标准战力 `252,600` | 公共大厅 |
| `combat.char_info` | 角色基础资料 | `/妮姬 查询 资料 <名>`, `/nikke info <name>` | 无 | `custom_character_aliases` | **READY** | Linux CI 全过 | **PASS** | 载入 207 条官方目录，基础字段齐全 | 公共大厅 |
| `combat.guide` | 本地授权攻略 | `/妮姬 攻略 [分类] [页码]` | 无 | — | **READY** | Linux CI 全过 | **PASS** | 准确输出本地 6 张授权 PNG 与原作者版权说明 | 公共大厅 |
| `combat.union_raid` | 联盟突袭（总览/排行/我的） | `/妮姬 突袭 [排名\|我的] [页码]` | 完整绑定 | — | **READY** | T2I Linux CI 全过 | **PASS**（`union_*.png` 3 张全部合格） | 4 请求拉取第 44 季 85 条记录，排名/我的均复用缓存（0 请求） | 工作台 |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 持有过滤 | `/妮姬 竞技场 解队\|沙盒\|我的\|数据状态` | 沙盒无；持有过滤需完整绑定 | `enable_arena` (false) | **READY** | Linux CI 全过 | **PASS**（`arena_matchup.png` & `arena_three_teams.png`） | 静态基线，已过滤 5 名未映射新角并标注珍藏推测边界 | 大厅 + 工作台 |
| `combat.arena_web` | 竞技场临时网页（单/三队） | `/妮姬 竞技场 编辑\|三队\|结果` | 同上（私聊发链接） | `enable_arena` (false), `arena_web_enabled` (false) | **READY** | Linux CI Chromium Playwright 端到端全过 | **NOT_TESTED** | 隔离测试停用公网网页，留由 Playwright CI 验证 | 已有网页复用底座 |
| `combat.solo_raid` | 单人突袭五队编组与估伤 | `/妮姬 单人突袭 [赛季\|编组\|阵容图\|保存\|我的\|队]` | 手工无；`账号` 需绑定 | `solo_raid_season_path`, `solo_raid_engine_path` | **DEGRADED** | 真实 `67835ca` + Python 3.12/3.13 进程树回收全过 | **DEGRADED**（五队+真实 `nikke-calc@67835ca` 计算 `1,813,859,815` 并出图 `PASS`；缺未导入赛季 JSON） | 部署机须自备 `67835ca` 克隆；缺失可选赛季文件时显式报缺口 | 大厅沙盒 + 工作台 |
| `event.calendar` | 活动日历与 24h 截止提醒 | `/妮姬 日程 [7\|14\|30] [页]`, `刷新\|订阅\|状态\|取消订阅` | 无 | — | **READY** | Linux Playwright + 订阅状态机全过 | **PASS**（`calendar_schedule.png` `1600×2308`） | 1 次请求刷新 9 条活动；QQ 真实群 `@` 推送按约束未发送 | 大厅 + 工作台订阅 |
| `event.gacha_board` | 卡池与活动分类板 | `/妮姬 卡池 [卡池\|活动\|皮肤\|突袭]` | 无 | — | **READY** | Linux CI + `unclassified` 计分修复全过 | **PASS** | 正确归类卡池/通行证/签到/转盘时装，明示 UP 概率缺失 | 公共大厅 |
| `event.announcement` | 官方公告查询与全群广播订阅 | `/妮姬 公告 [语言\|分类\|搜索\|诊断\|深度刷新\|订阅\|取消订阅]` | 查询无；订阅/刷新需管理员 | `enable_announcement_push` (false) | **READY** | Linux CI 全过 | **DEGRADED** | 部署机访问 `na-community.playerinfinite.com` 部分明细超时并安全提示 | 公共大厅 |
| `event.news_feeds` | 个人新闻/视频/日程订阅 | `/妮姬 新闻 [订阅\|状态\|取消订阅]` | 无（按会话+用户本人隔离） | — | **READY** | 按类型状态机 + 故障保护 + 并发去重全过 | **PASS**（YouTube `ConnectError` 时安全滞后建基线、`mock_sent=0`） | 真实 QQ 群推送按约束由 Mock sender 验证 | 工作台订阅管理 |
| `comm.daily_tasks_cdk` | 社区签到 / 领奖 / 浏览点赞 / CDK | `/妮姬 签到`, `日常 [任务]`, `兑换` | 完整绑定 + 独立写授权 | `enable_daily_actions` (false), `enable_cdk_redemption` (false) | **DEGRADED** | 离线 Mock + 崩溃/超时 `UNKNOWN_AFTER_ACTION` 防护全过 | **NOT_TESTED** | 严禁对真实玩家账号触发写提交 | 工作台只读状态 |
| `tool.counsel` | 咨询答案检索 | `/妮姬 咨询 <妮姬> [关键词]` | 无 | `counsel_bank_path` | **BLOCKED** | 检索器与导入器（带 `license` 校验）单测全过 | **BLOCKED** | 未内置无许可题库，命令明示缺口并阻断查询 | 导入合法题库后进大厅 |
| `tool.sync_calc` | 同步器升级/库存可升/瓶颈计算 | `/妮姬 同步器 [状态\|计算 ...]` | 可选（`计算 账号`） | `sync_level_cost_table_path` | **DEGRADED** | 可升计算 + 覆盖提示 + `validate_external_data.py` 校验全过 | **DEGRADED**（实号状态 `574` 与手工三项计算准确） | 无内置无许可成本表，缺少表时降级手工输入 | 大厅 + 工作台 |
| `tool.overload` | 超限洗词条建议与模拟 | `/妮姬 洗词条 ...`, `洗词条模拟 ...` | 可选（`账号[:角色]`） | `overload_recommendations_path` | **DEGRADED** | 跨 4 部位累计 + `SystemRandom` 同件重洗 + 账号对比全过 | **DEGRADED**（实号小红帽 4 件 T10 词条比对与模拟精准） | 无内置无许可推荐表，降级为用户自定义目标词条 | 大厅 + 工作台 |
| `tool.wishlist` | 愿望单推荐 | `/妮姬 愿望单 [收集\|均衡\|养成] [角色池]` | 可选（读取账号 SSR） | —（叠加 `data_dir/wishlist-pool-eligibility.json`） | **READY** | 171 SSR 准入表 + Fail-closed `unknown` 拒绝 + 160 墙全过 | **PASS** | 正确判过 160 墙（52/5）并保守过滤未核验新角 `5183–5187` | 大厅 + 工作台 |
| `fun.tarot` | 妮姬塔罗 | `/妮姬 塔罗 [单抽\|三张\|今日\|状态\|帮助]` | 今日牌绑定本人身份 | — | **READY** | Linux 完整 `assets/tarot` CI 全过 | **PASS** | 78 张牌面及逆位缓存生成正常 | 大厅随机 + 工作台每日 |
| `fun.favorite_grid` | 本命九宫格 T2I 图卡 & 人气榜 | `/妮姬 九宫格 <9人>`, `/妮姬 本命榜` | 无（每人 1 票可覆盖） | — | **READY** | 1080×1080 Edge 视觉 + O(1) 排行 + Linux CI 全过 | **PASS**（`favorite_grid.png` 携带 9 格真实本地立绘） | `nikke-t2i` 端到端渲染清晰且投票防刷正常 | 公共大厅 |
| `fun.voice` | 戳一戳语音 & 语音设置 | 戳一戳；`/妮姬 语音 [开\|关\|语言\|角色\|服装]` | 无 | `voice_dynamic_enabled` (true) | **READY** | Linux CI 全过 | **PASS**（偏好设置 + `/usr/bin/ffmpeg` & `ffprobe` 就绪） | 真实 QQ 戳一戳下发按约束未触发 | 大厅试听 + 工作台设置 |
| `nav.help` | 帮助导航与分类详解 | `/妮姬`, `/妮姬 帮助 [分类\|详解]` | 动态按配置裁剪 | — | **READY** | Linux CI 全过 | **PASS** | 按配置精准裁剪，输出符合合同 | 统一目录底座 |
| `misc.public_share` | 公开 UID 声明 / 第三方分享资料 / 手工资料 | `/妮姬 uid`, `我的妮姬 资料\|分享\|手工` | 无（不作账号归属证明） | `enable_public_share_api` (false) | **DEGRADED** | 默认关闭开关、外传提示及 `确认` 门禁测试全过 | **NOT_TESTED** | 默认关闭不外传，开启需运营者确认 | 工作台辅助 |
