# REAL_ACCOUNT_ACCEPTANCE.md — Phase 2 真实环境隔离只读验收报告

> **验收日期**：2026-11-25（UTC+8）  
> **代码基线**：`integration/phase2-candidate`（PR [#150](https://github.com/September6969/astrbot_plugin_nikke/pull/150)），代码验收至 commit `e7497462585c1ccf2eface1b628944dd76b799ab`（`e749746`）  
> **上游主干基线**：`origin/main` @ `71e664f41d8a8b370887c10580069edb8f99e42a`

---

## 一、部署环境与隔离边界

### 1.1 服务器与容器实况（`ssh serv`）
| 项目 | 实测值 |
|---|---|
| 主机架构 / 资源 | Linux x86_64，RAM `1.6 GiB`，`/dev/vda3` 可用空间 `3.7 GiB` |
| 主运行容器 `astrbot` | `soulter/astrbot:latest`，`Python 3.12.14`，`astrbot 4.27.5`，Playwright `0.28.1` / Chromium `151.0.7922.34`，`/usr/bin/ffmpeg`、`/usr/bin/ffprobe` |
| Spine Headless Worker | `/usr/local/bin/entrypoint-xvfb.sh`（Spine 4.0）、`/usr/local/bin/entrypoint-xvfb-4.1.sh`（Spine 4.1） |
| T2I 渲染服务 `nikke-t2i` | `nikke-t2i-runtime:20261029`，容器内网端点 `POST http://nikke-t2i:8080/text2img/generate`，内存限制 `384 MiB`，只读挂载字体目录 |
| 反向代理与 QQ 宿主 | `nikke-caddy`（`/opt/nikke-bot/caddy/Caddyfile`）、`napcat` |

### 1.2 安全与零干扰隔离措施
1. 全部验证均在服务器临时目录 `/opt/nikke-bot/astrbot/data/.p2-accept-isolated` 内执行：使用 `integration/phase2-candidate` 的独立 Git 检出、SQLite 官方在线备份 API `.backup()` 生成的数据库副本及只读 `secret.key` 副本，以及独立克隆的 `Jgaram/nikke-calc@67835ca3033a95482749ea2db35a8ee2a0856a92`。
2. 运行配置显式关闭全部写/高风险/端口冲突项：`enable_daily_actions=False`、`enable_cdk_redemption=False`、`enable_announcement_push=False`、`enable_shiftypad_readonly=False`、`enable_public_share_api=False`、`allow_group_bind=False`、`arena_web_enabled=False`、`web_port=0`（临时端口生命周期验证）。
3. 全程**未重启**任何生产容器，**未发送**任何真实 QQ 消息，**未执行**任何真实写操作（签到、社区任务、CDK 兑换、续期、解绑、换绑）。
4. 验收结束后已彻底删除 `/opt/nikke-bot/astrbot/data/.p2-accept-isolated`，并复核：
   - 生产库 `sha256sum /opt/nikke-bot/astrbot/data/nikke/nikke.sqlite3` 始终为 **`9e7efb023594c2942c6eb52ea785b9664ebbd044a08c70db7417abd97e9d2d97`**；
   - 宿主机零残留测试进程；
   - `astrbot` / `nikke-t2i` / `nikke-caddy` / `napcat` 四容器持续在线未中断。

---

## 二、绑定账号样本与部署侧运维观察

### 2.1 隔离库账号探针（严格脱敏）
| 记录 | 区服 `area_id` | 角色昵称 | 会话验证实测 | 说明 |
|---|---|---|---|---|
| `***9910` | `81` | `IRISES` | `profile_ok=true`（186 名妮姬、同步器 574 级） | **本次全量只读实测账号** |
| `***0455` | `81` | *（已绑定记录）* | `CookieExpired: 登录状态已失效，请重新绑定` | 实测印证凭据失效检测有效；隔离副本未对生产库做状态变更 |

> **关于提示参考号 `84522455` 的客观说明**：经查隔离数据库中两条记录的 `game_uid` 及上游 `GetUserProfileBasicInfo` / `GetUserGamePlayerInfo` 返回字段，均未发现直接等于 `84522455` 的游戏角色 ID；当前环境中仅 `***9910`（`IRISES`，区服 `81`）处于有效绑定态，全部在线只读验收基于该真实有效账号完成。  
> **ShiftyPad 凭据状态**：部署机 `/AstrBot/data/config` 与 `/AstrBot/data/nikke` 无独立 ShiftyPad 测试 Cookie/Token，`acct.shiftypad` 按约束维持 `BLOCKED` 与 `enable_shiftypad_readonly=false`。

### 2.2 宿主机反代配置差异提醒（合并后部署前置项）
实查宿主机 `/opt/nikke-bot/caddy/Caddyfile` 仍停留在较早版本（仅含 `log_skip /arena/open/*` 且开启 `stdout` 日志）。按 PR #150 内的 [`deploy/Caddyfile`](../../deploy/Caddyfile)，后续合并部署若计划启用 `enable_shiftypad_readonly`，必须先将 `log_skip /shiftypad/*` 与 `log_skip /api/shiftypad/*` 同步至宿主机 Caddy 配置并重载。

---

## 三、真实环境发现与当轮闭环修复

1. **真实业务 P1 缺陷发现与修复（提交 `e749746`）：`solo_raid` 已绑定账号未补全内置目录属性**
   - **现象**：首次在 `***9910` 实机运行 `/妮姬 单人突袭 阵容图 账号` 时，BlaBlaLink `GetUserCharacters` 仅返回 `name_code` 与战力/等级，未携带 `burst`/`element`/`name_zh_cn`/`resource_id`，导致 5 队输出 `1007(?)` 黑框且爆裂链全缺，真实 `nikke-calc@67835ca` 未被触发。
   - **修复与复验**：在 [`application/commands/solo_raid.py`](../../application/commands/solo_raid.py) 为已绑定账号支路补充 `_enrich_rows_with_directory` 目录补齐，并补充单测 [`tests/test_toolbox_commands.py`](../../tests/test_toolbox_commands.py)。修复后 `serv` 实机复跑立即输出完整 5 队、真实中文名与头像、全部通过爆裂链，并由真实 `Jgaram/nikke-calc@67835ca` 计算出总估算 **`1,813,859,815`**（第 1–5 队：`230,904,758` / `431,851,163` / `355,762,826` / `310,423,629` / `484,917,439`）。
2. **线上突发限流缓解（提交 `e749746`）：`GetUserCharacterDetails` Top-20 并发**
   - **现象**：首次实机连续查询 `profile` 后立刻执行 `roster_cold`（20 次 `GetUserCharacterDetails`，并发度 `3`）时，3/4 次实测触发上游 `BlaBlaError: request too frequently`（单轮最多 7 个角色提示「详情读取失败」）。
   - **修复与复验**：在 [`features/character/application.py`](../../features/character/application.py) 为速率限制错误增加 `1` 次退避重试（`ROSTER_DETAIL_RETRY_DELAY = 0.8s`），保持并发合约 `ROSTER_DETAIL_CONCURRENCY = 3`。复验 `roster_cold` 中 5 次触发限流后当轮追回 3 个、剩余 2 个在 `roster_warm` 缓存窗口补采成功，未引发账号封禁或整页崩溃。
3. **Python 3.12 POSIX 子进程树清理修复（提交 `2fff002`）**
   - **现象**：`65ba5f0` 首次 PR CI 中 Linux Python 3.12（`AstrBot ==4.24.0` 与 `>=4.24,<5`）均在派生子进程继承管道测试超时（10.03s–13.03s），而在 `serv` Linux Python 3.12.14 复现确认两处根因：（a）Python 3.12 `proc.wait()` 在管道未关闭时阻塞；（b）容器内 PID 1 未回收的 `State: Z` 僵尸进程仍使 `os.killpg(pgid, 0)` 返回存活。
   - **修复与复验**：在 [`integrations/nikke_calc/engine.py`](../../integrations/nikke_calc/engine.py) 增加 `_wait_direct_exit` 与 `_posix_pgid_has_live_processes`（通过 `/proc/<pid>/stat` 排除 `Z`/`X`/`x` 态），在 `serv` Python 3.12.14 上 `tests/test_solo_raid_engine.py` 8 项全部以 **`2.53s`** 通过，随后 PR #150 `2fff002` 全部 12 项 GitHub Actions CI 全绿。

---

## 四、`AUD-010` 请求计数、冷/热缓存耗时与系统健康实测

| 用例 / 阶段 | 请求总数与接口明细 | 总耗时（含渲染） | 结果摘要 |
|---|---|---|---|
| `profile_cold` | **5**（`GetUserProfileBasicInfo` x2, `GetUserProfileOutpostInfo` x1, `GetUserCharacters` x1, `GetUserDailyContentsProgress` x1） | `3398.3 ms` | 成功生成 `profile.png`（主线未映射显示 `ID 6050044`，困难 `40-11`） |
| `profile_warm` | **4**（上述 4 个接口各 1 次） | `1451.7 ms`（T2I 缓存命中仅 `17.4 ms`） | 成功生成 `profile_2.png` |
| `roster_cold`（20 展示详情） | **26**（`GetUserCharacters` x1 + `GetUserCharacterDetails` x25，含 5 次限流单次重试） | `31305.6 ms` | 18/20 当轮取全词条与 `#5185` 安全未知头像；2/20 限流保留降级提示（`空闲期实测 22 HTTP / 22311.0 ms`） |
| `roster_warm` | **2**（18/20 命中 30s 短缓存发 **0** 请求；仅补采前次失败 2 角色并成功补全） | `2976.8 ms` | 补齐为 19/20 完整词条（空闲期全程 `0 HTTP / 1347.2 ms`） |
| `character_card`（小红帽） | **5**（`BasicInfo` x1, `OutpostInfo` x1, GitHub commit/tree + `.skel` x3；详情命中缓存） | `25607.4 ms` | 104 阶 OL/4 件 T10/10-10-10 技能/`LV.15` 珍藏魔方全准；冷拉 GitHub `.atlas/.png` 超 6.0s 硬预算时降级为剪影兜底 |
| `raid_overview` | **4**（`GetMyGuildInfo`, `GetUnionRaidData`, `GetUnionRaidLevelInfo`, `GetUnionRaidDataOfGuildSeason`） | `8091.9 ms` | 第 44 季上赛季返回记录 85 条完整展示，明示非完整赛季边界 |
| `raid_ranking` / `raid_member` | **0** / **0**（复用客户端缓存） | `401.7 ms` / `1571.7 ms` | 分页贡献榜与个人 3 条尾刀记录及敌方 Boss/队友头像全对 |
| `campaign_lookup`（普通 10-1） | **1**（`GetMainQuestClearLineup`） | `1134.0 ms` | 返回 5 人通关阵容与总战力 `25,025` |
| `calendar` 刷新 + 查询 | **1**（`GetCalendarDetail`） | `2831.9 ms` | 同步 9 条进行中活动并生成日程图卡 |
| `announcements` 首次同步 | **9**（`GetLabelList` x1, `GetContentByLabel` x4, `GetContentInfoById` 200 x1 / 超时 x3） | `> 6.3s` | 海外节点访问 `na-community.playerinfinite.com` 部分明细超时，安全返回提示不造假 |
| `info_feeds`（YouTube Atom） | **1**（`www.youtube.com/feeds/videos.xml` `ConnectError`/`ConnectTimeout`） | `121.0 ms`（重试前超时 `10.0s`） | 明确提示「视频 来源当前暂不可用，将在恢复后首次同步时自动建立基线（不重推历史消息）」 |
| 进程内存（RSS） | 启动 `67.59 MB` → 全部查询+14 张 T2I+`nikke-calc`+生命周期回收结束 **`160.34 MB`** | — | 无内存失控增长 |
| 运行时退出与故障注入 | `coordinator_closed=true`、`survivors=[]`、`sqlite_integrity="ok"`、`lingering_nikke_calc_procs=[]` | — | 派生孙进程 0.4s 超时强杀零残留；坏 JSON 拒收；缺引擎明示降级；Mock 429/503/Timeout 均安全抛出规范异常 |

---

## 五、真实 `nikke-t2i` 卡片渲染与视觉人工核查（14/14 张）

全部截图均由生产容器 `nikke-t2i`（`POST http://nikke-t2i:8080/text2img/generate`）实际 Chromium 渲染并下载逐张核查（不提交含个人资料的原始截图文件至仓库）：

| 渲染页面 | 尺寸（px） | 文件体积 | 渲染耗时 | 视觉人工核查结论 |
|---|---|---|---|---|
| `profile.png` / `profile_2.png` | `1080×3148` | `388,585 B` | `1017.9 ms` / `17.4 ms` | 字体、资源图标、循环室/前哨/遗失物对齐清晰；普通主线未映射 `ID 6050044` 正常折行未溢框 |
| `roster.png` / `roster_2.png` | `1200×6392` / `1200×6556` | `1.19 MB` / `1.23 MB` | `1092.3 ms` / `1162.7 ms` | `#1` 未知新角 `瑪麗安：女王 #5185` 显示 `?` 安全占位；15 阶满阶黑底白字高亮清晰；失败条目明示不遮掩 |
| `character.png`（小紅帽） | `1600×2400` | `868,922 B` | `1723.8 ms` | 战力/等级/核心/珍藏/魔方/OL 4 部位与 15 阶高亮对齐准确；冷图超时 6.0s 降级剪影占位；另有较早 `海倫：海藍寶石` 实渲染全立绘验证（底部脚尖在底层毛玻璃下略微露出 2px 属轻量观感瑕疵） |
| `union_overview.png` | `1080×1839` | `171,222 B` | `349.6 ms` | 第 44 季休赛期标注、前五贡献条与个人 3 条记录清晰对齐 |
| `union_records.png` | `1080×2138` | `224,405 B` | `353.2 ms` | 15 名成员排行与出刀不确定声明排版完整 |
| `union_member.png` | `1080×1983` | `671,896 B` | `1056.6 ms` | 3 支尾刀阵容头像、战力及 `Rebuild Big Torso` Boss 图标完整 |
| `campaign.png`（普通 10-1） | `1600×900` | `248,192 B` | `466.3 ms` | 5 人头像、战力 `25,025` 与底部元信息对齐无裁切 |
| `arena_matchup.png` | `1000×1862` | `426,880 B` | `460.9 ms` | 敌我 P1–P5 头像、爆裂轴、模板风险提示与珍藏推测声明清晰 |
| `arena_three_teams.png` | `1000×2083` | `522,343 B` | `569.6 ms` | 3 场对位 30 个角色头像与爆裂顺序完整无重叠 |
| `solo_raid.png` | `1000×1760` | `650,691 B` | `616.0 ms` | 25 名角色头像、`B1–B3`、真实 `nikke-calc 67835ca303` 总估算 `1,813,859,815` 与 MIT 声明清晰（`B1 · Electronic` 少量长英文属性自动换行，无溢框） |
| `calendar_schedule.png` | `1600×2308` | `2,119,285 B` | `1699.6 ms` | 活动头图与 9 条活动进度条、即将结束橙标清晰对齐 |
| `favorite_grid.png` | `1080×1080` | `1,282,279 B` | `1213.8 ms` | 9 格真实角色头像 `1080×1080` 正方裁切干净、P1–P9 标签清晰 |

---

## 六、30 项能力真实环境验收总表

> **状态严格定义**：`PASS`（本次实机真实链路跑通且输出/T2I 合格）、`DEGRADED`（安全降级或依赖未在部署机导入的可选外部数据/高风险写开关保持关闭）、`BLOCKED`（缺授权凭据或无许可题库，按规定阻断）、`NOT_TESTED`（按环境约束本轮不得执行真实线上操作，保持由 CI/离线测试覆盖）。

| Capability ID | 功能 | 测试版本（SHA） | 验证方式 | 实际结果 | 请求次数 | 耗时 | 证据 | 状态 |
|---|---|---|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 绑定扩展与 Web 鉴权 | `e749746` | 隔离临时端口监听 + CI Extension/Web 验真 | Ephemeral 端口起停正常，生产未暴露额外端口（线上反代 HTTPS 仍以线上配置为准） | 0 | — | `accept_report.json#lifecycle.web_ephemeral_sites` | **PASS**（绑定写入流程按约束未实号重绑） |
| `acct.lifecycle` | 绑定状态 / 凭据失效检测 / 解绑隔离 | `e749746` | 隔离库 2 条真实记录探测 | `***9910` 有效读出资料；`***0455` 准确识别 `CookieExpired` 拒绝读数，未写坏生产库 | 4 | — | `accept_report.json#account_probe` | **PASS**（真实解绑按约束仅离线验证） |
| `acct.renewal` | 实验性会话续期与自动续期 | `e749746` | 开关 `enable_daily_actions=False` | 默认关闭，未对真实账号执行写操作 | 0 | — | 约束禁止真实账号写入 | **NOT_TESTED** |
| `acct.shiftypad` | ShiftyPad 只读导入绑定 | `e749746` | 部署机凭据检索 + `uid 状态` 命令 | 部署机无 ShiftyPad 授权凭据，开关维持 `false` | 0 | — | `accept_report.json#results.shiftypad_status` | **BLOCKED** |
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | `e749746` | 实号冷/热调用 + `nikke-t2i` | 准确输出等级 `731`、战力 `1,418,686`、同步器 `574`、未映射主线 `6050044` 与 `profile.png` | 5 / 4 | `3398.3ms` / `1451.7ms` | `profile.png` | **PASS** |
| `char.roster` | 角色练度总览（Top 20 OL） | `e749746` | 实号冷/热调用 + `nikke-t2i` | 186 角色按战力排序、#5185 未知安全占位、15 阶高亮；突发并发限流由重尝试+缓存缓解（偶发 2/20 降级提示） | 26 / 2（空闲 22 / 0） | `31305.6ms` / `2976.8ms` | `roster.png` / `roster_2.png` | **DEGRADED**（偶发限流保护降级） |
| `char.detail` | 单角色详细练度 / OL / Spine | `e749746` | 实号查询「小红帽」+ `nikke-t2i` | 104 阶 OL / T10 / 技能 / 珍藏 / 魔方全部精准；GitHub 冷图超 6s 降级剪影兜底 | 5 | `25607.4ms` | `character.png` | **PASS**（冷网立绘降级正常） |
| `growth.history` | 养成历史快照与差异 | `e749746` | 隔离库随 `profile`/`roster` 自动落盘并查询 | 成功记录 9 项字段快照（`Lv.731`/`574`/`186`）并返回「养成历史」输出 | 0 | — | `accept_report.json#results.growth` | **PASS** |
| `combat.campaign` | 主线通关历史阵容 | `e749746` | 实号查普通 `10-1` + `nikke-t2i` | 返回 5 人真实阵容（总战力 `25,025`）与 `campaign.png`（`1600×900`） | 1 | `1134.0ms` | `campaign.png` | **PASS** |
| `combat.tower` | 企业塔静态战力资料 | `e749746` | 本地预热 + `无限 150` 命令 | 准确输出 `252,600` 标准战力及免责提示 | 0 | <5ms | `accept_report.json#results.tower_floor` | **PASS** |
| `combat.char_info` | 角色基础资料 | `e749746` | 官方目录预载 + `查询 小红帽` | 准确输出中英名/SSR/Iron/SR/AllStep/PILGRIM | 0 | <5ms | `accept_report.json#results.character_info` | **PASS** |
| `combat.guide` | 本地授权一图流攻略 | `e749746` | `攻略` 目录与 `攻略 练度 1` | 返回 6 张本地授权 PNG（`exists=true`）及授权声明 | 0 | <10ms | `accept_report.json#results.guide_progression` | **PASS** |
| `combat.union_raid` | 联盟突袭（总览 / 排名 / 我的） | `e749746` | 实号拉取「灰姑娘的水晶鞋」+ 3 张 `nikke-t2i` | 第 44 季 85 条记录、15 名贡献榜与个人 3 刀详情均渲染出图 | 4 / 0 / 0 | `8091.9ms` / `401.7ms` / `1571.7ms` | `union_*.png` | **PASS** |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 我的 / 状态 | `e749746` | 实号持有过滤（181 已映射）+ 单队/三队导入 + `nikke-t2i` | 单队解队、三队导入均快速生成清晰深色对战卡片 | 1 / 0 / 0 | `1378ms` + `460.9ms`/`569.6ms` | `arena_matchup.png`, `arena_three_teams.png` | **PASS** |
| `combat.arena_web` | 竞技场临时编辑网页 | `e749746` | 部署隔离 `arena_web_enabled=False` | 路由挂载与 Playwright CI 完备，隔离验收按约束未对公网开启 | 0 | — | Linux Playwright CI 实测通过 | **NOT_TESTED** |
| `combat.solo_raid` | 单人突袭五队编组与 MIT 估伤 | `e749746` | 修复 `e749746` 后实号 186 人 + 实装 `nikke-calc@67835ca` + `nikke-t2i` | 5 队爆裂全通过，真实引擎计算总估算 **`1,813,859,815`** 并渲染 `solo_raid.png`；因未导入可选赛季 JSON `赛季` 显式报缺口 | 0（复用缓存） | `17486.7ms`（含 5 队真实子进程+T2I） | `solo_raid.png` | **DEGRADED**（未导入可选赛季 JSON；核心 5 队与 MIT 估伤 `PASS`） |
| `event.calendar` | 活动日历查询与 T2I | `e749746` | 在线拉取 `GetCalendarDetail` + `nikke-t2i` | 拉取 9 条实时活动，倒计时准确，输出 `calendar_schedule.png`（`1600×2308`） | 1 | `2831.9ms` | `calendar_schedule.png` | **PASS** |
| `event.gacha_board` | 卡池与活动分类板 | `e749746` | 基于同一实网日程快照生成分类文本 | 完整区分限时卡池、通行证、签到、转盘时装并明示概率缺失 | 0 | <5ms | `accept_report.json#results.gacha` | **PASS** |
| `event.announcement` | 官方公告查询与全群广播订阅 | `e749746` | 部署机访问 `na-community.playerinfinite.com` | 实测海外节点详情明细请求部分超时，明确提示「同步公告超时」，未造假；全群推送未开启 | 9 | `> 6.3s` | `accept_report.json#results.announcements` | **DEGRADED**（受节点网络超时影响；安全降级正确） |
| `event.news_feeds` | 个人新闻 / 视频 / 日程订阅 | `e749746` | 隔离订阅「新闻、视频、日程」+ 模拟 `dispatch_due`（无 QQ 发送） | YouTube Atom `ConnectError` 时明确提示并保留基线、`mock_sent_count=0` | 1 | `121.0ms` | `accept_report.json#results.info_feeds_isolated` | **PASS**（QQ 主动推送按约束由 Mock 验证） |
| `comm.daily_tasks_cdk` | 社区签到 / 领奖 / 浏览点赞 / CDK | `e749746` | `enable_daily_actions=False`, `enable_cdk_redemption=False` | 高风险实号写操作严禁现场触发，保持默认关闭 | 0 | — | 约束禁止真实账号写操作 | **NOT_TESTED** |
| `tool.counsel` | 咨询答案检索 | `e749746` | 命令调用 `/妮姬 咨询 拉毗` | 无合法授权中文题库，明示「题库文件不存在：counsel_bank.json」并阻断 | 0 | <5ms | `accept_report.json#results.counsel` | **BLOCKED** |
| `tool.sync_calc` | 同步器升级与瓶颈计算 | `e749746` | `状态` 读实号 `574` + `手工` 升至 `580` 计算 | 在线读取 `574` 级与手工三项累计成本预测 `250` 天均正确（缺未导入等级表时降级手工） | 0（复用缓存） | <5ms | `accept_report.json#results.sync_*` | **DEGRADED**（无内置等级成本表） |
| `tool.overload` | 超限洗词条建议与模拟 | `e749746` | `账号:小红帽` 读取真实 4 件 T10 OL 对比与模拟 | 精准读出小红帽实装 `13/8/15` 阶词条并给出保留锁定/重洗建议与模拟 | 0（复用缓存） | <10ms | `accept_report.json#results.overload*` | **DEGRADED**（无内置角色推荐表） |
| `tool.wishlist` | 普通招募愿望单推荐 | `e749746` | `均衡` 模式基于实号 186 名持有生成推荐 | 判定 `160 壁垒：已通过（52/5）` 并过滤联动/限定/免费及未知新角 `5183–5187` | 0（复用缓存） | <10ms | `accept_report.json#results.wishlist` | **PASS** |
| `fun.tarot` | 妮姬塔罗（单抽 / 逆位 / 状态） | `e749746` | 完整 78 张牌库实抽与逆位图缓存生成 | 抽取 `XI·正义·逆位` 并生成逆位 PNG（`22/22 + 56/56` 完备） | 0 | <50ms | `accept_report.json#results.tarot_*` | **PASS** |
| `fun.favorite_grid` | 本命九宫格 T2I & 人气榜 | `e749746` | 9 名角色生成图卡 + 排行榜查询 | 生成 `1080×1080` 带真实头像九宫格 PNG 并正确写入孤立排行计数 | 0 | `1213.8ms` | `favorite_grid.png` | **PASS** |
| `fun.voice` | 戳一戳语音与偏好设置 | `e749746` | 状态命令 + 宿主工具探针 | 偏好设置与提示正常，`/usr/bin/ffmpeg` 与 `/usr/bin/ffprobe` 均就绪（实际 QQ 戳一戳语音发送未外发） | 0 | <5ms | `accept_report.json#results.voice_*` | **PASS**（偏好+编解码工具核验） |
| `nav.help` | 帮助首页与按配置动态详情 | `e749746` | `help_home` + `help_detail("竞技场")` | 动态裁剪开关项并正常输出 192 / 132 字符说明 | 0 | <5ms | `accept_report.json#results.help_*` | **PASS** |
| `misc.public_share` | 公开 UID 声明 / 第三方分享资料 | `e749746` | `enable_public_share_api=False` 默认关闭边界检查 | 关闭开关后不发起第三方 `nikke-api.pages.dev` 请求 | 0 | — | 隔离配置验证关闭 | **NOT_TESTED** |
