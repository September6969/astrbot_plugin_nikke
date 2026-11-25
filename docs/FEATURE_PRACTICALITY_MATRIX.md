# NIKKE 综合助手 — 30 项核心能力实用性核查清单

> **基线版本**：`v0.3.1`（`feat/sync-calculator-v2` 合入 `main`，2026-11-25）  
> **核查范围**：全部 30 项注册能力（`features/catalog/registry.py`）覆盖 QQ 命令、公共大厅 `/hall` 与个人指挥官工作台 `/workspace`。

---

## 一、总览统计

| 可用级别 | 数量 | 说明 |
|---|---:|---|
| **开箱即用（免绑定公共能力）** | 12 | 无需账号绑定或管理员外部配置，内置开源/官方实时数据源即用 |
| **绑定账号后即用（个人只读/交互能力）** | 11 | 通过自助绑定扩展登录 BlaBlaLink 后自动读取账号数据可用 |
| **依赖管理员配置 / 外部二进制 / 外部授权导入** | 7 | 高风险写操作开关、MIT 外部引擎克隆或无开源授权外部题库 |

---

## 二、逐项实用性清单（全部 30 项）

| # | ID | 功能名称 | 分类 | 入口归属 | 实测可用状态 | 具体依据 / 外部条件与限制说明 |
|---:|---|---|---|---|---|---|
| 1 | `portal.hall` | 公共功能大厅 | 互动 | Hall (`/hall`) | **开箱即用** | 匿名访问、目录搜索、口令复制、群聊 `/妮姬 大厅` 反馈闭环完整。 |
| 2 | `portal.workspace` | 个人指挥官工作台 | 账号 | Workspace (`/workspace`) | **开箱即用** | `/workspace/open/{token}` 一次有效进入、按需懒加载、脱敏分享至 QQ。 |
| 3 | `account.bind` | 账号绑定与状态 | 账号 | QQ + Workspace (`binding`) | **开箱即用** | 自助 10 分钟绑定向导 + 浏览器扩展提交 + 状态/汇总开关/解绑闭环。 |
| 4 | `account.renewal` | 实验性会话续期 | 账号 | QQ 专用 | **需绑定 + 管理员写开关** | 默认关闭，需私聊绑定并开启 `enable_daily_actions`。 |
| 5 | `profile.me` | 指挥官个人进度 | 账号 | QQ + Workspace (`binding`) | **需绑定即用** | 实时读取等级、总战力、同步器、前哨、主线/无限塔、珠宝及核心材料并渲染 T2I。 |
| 6 | `identity.uid` | UID 边界与手工档案 | 账号 | QQ + Workspace (`settings`) | **开箱即用** | 明确区分数字 UID 与 OpenID；支持未绑定个人手工建档与查询。 |
| 7 | `growth.history` | 养成成长历史 | 账号 | QQ + Workspace (`binding`) | **需绑定即用** | 按 QQ + 游戏身份隔离自动记录战力/练度差异快照并支持一键清空。 |
| 8 | `character.roster` | 角色练度与单卡 | 养成 | QQ + Workspace (`roster`) | **需绑定即用** | 读取已持有妮姬排行与单角色技能/魔方/收藏品/T10 词条 T2I 详卡。 |
| 9 | `character.info` | 妮姬公开资料 | 养成 | QQ + Hall (`tools`) | **开箱即用** | 内置 `character_master.json` 200 名角色资料与 `character_aliases.json` 别名检索。 |
| 10 | `counsel.search` | 咨询答案检索 | 养成 | QQ + Hall（默认隐藏） | **需外部授权导入（默认隐藏）** | 公开开源仓无合法可再分发中文咨询题库；未导入时在公共大厅卡片/目录及帮助默认分类中隐藏，防止死入口。 |
| 11 | `sync.calculator` | 同步器升级计算 V2 | 养成 | QQ + Hall + Workspace (`tools`) | **开箱即用（绑定更佳）** | 内置 WTFPL `sync_level_costs.json`（Lv.2–1400）与 `outpost_rates.json`（Lv.1–800 含 Lv.533 跃升）；绑定后自动读等级/直存/前哨/学院课程；支持 `1H–24H` 资源箱、歼灭次数、额外日产及手工备用。 |
| 12 | `wishlist.advisor` | 普通招募愿望单推荐 | 养成 | QQ + Hall + Workspace (`tools`) | **开箱即用（绑定更佳）** | 内置 `wishlist_pool_eligibility.json` 已全量核验 171 名 SSR（**0 个未知项**）；含 `scripts/operations/update_wishlist_eligibility.py` 可持续增量更新。 |
| 13 | `overload.advisor` | 超限洗词条建议与模拟 | 养成 | QQ + Hall + Workspace (`tools`) | **开箱即用（绑定更佳）** | 内置源自 MIT `nikke-calculator` 的 200 角色专属词条推荐 + 末弹/蓄速避坑规则；支持 `/妮姬 洗词条 爱丽丝` 查推荐、工作台绑定角色 T10 实装自动对比，以及基于 MIT 权重（10%/12%）洗炼模拟。 |
| 14 | `arena.solver` | 竞技场解队与三队编辑 | 竞技场 | QQ + Workspace (`arena`) | **需管理员开关 (`enable_arena`)** | 生产已启用；单队文字解队开箱即用，网页可视化编辑器需额外启用 `arena_web_enabled`。 |
| 15 | `raid.union` | 联盟突袭统计 | 突袭 | QQ 专用 | **需绑定即用** | 实时读取联盟突袭总览、贡献排名、个人出刀记录并输出 T2I 图表。 |
| 16 | `solo_raid.planner` | 单人突袭五队与估伤 | 突袭 | QQ + Workspace (`solo-raid`) | **开箱即用（完整估伤需 `nikke-calc`）** | 内置 S36–S43 核验赛季/属性/弱点/机制，并在运行时从官方缓存公告增量识别新赛季（及 Raid Rush 休赛）；生产 `serv` 已装配 MIT `nikke-calc@67835ca` 真实计算。 |
| 17 | `campaign.clear` | 主线战役通关记录 | 攻略 | QQ 专用 | **需绑定即用** | 通过 BlaBlaLink 查询所在服务器主线常规/困难低战力通关作业。 |
| 18 | `tower.floor` | 无限之塔楼层资料 | 攻略 | QQ + Hall (`guides`) | **开箱即用** | 内置 `tower_floors.json` 静态楼层战力与敌方构成数据。 |
| 19 | `guide.images` | 一图流攻略目录 | 攻略 | QQ + Hall (`guides`) | **开箱即用** | 内置授权一图流攻略图片目录，支持 QQ 与公共大厅分页查看。 |
| 20 | `calendar.schedule` | 活动日程总览 | 活动 | QQ + Hall (`calendar`) | **开箱即用** | 定时刷新并冻结官方活动日历，支持群聊回推与 T2I 长图渲染。 |
| 21 | `calendar.board` | 卡池 / 皮肤 / 突袭分类板 | 活动 | QQ + Hall (`calendar`) | **开箱即用** | 按卡池/活动/皮肤/突袭分类展示剩余时间（UP 概率官方未提供时显式标明）。 |
| 22 | `calendar.subscription` | 个人日程截止订阅 | 活动 | QQ 专用 | **开箱即用** | 按会话选择订阅事件类型并在截止前发出提醒。 |
| 23 | `announcement.view` | 官方公告检索 | 活动 | QQ + Hall (`announcements`) | **开箱即用** | 定期抓取官方多语种公告缓存并支持关键词/语种过滤。 |
| 24 | `feeds.subscription` | 新闻 / 视频 / 日程订阅 | 活动 | QQ + Workspace (`settings`) | **开箱即用** | 官方 YouTube Atom + 公告 + 日程独立状态机，支持工作台查看状态。 |
| 25 | `daily.checkin` | 社区签到与状态 | 福利 | QQ 专用 | **需绑定（签到动作需写开关）** | `/妮姬 签到 状态` 绑定即查；执行签到受安全写开关限制。 |
| 26 | `daily.routine` | 社区日常与自动执行 | 福利 | QQ 专用 | **需绑定 + 管理员写开关 (`enable_daily_actions`)** | 生产默认关闭以防异常风控；由运营者按需开启。 |
| 27 | `cdk.redeem` | 国际服 CDK 兑换 | 福利 | QQ 专用 | **需绑定 + 管理员开关 (`enable_cdk_redemption`)** | `可用/历史` 查询只读；实际兑换需绑定且开启开关。 |
| 28 | `tarot.draw` | NIKKE 塔罗占卜 | 互动 | QQ + Hall (`tarot`) | **开箱即用** | 内置完整大小阿尔卡那牌库与立绘，支持单抽/三张及大厅一键回推群聊。 |
| 29 | `favorite_grid.board` | 本命九宫格与人气榜 | 互动 | QQ + Hall (`announcements`) | **开箱即用** | QQ 生成 3×3 九宫格图片并计票，公共大厅实时查看人气榜 Top 10。 |
| 30 | `voice.poke` | 戳一戳语音互动 | 互动 | QQ 专用 | **开箱即用** | 支持语音开关、角色/服装/语言偏好设置与戳一戳触发语音回复。 |
| 31* | `admin.ops` | 运行健康与调度管理 | 管理 | QQ 管理员专用 | **仅管理员** | 健康巡检、群绑定、每日任务定时设定及深度刷新公告。 |

> **关键收束项**：本轮一并消除了功能目录 `registry.py` 中 11 处 `web_tab` 与实际页面标签不一致的问题，并在 QQ、公共大厅、个人工作台之间补齐了超限专属推荐、单人突袭实时赛季联动及同步器完整资源箱计算的交互一致性。
