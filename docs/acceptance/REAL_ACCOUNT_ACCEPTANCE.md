# REAL_ACCOUNT_ACCEPTANCE.md — Phase 2 真实环境隔离只读验收报告

> **验收日期**：2026-11-25（UTC+8）  
> **代码基线**：`integration/phase2-candidate`（PR [#150](https://github.com/September6969/astrbot_plugin_nikke/pull/150)），含最终门禁收尾修复  
> **上游主干基线**：`origin/main` @ `71e664f41d8a8b370887c10580069edb8f99e42a`

---

## 一、部署环境与零干扰隔离边界

### 1.1 服务器与容器实况（`ssh serv`）
| 项目 | 实测值 |
|---|---|
| 主机架构 / 资源 | Linux x86_64，RAM `1.6 GiB`，`/dev/vda3` 可用空间 `3.7 GiB` |
| 主运行容器 `astrbot` | `soulter/astrbot:latest`，`Python 3.12.14`，`astrbot 4.27.5`，Playwright `0.28.1` / Chromium `151.0.7922.34`，`/usr/bin/ffmpeg`、`/usr/bin/ffprobe` |
| Spine Headless Worker | `/usr/local/bin/entrypoint-xvfb.sh`（Spine 4.0）、`/usr/local/bin/entrypoint-xvfb-4.1.sh`（Spine 4.1） |
| T2I 渲染服务 `nikke-t2i` | `nikke-t2i-runtime:20261029`，容器内网端点 `POST http://nikke-t2i:8080/text2img/generate`，内存限制 `384 MiB`，只读挂载字体目录 |
| 反向代理与 QQ 宿主 | `nikke-caddy`（`/opt/nikke-bot/caddy/Caddyfile`）、`napcat` |

### 1.2 安全边界与环境零干扰核验
1. 全部验证在隔离临时目录内运行：使用 `integration/phase2-candidate` 独立克隆、SQLite `.backup()` 只读隔离库、`secret.key` 副本，以及独立克隆的 `Jgaram/nikke-calc@67835ca3033a95482749ea2db35a8ee2a0856a92`。
2. 显式关闭高风险/写/端口冲突开关：`enable_daily_actions=False`、`enable_cdk_redemption=False`、`enable_announcement_push=False`、`enable_shiftypad_readonly=False`、`enable_public_share_api=False`、`allow_group_bind=False`、`arena_web_enabled=False`、`web_port=0`。
3. 全程**未重启**任何生产容器，**未发送**真实 QQ 消息，**未执行**真实账号写操作（签到、社区任务、CDK、续期、解绑、换绑）。
4. 验收后彻底删除隔离目录，核验：
   - 生产数据库 `sha256sum /opt/nikke-bot/astrbot/data/nikke/nikke.sqlite3` 始终为 **`9e7efb023594c2942c6eb52ea785b9664ebbd044a08c70db7417abd97e9d2d97`**；
   - 宿主机无残留测试进程与临时敏感副本；
   - `astrbot`、`nikke-t2i`、`nikke-caddy`、`napcat` 持续运行未中断。

---

## 二、数据库身份核查与指定 UID `84522455` 定位结论

### 2.1 只读数据库结构与身份字段全面核查
对生产库 `/AstrBot/data/nikke/nikke.sqlite3`（`schema_version=2`）及 `/AstrBot/data/{nikke,config}` 非敏感配置进行了全面只读检索（绝不解密输出 Cookie/Token 明文）：

| 核查范围 | 字段 / 存储维度 | 核查结果 |
|---|---|---|
| `accounts` 表（2 行） | 主键 `qq_id`、`game_uid`、`game_openid`、`area_id`、`nickname`、`role_name`、`cookie_valid`、`canonical_game_identity`（`blabla:<area>:<uid>`）、解密后 `cookie_cipher` & `xcommon_cipher`（仅布尔检索） | **均不含 `84522455`**。样本 A（`qq` 尾号 `***9910`，区服 `81`）会话有效，作为本次只读验收账号；样本 B（`qq` 尾号 `***0455`，区服 `81`）上游实测返回 `CookieExpired`（已失效，未擅自续期或重绑） |
| `bind_sessions` 表（1 行） | `token_hash`、`qq_id`、`status` | `status=success`（对应样本 A），不含 `84522455` |
| `settings` 表（85 行） | 各订阅、成长、日历与功能配置键 | 全表无 `84522455` |
| `action_runs`（159 行）/ `/AstrBot/data/{nikke,config}` | 历史执行流水与运行时配置文件 | 无 `84522455` 匹配项；且部署机无 ShiftyPad 测试凭据（`acct.shiftypad` 保持 `BLOCKED`） |

> **非阻塞未完成验收项结论**：`84522455` 在当前生产数据库全部身份字段（含主/旧版字段、`game_openid`、`canonical_game_identity` 及密文荷载内部键）与配置文件中均未定位到对应记录；按“未获授权不续期失效账号、亦不再另选他号增测”原则，如实记为待用户核对账号归属的非阻塞未完成事项。

### 2.2 宿主机 Caddy 反代配置提醒（正式部署前前置项）
实查宿主机 `/opt/nikke-bot/caddy/Caddyfile` 仅配有 `log_skip /arena/open/*` 且启用 `stdout` 访问日志。正式部署 PR #150（尤其在未来考虑启用 ShiftyPad 功能前），**必须先同步 [`deploy/Caddyfile`](../../deploy/Caddyfile) 的 `log_skip /shiftypad/*` 与 `log_skip /api/shiftypad/*` 并重载 Caddy**，防止一次性认证路径进入代理访问日志。

---

## 三、验真层级划分与当轮工程收尾

本报告严格区分三类实测层级，不将局部/模拟结论夸大为完整真实业务闭环：
1. **完整真实业务验收（Full Real Business E2E）**：真实有效账号发起只读指令 → 真实 BlaBlaLink 上游拉取 → 领域计算 / `nikke-calc@67835ca` → 生产级 `nikke-t2i` Chromium 出图与视觉验收（涵盖核心只读查询、T2I 图卡、离线引擎、本地资料/娱乐与愿望单等）。
2. **真实服务器部分链路验收（Partial Server Chain）**：已部署容器上的实态接口/外部工具链/状态探针通过，但受高风险写禁令、公网未开或 QQ 外发禁止所限未走全链（如 `acct.blabla_bind`、`acct.lifecycle`、`fun.voice`）。
3. **Mock / 离线及网络故障降级验收（Mock / Offline / Fault-Injection）**：无线上发送行为，基于真实网络超时或隔离 Mock 验证边界（如 `event.news_feeds`、高风险写开关 `acct.renewal` / `comm.daily_tasks_cdk`、网页 Playwright CI 覆盖项 `combat.arena_web` 及默认关闭项 `misc.public_share`）。

---

## 四、`AUD-010` 上游 HTTP、T2I 渲染、生命周期与故障注入指标

| 检验维度 | 实测观测值（脱敏） | 状态与说明 |
|---|---|---|
| `profile`（冷 / 热） | `5` HTTP（`3398.3 ms`）/ `4` HTTP（`1451.7 ms`，T2I 缓存命中 `17.4 ms`） | 新版本未收录主线 ID 明确标示“未映射” |
| `roster`（Top-20 详情，冷 / 热） | 突发限流窗：`26` HTTP（`1+25` 含 5 次重试追回 3 项，2 项降级，耗时 `31.3 s`）→ 热查 `2` HTTP（`2.98 s` 补齐，其余 18 项 `0` HTTP）；空闲窗：`22` HTTP（`22.3 s`）→ `0` HTTP（`1.35 s`） | 30s 缓存与单次退避重试有效，但并发 20 次详情在紧接 `profile` 后仍偶发限流降级 |
| `character_card` | `5` HTTP（`Basic` + `Outpost` + GitHub index/tree/skel，`25.6 s`） | 超限词条、技能、魔方与珍藏数值精确；冷网下 GitHub 立绘超出 6.0s 硬预算时降级为剪影兜底 |
| `raid`（总览 / 排行 / 个人） | `4` / `0` / `0` HTTP（`8.09 s` / `0.40 s` / `1.57 s`） | 三张图卡复用同一短缓存，正确标注休赛期及记录完整性边界 |
| `campaign` / `calendar` | 各 `1` HTTP（`1.13 s` / `2.83 s`） | 出图与活动倒计时精确 |
| `announcements` / `info_feeds` | 公告 `9` HTTP（部分明细海外超时提示不可用）；YouTube Atom `1` HTTP（`ConnectError`），`mock_sent=0` | 严格滞后建基线、零误推送、不造假 |
| `solo_raid`（实号 + `nikke-calc@67835ca`） | `0` 新增 HTTP（复用缓存），`17.49 s` 含 5 队真实子进程与 T2I | 修复目录补全后 5 队爆裂全通并跑出 `Git 核验固定基线` 估算总和 `1,813,859,815` |
| `nikke-t2i` 像素视觉抽检 | 14 页截图（`profile`/`roster`/`character`/`union_*`/`campaign`/`arena_*`/`solo_raid`/`calendar_schedule`/`favorite_grid`）全部 `HTTP 200` 生成（耗时 `17.4 ms–1.72 s`） | 中文排版、图标、15 阶高亮与未知角色安全占位均清晰；`海伦` 全立绘底层毛玻璃下方略微可见 2px 脚尖、`solo_raid` 少量长英文属性自动换行无溢框 |
| 进程树/内存/故障注入 | RSS `67.59 MB → 160.34 MB`；`coordinator_closed=true`、`survivors=[]`、`lingering_nikke_calc_procs=[]`、`sqlite_integrity="ok"`；`0.4s` 挂起子进程树超时强杀零残留；坏 JSON/缺引擎/429/503/Timeout 均安全处置 | 随后又在最终收尾修复中补强了并发清理幂等、失败占槽不释放、提前返回不丢 `cleanup_error` 与 `collector` 回收 |

---

## 五、30 项能力验收总表（PASS: 19 / DEGRADED: 5 / BLOCKED: 2 / NOT_TESTED: 4）

| Capability ID | 功能 | 验收层级划分 | 请求次数 / 耗时 | 实测结论摘要 | 状态 |
|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 完整绑定 | 真实服务器部分链路 | 0 / — | 隔离临时监听起停与路由挂载正常（线上重绑未覆盖实号，反代同步见 §2.2） | **PASS** |
| `acct.lifecycle` | 绑定状态 / 失效检测 / 解绑隔离 | 真实服务器部分链路 | 4 / — | 真实有效账号读出正常；失效记录精准识别 `CookieExpired`（实号解绑仅离线验证） | **PASS** |
| `acct.renewal` | 实验性会话续期 & 自动续期 | Mock 验收 | 0 / — | 开关 `enable_daily_actions=False` 默认关闭，严禁实号触发（离线 Mock/未知态保护已过） | **NOT_TESTED** |
| `acct.shiftypad` | ShiftyPad 只读导入绑定 | —（受阻） | 0 / — | 部署机无 ShiftyPad 授权凭据，保持 `enable_shiftypad_readonly=false` 默认关闭 | **BLOCKED** |
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | 完整真实业务验收 | 5→4 / `3.40s→1.45s` | 资料/前哨/资源与 `profile.png`（`1080×3148`）完整生成，未映射主线如实提示 | **PASS** |
| `char.roster` | 角色练度总览（Top 20 OL） | 完整真实业务验收 | 26→2（空闲 22→0） | 排序、词条汇总、`roster.png`（`1200×6556`）正常；突发限流经重试缓解但偶发 2/20 降级 | **DEGRADED** |
| `char.detail` | 单角色详细练度 / OL / Spine | 完整真实业务验收 | 5 / `25.61s` | OL 4 件/技能/珍藏/魔方全准，`character.png`（`1600×2400`）正常，冷网超时安全降级剪影 | **PASS** |
| `growth.history` | 养成历史快照与差异 | 完整真实业务验收 | 0 / <10ms | 隔离库 9 项字段自动落盘并正确查出对比快照（已按游戏身份隔离） | **PASS** |
| `combat.campaign` | 主线通关历史阵容 | 完整真实业务验收 | 1 / `1.13s` | 查得 5 人通关阵容并渲染 `campaign.png`（`1600×900`） | **PASS** |
| `combat.tower` | 企业塔静态战力资料 | 完整真实业务验收 | 0 / <5ms | 本地静态表精准输出标准战力及免责提示 | **PASS** |
| `combat.char_info` | 角色基础资料 | 完整真实业务验收 | 0 / <5ms | 载入 207 条官方目录，属性/武器/爆裂/企业查询准确 | **PASS** |
| `combat.guide` | 本地授权一图流攻略 | 完整真实业务验收 | 0 / <10ms | 输出 6 张本地授权 PNG 及作者/授权信息 | **PASS** |
| `combat.union_raid` | 联盟突袭（总览 / 排名 / 我的） | 完整真实业务验收 | 4→0 / `8.09s` | 完整渲染 `union_overview` / `union_records` / `union_member` 3 张截图与上赛季记录边界 | **PASS** |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 我的 / 状态 | 完整真实业务验收 | 1 / `1.38s`+`0.46s` | 实号持有过滤（剔除 5 个未映射新角）并输出单队/三队 `arena_*.png` | **PASS** |
| `combat.arena_web` | 竞技场临时编辑网页 | Mock / CI 验收 | 0 / — | 隔离验收保持 `arena_web_enabled=False`，已由 Linux CI Playwright 端到端通过 | **NOT_TESTED** |
| `combat.solo_raid` | 单人突袭五队编组与 MIT 估伤 | 完整真实业务验收 | 0 / `17.49s` | 实号 5 队爆裂全通并经真实 `nikke-calc@67835ca` 计算与 `solo_raid.png` 出图；缺未导入赛季 JSON | **DEGRADED** |
| `event.calendar` | 活动日历与 24h 截止提醒 | 完整真实业务验收 | 1 / `2.83s` | 在线同步 9 条活动并生成 `calendar_schedule.png`（`1600×2308`） | **PASS** |
| `event.gacha_board` | 卡池与活动分类板 | 完整真实业务验收 | 0 / <5ms | 基于真实日程快照精确分类卡池/活动并标示 UP 概率缺失 | **PASS** |
| `event.announcement` | 官方公告查询与全群广播订阅 | 真实服务器+故障验收 | 9 / `>6.3s` | 海外节点拉取 `na-community.playerinfinite.com` 部分明细超时，安全返回不可用提示 | **DEGRADED** |
| `event.news_feeds` | 个人新闻 / 视频 / 日程订阅 | 真实网络+Mock 投递 | 1 / `121.0ms` | YouTube `ConnectError` 时准确保留未初始化基线（防历史倒灌），`dispatch_due` 由 Mock 验证 | **PASS** |
| `comm.daily_tasks_cdk` | 社区签到 / 领奖 / 浏览点赞 / CDK | Mock 验收 | 0 / — | 高风险实号写操作默认关闭（`False`），严禁线上实测；`UNKNOWN_AFTER_ACTION` 仅离线验证 | **NOT_TESTED** |
| `tool.counsel` | 咨询答案检索 | —（受阻） | 0 / <5ms | 无合法授权中文题库，命令明确报缺口并阻断查询 | **BLOCKED** |
| `tool.sync_calc` | 同步器升级与瓶颈计算 | 完整真实业务验收 | 0 / <5ms | 实号当前等级读取与手工三项累计升级计算精确；缺未导入等级成本表 | **DEGRADED** |
| `tool.overload` | 超限洗词条建议与模拟 | 完整真实业务验收 | 0 / <10ms | 实号 4 件 T10 词条比对与模拟精准；缺未导入角色推荐预设表 | **DEGRADED** |
| `tool.wishlist` | 普通招募愿望单推荐 | 完整真实业务验收 | 0 / <10ms | 正确判过 160 墙，保守过滤联动/限定/免费及未核验新角 | **PASS** |
| `fun.tarot` | 妮姬塔罗 | 完整真实业务验收 | 0 / <50ms | 78 张牌面及逆位缓存渲染全部就绪并抽取成功 | **PASS** |
| `fun.favorite_grid` | 本命九宫格 T2I & 人气榜 | 完整真实业务验收 | 0 / `1.21s` | 生成 `1080×1080` 带真实头像九宫格 PNG 并正确写入孤立排行投票 | **PASS** |
| `fun.voice` | 戳一戳语音 & 偏好设置 | 真实服务器部分链路 | 0 / <5ms | 语音设置指令与宿主 `/usr/bin/ffmpeg` & `ffprobe` 就绪通过（未触发实际 QQ 戳一戳外发） | **PASS** |
| `nav.help` | 帮助导航与分类详解 | 完整真实业务验收 | 0 / <5ms | 按运行配置动态裁剪输出，合同一致 | **PASS** |
| `misc.public_share` | 公开 UID / 第三方分享 / 手工资料 | Mock / 离线验收 | 0 / — | `enable_public_share_api=false` 默认关闭，未实网调用 `nikke-api.pages.dev` | **NOT_TESTED** |

> **核对汇总**：`PASS` = **19** · `DEGRADED` = **5** · `BLOCKED` = **2** · `NOT_TESTED` = **4**（合计 **30** 项）。

---

## 六、后续维护事项（Post-Merge Backlog，不在本轮扩大重做）

1. **练度查询并发性能与上游限流**：`GetUserCharacterDetails` 连续 20 次查询紧随 `profile` 后偶发触发 `request too frequently`（当前冷拉耗时 `22–31 s`，突发期依赖 `0.8s` 单次重试与 `roster_warm` 缓存补齐）；后续可在 Phase 3+ 结合实号样本继续评估分批节流策略，并跟踪主线新章节 ID 映射与最新 5 名新角色（`#5183–#5187`）目录同步。
2. **GitHub 冷素材超时与公告节点连通性**：冷缓存下首查全立绘/Spine 偶超 `6.0s` 硬预算降级剪影；服务器海外出口访问官方公告详情接口及 YouTube Atom 存在偶发超时/断连，后续上线运维需根据宿主机网络环境按需补充加速或本地素材预热缓存。
3. **指定参考 UID `84522455` 核实**：当前隔离库两行绑定账号中未匹配到该参考编号且样本 B 凭据已失效；如后续需专门验证该 UID，须先由账号本人提供对应绑定信息或重新绑定后再行验收。
4. **反代日志保护与可选数据导入**：正式合并部署开启任何 Web 扩展入口（尤其 ShiftyPad）前，务必同步 [`deploy/Caddyfile`](../../deploy/Caddyfile) 的 `log_skip /shiftypad/*`；若需消除 `DEGRADED`/`BLOCKED` 项，可由运营方按 `EXTERNAL_DATA_IMPORT.md` 校验流程自行导入合法赛季/成本表/推荐表与授权题库。
