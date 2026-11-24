# CAPABILITY_MATRIX.md — NIKKE 综合助手能力矩阵与双入口收敛规划基线

> **基线**：PR #144–#148 完成后状态（对应 `docs/p2-business-completion-gate`）  
> **状态口径**：`COMPLETE`（业务代码闭环，含离线验证；真机/线上未实测项见备注）、`PARTIAL`（核心已可用但依赖用户手工数据/外部实测确认）、`BLOCKED`（受外部授权题库或未实测上游接口阻塞，默认关闭/降级）。  
> **双入口目标（待 Phase 3–7 审批后实施）**：公共功能大厅（`/hall`，免账号/公共资料与计算器）与个人指挥官工作台（`/workspace`，个人绑定数据、养成历史与配置）。

---

## 一、能力总表（25 项既有与新增核心能力）

| ID | 能力名称 | QQ 命令入口 | 所需绑定层级 | 关键配置开关（`core/config.py`） | 当前状态 | 离线/CI 验证 | 真实环境待验项 | Phase 3–7 规划入口 |
|---|---|---|---|---|---|---|---|---|
| `acct.blabla_bind` | BlaBlaLink 完整绑定 | `/妮姬 账号 绑定`, `/nikke bind` | 无（私聊发起） | `allow_group_bind` (false), `web_port` (6210), `web_trusted_proxy_ip`, `binding_api_key` | **COMPLETE** | 离线+Extension+PR #144 CI | HTTPS 反代限流现场复验 | 工作台核心接入 |
| `acct.lifecycle` | 绑定状态 / 换绑 / 解绑 / 凭据失效 | `/妮姬 账号`, `账号 解绑`, `/nikke status\|unbind` | 本人记录 | — | **COMPLETE** | 离线+PR #144 CI | 线上多账号换绑观察 | 工作台（个人状态） |
| `acct.renewal` | 实验性会话续期 & 自动续期 | `/妮姬 账号 续期 [状态]`, `自动续期 开\|关` | 完整绑定（私聊） | `enable_daily_actions` (false) | **PARTIAL** | 离线 Mock 全过 | 长期续期实际有效期未证实 | 工作台只读状态 |
| `acct.shiftypad` | ShiftyPad 只读导入绑定 | `/妮姬 我的妮姬 导入\|只读\|同步\|解绑` | 仅只读导入（私聊发起） | `enable_shiftypad_readonly` (false) | **BLOCKED** | 离线 Mock Web/CSRF/存储全过（PR #145） | 上游 `User/GetUserProfile` 实测（BLOCKED） | 工作台（实验性只读导入） |
| `profile.dashboard` | 指挥官主页 / 进度 / 前哨 | `/妮姬 我的`, `/nikke me\|progress` | 完整绑定 | — | **COMPLETE** | T2I 离线+PR #144 CI | 生产实时字段微调 | 工作台首页 + 可选分享图 |
| `char.roster` | 角色练度总览 | `/妮姬 查询 练度`, `/nikke roster` | 完整绑定 | — | **COMPLETE** | T2I 离线+PR #144 CI | 批量练度 23 次请求（AUD-010）实测 | 工作台总览 + 可选分享 |
| `char.detail` | 单角色详细练度（OL/技能/皮肤/Spine） | `/妮姬 查询 练度 <名>`, `/nikke character <name>` | 完整绑定 | `spine_runtime_version` (4.0), `spine_worker_timeout` (4) | **COMPLETE** | PR #144 Python CI 通过（Spine worker CI 失败待修） | 新角色/皮肤 Spine 清单维护 | 工作台懒加载详情页 |
| `growth.history` | 养成历史快照与差异 | `/妮姬 养成历史 [清空]` | 完整绑定 + 身份隔离 | — | **COMPLETE** | PR #145 隔离/并发回写单测全过 | 长周期多账号实测 | 工作台时间线 |
| `combat.campaign` | 主线通关阵容 | `/妮姬 战役 <关> [普通\|困难]` | 完整绑定 | — | **COMPLETE** | T2I 离线+PR #144 CI | 实号样本拉取 | 工作台 / 大厅辅助 |
| `combat.tower` | 企业塔静态资料 | `/妮姬 塔层 <塔名> <层数>` | 无 | — | **COMPLETE** | 离线+PR #144 CI | 静态资料随版本更新 | 公共大厅 |
| `combat.char_info` | 角色基础资料 | `/妮姬 查询 资料 <名>`, `/nikke info <name>` | 无 | `custom_character_aliases` | **COMPLETE** | 离线+PR #144 CI | — | 公共大厅 |
| `combat.guide` | 本地授权攻略 | `/妮姬 攻略 [分类] [页码]` | 无 | — | **COMPLETE** | 离线+PR #144 CI（本机缺 symlink 权限） | 本地合规图文素材维护 | 公共大厅 |
| `combat.union_raid` | 联盟突袭（总览/排行/我的） | `/妮姬 突袭 [排名\|我的] [页码]` | 完整绑定 | — | **COMPLETE** | T2I 离线+PR #144 CI | 实号工会突袭数据 | 工作台 |
| `combat.arena_qq` | 竞技场解队 / 沙盒 / 持有过滤 | `/妮姬 竞技场 解队\|沙盒\|我的\|数据状态` | 沙盒无；持有过滤需完整绑定 | `enable_arena` (false) | **COMPLETE** | 离线+PR #144 CI | 静态模型仅作参考 | 大厅 + 工作台 |
| `combat.arena_web` | 竞技场临时网页（单/三队） | `/妮姬 竞技场 编辑\|三队\|结果` | 同上（私聊发链接） | `enable_arena` (false), `arena_web_enabled` (false) | **COMPLETE** | PR #144 CI Playwright 通过（本机缺 Chromium） | 线上与 `/hall` 底座统一 | 已有网页复用底座 |
| `combat.solo_raid` | 单人突袭五队编组与估伤 | `/妮姬 单人突袭 [赛季\|编组\|阵容图\|保存\|我的\|队]` | 手工无；`账号` 需完整绑定/只读 | — | **PARTIAL** | PR #146 规则/隔离/弱点纠偏全过 | 真实 `Jgaram/nikke-calc@67835ca` 实机压测 + 合法赛季 JSON 导入 | 大厅（沙盒编组）+ 工作台 |
| `event.calendar` | 活动日历与 24h 截止提醒 | `/妮姬 日程 [7\|14\|30] [页]`, `刷新\|订阅\|状态\|取消订阅` | 无 | — | **COMPLETE** | 离线+PR #144/148 单测全过 | 真实 QQ 群 @ 提醒现场验收 | 大厅 + 工作台订阅 |
| `event.gacha_board` | 卡池与活动分类板 | `/妮姬 卡池 [卡池\|活动\|皮肤\|突袭]` | 无 | — | **COMPLETE** | PR #148 修复 `unclassified` 计数并通过 | 线上实网日程数据 | 公共大厅 |
| `event.announcement` | 官方公告查询与全群广播订阅 | `/妮姬 公告 [语言\|分类\|搜索\|诊断\|深度刷新\|订阅\|取消订阅]` | 查询无；订阅/刷新需管理员 | `enable_announcement_push` (false) | **COMPLETE** | 离线+PR #144 CI | 真实 QQ 群公告推送验收 | 公共大厅（只读展示） |
| `event.news_feeds` | 个人新闻/官方视频/新日程订阅 | `/妮姬 新闻 [订阅\|状态\|取消订阅]` | 无（按会话+用户本人隔离） | — | **COMPLETE** | PR #148 状态文案澄清与单测全过 | YouTube Atom 实网与 QQ 私/群主动送达 | 工作台订阅管理 |
| `comm.daily_tasks_cdk` | 社区签到 / 领奖 / 浏览点赞 / CDK | `/妮姬 签到`, `日常 [任务]`, `兑换` | 完整绑定 + 独立写授权 | `enable_daily_actions` (false), `enable_cdk_redemption` (false), 预算限额 | **COMPLETE** | 离线 Mock + 未知态保护全过 | 真实账号写操作与两步恢复确认 | 工作台只读状态 + QQ 执行 |
| `tool.counsel` | 咨询答案检索（需授权中文题库） | `/妮姬 咨询 <妮姬> [关键词]` | 无 | — | **BLOCKED** | PR #147 匹配类型区分单测全过 | 等待合法授权中文题库导入（禁用无许可韩文表） | 公共大厅（导入后启用） |
| `tool.sync_calc` | 同步器等级/库存可升/瓶颈计算 | `/妮姬 同步器 [状态\|计算 ...]` | 可选（`计算 账号`） | — | **PARTIAL** | PR #147 可升计算与覆盖提示全过 | 待补充合法 1–200 级成本表或依赖手工输入 | 大厅 + 工作台 |
| `tool.overload` | 超限洗词条建议与同件概率模拟 | `/妮姬 洗词条 ...`, `洗词条模拟 ...` | 可选（`账号[:角色]` 对比） | — | **COMPLETE** | PR #147 跨部位/概率/实号对比单测全过 | 真实角色装备数据对比待实号验收 | 大厅 + 工作台 |
| `tool.wishlist` | 愿望单推荐（SSR 四大企业 + 160 墙） | `/妮姬 愿望单 [收集\|均衡\|养成] [角色池]` | 可选（读取账号已拥有 SSR） | — | **COMPLETE** | PR #146 企业分组与 SSR 160 墙全过 | 当期限定/联动池列表随版本更新 | 大厅 + 工作台 |
| `fun.tarot` | 妮姬塔罗 | `/妮姬 塔罗 [单抽\|三张\|今日\|状态\|帮助]` | 今日牌绑定本人身份 | — | **COMPLETE** | PR #144 CI 全过（本机缺 `assets/tarot`） | — | 大厅随机 + 工作台每日 |
| `fun.favorite_grid` | 本命九宫格 T2I 图卡 & 人气榜 | `/妮姬 九宫格 <9人>`, `/妮姬 本命榜` | 无（每人 1 票可覆盖） | — | **COMPLETE** | PR #148 单元测试 + Edge `1080×1080` 实图验收 | 部署机带真实立绘图的 T2I 渲染 | 公共大厅 |
| `fun.voice` | 戳一戳语音 & 语音设置 | 戳一戳；`/妮姬 语音 [开\|关\|语言\|角色\|服装]` | 无（个人设定按用户保存） | `voice_dynamic_enabled` (true) | **COMPLETE** | PR #144 CI 全过（本机缺 `ffmpeg` / 音频资产） | 宿主 `ffmpeg`/`ffprobe` 安装验收 | 大厅试听 + 工作台设定 |
| `nav.help` | 帮助导航与分类详解 | `/妮姬`, `/妮姬 帮助 [分类\|详解]` | 动态按配置/权限裁剪 | — | **COMPLETE** | 离线+PR #144 CI 全过 | — | 统一目录底座 |
| `misc.public_share` | 公开 UID 声明 / 第三方分享资料 / 手工资料 | `/妮姬 uid`, `我的妮姬 资料\|分享\|手工` | 无（不作账号归属证明） | `enable_public_share_api` (false) | **PARTIAL** | PR #145 默认关闭开关与披露测试全过 | `nikke-api.pages.dev` 线上实测 | 工作台辅助 |

---

## 二、安全与写开关默认值清单（`core/config.py` & `_conf_schema.json`）

所有外部写操作、实验性只读导入及第三方外传接口默认 **fail-closed (`false`)**：
- `allow_group_bind`: `false`
- `enable_arena`: `false`
- `arena_web_enabled`: `false`
- `arena_external_stats_enabled`: `false`
- `enable_daily_actions`: `false`
- `enable_announcement_push`: `false`
- `enable_cdk_redemption`: `false`
- `enable_shiftypad_readonly`: `false`（PR #145 新增）
- `enable_public_share_api`: `false`（PR #145 新增）
- 唯二默认开启项：`voice_dynamic_enabled`: `true`、`public_base_url`: `"https://nikke.irises777.xyz"`。
