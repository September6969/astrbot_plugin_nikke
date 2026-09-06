# 当前执行状态（2026-09-06）

本表是当前状态入口；下方旧计划保留为历史规格，其中 TODO/BLOCKED 不再作为当前进度判断。
最新执行规则见 [审核与自治计划](EXECUTION_AUTONOMY_PLAN.md)，优先于历史资源策略。

| 范围 | 当前状态 | 已完成与剩余 |
| --- | --- | --- |
| 审核修复 | DONE | 序关系脱敏、Guide registry 强制入口、单条取消 unknown、用户隔离 cooldown、移除临时 CI trigger |
| 公告来源/缓存/订阅/调度 | PARTIAL | 正式 CMS、退避、独立版本、默认关闭调度已实现；状态清理已实现，深度重扫待做 |
| Campaign | PARTIAL | 3572 关卡映射、严格阵容与异常合同；更丰富渲染待做 |
| Tower | DONE | 7350 层公开静态查询，不代表账号进度 |
| Profile | PARTIAL | 结构化研究与收藏、名称映射；完整分区继续完善 |
| Raid | PARTIAL / NEEDS_LIVE_EVIDENCE | 当前响应排名、历史客户端、诊断已实现；身份、多轮、范围仍待证据 |
| Daily | PARTIAL / NEEDS_LIVE_EVIDENCE | 单次写后只读验证；Like/Browse 未证明状态变化 |
| CDK | PARTIAL | 串行批量持久化、取消及硬崩溃保护；过期 running 原子转 unknown，禁止重放；统一编排仍可改进 |
| Voice | PARTIAL | 本地音频、偏好、发送器与隔离 cooldown；动态源与两级缓存已实现并匿名验证；角色/皮肤映射与动态 Poke 接线待做 |
| Spine | PARTIAL | 队列与无运行时预检查；真实运行时和 Linux 渲染基准待做 |
| Guide | DEFERRED | 保留框架/分页/占位，不生成、不抓取、不添加素材；当前不需要用户行动 |
| 许可证最终采用 | NEEDS_HUMAN_DECISION | 仅生产采用具体 runtime 时确认，不阻止先研究与工程验证 |
| 静态装备/魔方/珍藏品/技能 | PARTIAL | 已找到公共数据源，完整 registry 与数值验证待做 |
| HARD_BLOCKED | 无确认项 | 不将尚未研究完的事项视为永久阻塞 |

## 历史规格归档（以下状态仅描述撰写时情况）

# NIKKE BlaBlaLink 插件 — 主开发文档（仓库扫描修订版）

> 仓库：`September6969/astrbot_plugin_nikke`  
> 默认分支：`main`  
> 当前基线：`main@deeef6277f09a42918d71b44f49170398a05558b`  
> 插件版本：`0.1.8`  
> 基线来源：PR #4 已合并，merge commit `deeef6277f09a42918d71b44f49170398a05558b`  
> CI 基线：Python 3.10 / 3.11 / 3.12 全绿；Python 3.12 为 `180 passed, 2 warnings, 28 subtests passed`  
> 修订方式：按当前 GitHub `main` 实际目录、代码、测试、fixture、扩展、部署文件重新扫描，并合并此前全部已计划但尚未完成的功能。  
> 本文件替代此前“按计划推断”的版本；以后判断进度优先看当前代码与测试，而不是旧 checkbox。

---

# 0. 本次扫描后的关键修正

这次扫描对此前文档做了几项重要纠正。

## 0.1 PR #4 已经在 main

不再使用：

```text
PR #4 待合并
master@25b2116
```

作为当前状态。

当前有效代码基线是：

```text
main@deeef6277f09a42918d71b44f49170398a05558b
```

## 0.2 仓库里目前没有 contracts/ 和 evidence/ 目录

此前规划中出现过：

```text
contracts/*.md
evidence/*
```

但这两个目录 **并不存在于当前 GitHub main**。

当前真正承担“证据”角色的是：

```text
tests/fixtures/
scripts/capture_profile_fixtures.py
scripts/capture_union_raid_fixtures.py
tests/*
```

部分源码 docstring 仍写着：

```text
遵循 contracts/xxx.md
```

这属于历史文档引用，不应被理解为仓库里已经存在这些文件。

后续有两种选择：

1. 保持本主文档 + tests/fixtures 为单一开发依据；
2. 真正把 `docs/contracts/` 和 `docs/evidence/` 建进仓库。

在实际创建前，不再把它们写成“现有架构”。

## 0.3 Union Raid Phase 2 不是“完全没有真实数据”

当前仓库已经有 4 份联盟突袭 fixture：

```text
tests/fixtures/union_raid_overview.json
tests/fixtures/union_raid_boss_list.json
tests/fixtures/union_raid_ranking.json
tests/fixtures/union_raid_my_data.json
```

其中 ranking / my_data 都来自：

```text
POST /api/game/proxy/Game/GetUnionRaidData
```

并已经看到：

```text
participate_data[]
openid
nickname
total_damage
boss_id
day
difficulty
level
step
is_final_hit
squad[]
  tid
  lv
  combat
  costume_id
  slot
```

所以后续 Raid Phase 2 的起点不是“先发现接口”，而是：

```text
修 fixture 抓取脚本
改进脱敏方式
保留可聚合关系
再实现 Attack / Participant / Ranking 模型
```

## 0.4 但当前 Raid fixture 抓取脚本本身已经落后于 client 修复

当前：

```text
scripts/capture_union_raid_fixtures.py
```

仍然存在两个旧合同：

```python
game_openid = openid.split("-")[-1]
```

以及：

```python
GetMyGuildInfo(
    {
        "nikke_area_id": area_id,
        "intl_open_id": game_openid
    }
)
```

这与 PR #4 已确认并修复的生产 client 不一致。

生产 client 当前正确合同是：

```python
GetMyGuildInfo({"ignore_toast": True})
```

且：

```text
完整 openid 透传，不 split
```

因此 **在修复 capture script 之前，不应该继续用它生成新的 Raid 证据 fixture**。

## 0.5 README 已明显落后于 main

README 当前仍然：

- 没有完整列出战役、联盟突袭、公告、日程、攻略、CDK 批量/可用/历史。
- 仍把签到描述为“尚未通过真实写接口验收”，而当前代码已经实现 `DailyCheckIn` 和写后查询，但默认关闭。
- 测试说明仍偏旧，没有反映当前 pytest 180 测试。
- 没有准确描述 Profile / Raid / Campaign 新 Renderer。

所以 README 同步应进入最近一次维护 PR。

---

# 1. 状态定义

本文统一使用：

| 状态 | 含义 |
|---|---|
| `DONE` | 当前主链已完成，测试覆盖足够，可正常维护 |
| `PARTIAL` | 功能已经可用，但合同、UI 或生产可靠性仍有明确缺口 |
| `MVP` | 第一阶段范围可用，但刻意未实现完整产品目标 |
| `SPIKE` | 仅工程验证或骨架，不能称为正式功能 |
| `TODO` | 尚未实现 |
| `BLOCKED` | 需要真实响应或外部证据，禁止凭猜测继续 |
| `DEBT` | 已确认存在的技术/合同债，应在扩展功能前处理 |

---

# 2. 仓库实际结构

当前 main 主要文件如下：

```text
.github/
  workflows/ci.yml

deploy/
  Caddyfile
  docker-compose.caddy.yml

extension/
  manifest.json
  background.js
  popup.js
  popup.html

assets/
  README.md
  campaign_stages.json
  cubes.json
  equipment.json
  favorite_items.json
  sources.json

scripts/
  capture_profile_fixtures.py
  capture_union_raid_fixtures.py
  preview_character_cards.py

tests/
  fixtures/
  extension.test.cjs
  test_announcements.py
  test_asset_manager.py
  test_campaign_history.py
  test_card_builder.py
  test_cdk.py
  test_character_card_renderer.py
  test_configuration.py
  test_core.py
  test_feedback_and_voice.py
  test_nikke_db_provider.py
  test_theme_and_profile.py
  test_union_raid.py

main.py
client.py
storage.py
web_service.py

renderer.py

card_models.py
card_builder.py
card_theme.py
character_card_renderer.py

profile_models.py
profile_builder.py
profile_card_renderer.py

union_raid_models.py
union_raid_builder.py
union_raid_renderer.py

campaign_history_models.py
campaign_history_builder.py
campaign_history_renderer.py
campaign_stage_resolver.py

cdk_models.py
cdk_service.py

announcement_models.py
announcement_service.py

asset_manager.py
nikke_db_provider.py
spine_prerenderer.py

processing_feedback.py
voice_feedback.py

_conf_schema.json
_version.py
metadata.yaml
requirements.txt
README.md
LICENSE
NOTICE
```

当前还没有：

```text
docs/
contracts/
evidence/
```

---

# 3. 当前产品状态总表

| 子系统 | 状态 | 当前实际情况 |
|---|---|---|
| 安全绑定 | `DONE` | MV3 扩展 + HTTPS 绑定服务 + 单次 token + Cookie/XCommon 加密 |
| 账号状态 | `DONE` | 绑定、解绑、Cookie 状态、汇总开关 |
| 练度总览 | `DONE` / legacy UI | 可用，但仍走旧 CardRenderer |
| 单角色练度卡 | `DONE` | 1800×1000、新 Builder、四槽装备、目标角色定向请求 |
| Profile | `PARTIAL` | 主体完成，Research/Collection 仍摘要化 |
| Campaign History | `MVP + DEBT` | NORMAL 46 / HARD 35 可用；未知错误传播仍需收紧 |
| Union Raid Overview | `MVP + DEBT` | Boss HP 总览可用；多轮选择和 HP clamp 有债 |
| Union Raid Ranking/My | `TODO`，已有结构 fixture | GetUnionRaidData fixture 已有，但未建模型/命令 |
| CDK 单条 | `DONE` | 幂等、超时 unknown、业务错误、真实字段合同较完整 |
| CDK 批量 | `PARTIAL` | 串行/账号锁已有；未复用 action_runs 持久幂等 |
| 公告/日程查询 | `PARTIAL + DEBT` | 缓存/解析/查询可用；正式源和版本逻辑有债 |
| 公告自动推送 | `TODO` | 去重基础有，目标订阅/调度发送未完成 |
| 社区签到 | `PARTIAL + SAFETY DEBT` | 写接口与写后查询已有；模糊超时后可能再次提交 |
| 点赞/浏览日常 | `TODO` | 未实现 |
| AssetManager | `PARTIAL` | 静态资源链完整度较高，资源映射仍不全 |
| Spine | `SPIKE` | 队列/版本/cache 骨架有，真实 render 仍返回 None |
| Poke/Voice | `SPIKE` | 当前是文本台词，不是真实 QQ 音频 |
| Guide | `SKELETON` | 命令路由有，但 assets 下当前没有 guides 内容目录 |
| CI | `PARTIAL` | Python CI 绿；Node extension test 没接入，branch protection 未强制 |
| README/Docs | `DEBT` | README 与 main 功能面明显不同步 |

---

# 4. 版本、平台与依赖

当前：

```text
PLUGIN_VERSION = 0.1.8
AstrBot >=4.24,<5
support_platforms:
  aiocqhttp
```

Python 依赖：

```text
aiohttp >=3.10,<4
cryptography >=43,<51
httpx >=0.27,<1
Pillow >=11,<13
```

当前 CI 实际验证：

```text
Python 3.10
Python 3.11
Python 3.12
```

因此文档中的 Python 支持应写成：

```text
Python 3.10–3.12：CI 已验证
Python 3.13+：当前未验证
```

不要仅因为 README 写了 “Python 3.10+” 就默认 3.13 已兼容。

原因之一是 CI 当前已经出现：

```text
audioop deprecated and slated for removal in Python 3.13
```

---

# 5. CI 当前真实状态

当前 `.github/workflows/ci.yml`：

```text
push: master, main
pull_request: master, main
```

Python matrix：

```text
3.10
3.11
3.12
```

执行：

```text
pip install -r requirements.txt
pip install pytest pytest-asyncio astrbot

python -m compileall -q .
python -c "import astrbot_plugin_nikke"
pytest -v
```

PR #4 merge 后的 main push CI：

```text
180 passed
2 warnings
28 subtests passed
```

## 5.1 CI 已覆盖

当前测试已经覆盖：

```text
绑定 API
Cookie 加密
账号隔离
x-common / canonical openid 恢复
Profile fixtures
单角色四槽装备
单角色 Renderer
资源 fallback/cache
Campaign
CDK
Announcement
Union Raid Overview
Delayed feedback
VoiceResolver
NikkeDbProvider
Theme
command routing
```

## 5.2 CI 仍有缺口

仓库存在：

```text
tests/extension.test.cjs
```

它使用 Node 内置 `node:test` 验证：

```text
自建绑定域名
拒绝错误域名
账号切换时不复用旧 xCommon
损坏缓存 fallback
当前账号 xCommon 完整保留
```

但当前 GitHub Actions **只运行 pytest，没有运行这个 Node 测试文件**。

建议补：

```yaml
- name: Test browser extension
  run: node --test tests/extension.test.cjs
```

另外：

```text
main branch 当前没有 required status checks / branch protection
```

因此“CI 绿”目前是事实，但“合并必须 CI 绿”尚未由 GitHub 强制。

## 5.3 workflow 分支清理

仓库默认分支已经是：

```text
main
```

CI 仍监听：

```text
master, main
```

当前 GitHub 甚至对相同 merge commit 出现了 main/master 两个 push run。

后续可以确认旧 master 是否还需要保留；如果不需要：

```text
只监听 main
```

减少重复 CI。

---

# 6. 安全绑定与账号存储

状态：`DONE`

这一块比此前主文档描述得更完整，应单独作为稳定子系统。

## 6.1 浏览器扩展

MV3 扩展权限：

```text
cookies
tabs
storage
webRequest
```

host_permissions：

```text
https://*.blablalink.com/*
当前绑定服务器 origin
```

运行时打包时：

```text
main.py
↓
读取 extension/manifest.json
↓
将绑定域名替换为 public_base_url
↓
生成 data/nikke/nikke-bind-extension.zip
```

## 6.2 x-common 获取

`background.js`：

```text
只监听 BlaBlaLink outbound request headers
只读取 x-common-params
不读取 requestBody
不读取 response
```

`popup.js`：

```text
只接受扩展 manifest 允许的 HTTPS 绑定 origin
路径必须 /bind/<token>
读取 www.blablalink.com 实际 cookie
要求 game_token/game_uid/game_openid
```

若缓存 xCommon 的 openid 与当前账号不同：

```text
不复用旧缓存
```

否则 fallback 使用当前 cookie 构造最小 context。

## 6.3 服务端绑定边界

BindingWebService 已实现：

```text
HTTPS public_base_url 校验
每远端约 60 req/min
CORS 限制
client_max_size 64KiB
token 格式校验
10 分钟绑定 session
单次消费
Cookie domain 过滤
Cookie count / value / total header 上限
x-common JSON 校验
公开错误脱敏
```

## 6.4 存储

NikkeStore：

```text
SQLite
WAL
foreign_keys ON
Fernet
```

密钥：

```text
NIKKE_ENCRYPTION_KEY
或
data/nikke/secret.key
```

secret.key 创建后：

```text
chmod 600
```

加密字段：

```text
cookie
x_common_params
```

账号独立 key：

```text
qq_id
```

绑定 session token：

```text
只保存 SHA-256
```

## 6.5 这一块下一步

不是功能开发优先级。

仅维护：

```text
安全回归
部署文档
依赖升级
AstrBot API 兼容
```

---

# 7. 主路由与命令面

当前统一根命令：

```text
/妮姬
alias: /nikke
```

主要中文入口：

```text
/妮姬 帮助

/妮姬 账号
/妮姬 账号 绑定
/妮姬 账号 解绑
/妮姬 账号 汇总 开|关

/妮姬 我的

/妮姬 查询 练度
/妮姬 查询 练度 <角色名>
/妮姬 查询 资料 <角色名>

/妮姬 战役 [普通/困难] <关卡>
/妮姬 联盟突袭

/妮姬 日程
/妮姬 公告
/妮姬 攻略 [分类]

/妮姬 签到
/妮姬 签到 状态

/妮姬 兑换 <CDK>
/妮姬 兑换 批量 <CDK...>
/妮姬 兑换 可用
/妮姬 兑换 历史

/妮姬 戳一戳 [角色名]
```

管理员：

```text
/妮姬 管理 设群
/妮姬 管理 任务时间 HH:MM
/妮姬 管理 汇总时间 HH:MM
/妮姬 管理 执行
/妮姬 管理 健康
```

旧英文平铺指令仍保留兼容。

---

# 8. Scheduler / Lifecycle

状态：`PARTIAL`

主 scheduler：

```text
每 20 秒循环
```

处理：

```text
daily task time
summary time
announcement sync
```

公告：

```text
约每 3600 秒 sync
```

每日任务与汇总使用北京时间。

## 8.1 已有

```text
last_daily
last_summary
全账号 stagger
max_concurrency
summary target
```

## 8.2 生命周期债务

scheduler 内部使用：

```python
asyncio.create_task(self._run_all_daily(...))
asyncio.create_task(self._send_summary(...))
asyncio.create_task(self._sync_announcements_background())
```

但这些动态创建的 task 没有统一加入：

```text
self._background_tasks
```

`terminate()` 只会取消当前记录在 `_background_tasks` 的 task。

因此插件关闭时：

```text
已经启动的 daily / summary / announcement task
可能继续运行到自身结束
```

建议未来抽一个统一 task registry：

```text
spawn_background(coro)
track
done callback remove
shutdown cancel + gather
```

---

# 9. 练度总览

状态：`DONE / legacy renderer`

命令：

```text
/妮姬 查询 练度
```

目前仍走：

```text
client.get_roster(include_details=True)
↓
renderer.CardRenderer.render_roster()
```

显示：

```text
前 20 名
按 combat / level 排序
等级
战力
技能
突破
核心
```

这一条仍属于旧 1200px 通用卡。

## 9.1 Legacy equipment_effects

`get_roster(include_details=True)` 仍会生成：

```text
equipment_effects
```

这是历史练度/AEL 用途。

允许继续存在，但必须明确：

```text
不能用于重建四槽装备
```

单角色卡已经不依赖它。

---

# 10. 单角色练度卡

状态：`DONE`

命令：

```text
/妮姬 查询 练度 <角色名>
```

链路：

```text
directory match
↓
GetUserCharacters（确认持有）
↓
GetUserCharacterDetails（只请求目标 name_code）
↓
CharacterCardBuilder
↓
AssetManager
↓
CharacterCardRenderer
```

## 10.1 四槽合同

只使用：

```text
head
torso
arm
leg

{slot}_equip_tid
{slot}_equip_lv
{slot}_equip_option1_id
{slot}_equip_option2_id
{slot}_equip_option3_id
state_effects
```

禁止从：

```text
equipment_effects
```

反推槽位。

## 10.2 词条

百分比内部：

```python
abs(raw) / 10000
```

UI 再乘 100 显示 `%`。

未知词条：

```text
显示
不加入已知总和
```

function_value_type 与预期冲突：

```text
按 unknown
```

## 10.3 UI

当前测试锁定：

```text
1800 × 1000
```

并测试：

```text
内部 ID 不进入最终卡片
空装备
长名字
完整 summary
```

这一模块现在不是近期优先开发对象。

---

# 11. Profile Dashboard

状态：`PARTIAL`

命令：

```text
/妮姬 我的
```

数据源：

```text
PROFILE       required
OUTPOST       optional
CHARACTERS    optional
```

`get_profile_dashboard()` 使用：

```text
asyncio.gather(return_exceptions=True)
```

### 语义

```python
roster: list[dict] | None
```

```text
None = 获取失败
[]   = 成功但空
```

character_count：

```text
Basic 有 → Basic
Basic 无 + roster 成功 → len(roster)
roster 失败 → None
```

max_level / max_combat：

```text
roster 非空 → max
roster 空/失败 → None
```

## 11.1 当前 Model 仍是摘要结构

ProfileDashboardData 当前只有：

```text
recycle_room_summary: str | None
memorial_summary: str | None
```

没有：

```text
RecycleResearchData[]
CollectionData[]
```

Builder 当前：

```text
recycle_room_researches[]
↓
仅抽 lv
↓
“X 项 · 等级合计 Y”
```

## 11.2 Renderer

当前 1200px 动态卡分区：

```text
BASIC INFO
OUTPOST
ROSTER
MORE
```

普通/困难 Campaign 仍在 Basic。

Research / Collection 仍是摘要字段。

## 11.3 下一步

Profile 下一阶段应只做合同收尾：

```text
保留 recycle_room_researches 原始 tid/lv/exp
建立 DTO
未确认 TID 不猜名字
独立 Collection / Research section
```

不需要再重写整个 Profile。

---

# 12. Campaign History

状态：`MVP + CONTRACT DEBT`

命令：

```text
/妮姬 战役 [普通/困难] <关卡>
```

Endpoint：

```text
POST /api/game/proxy/Game/GetMainQuestClearLineup
```

请求：

```json
{
  "stage_id": ...,
  "area_id": ...
}
```

## 12.1 Stage Map

当前仓库静态 map：

```text
NORMAL Chapter 46
HARD Chapter 35
```

禁止公式推导 stage_id。

## 12.2 Builder 已正确收紧

成功必须：

```text
code == 0
data.list 是非空 list
原响应完全无 malformed item
最终恰好 5 人
slot == {1,2,3,4,5}
```

每项必填：

```text
tid
lv
combat
slot
```

错误：

```text
1300017 → UNAVAILABLE
212000  → RATE_LIMITED
```

## 12.3 仍存在的 Client 合同债

`client.get_main_quest_clear_lineup()` 当前：

```text
1300017 → 返回受控 dict
212000  → 返回受控 dict
300001  → CookieExpired
其它 BlaBlaError → 也转换成 generic dict
```

此前合同希望：

```text
未知业务错误/其它 BlaBlaError 继续抛出
```

原因：

```text
不要把未知 auth/server/business error
静默转换成普通“历史阵容错误状态”
```

建议修成：

```python
if code == "1300017":
    ...
elif code == "212000":
    ...
elif code == "300001":
    ...
else:
    raise
```

这是 Campaign 当前最明确的代码债。

---

# 13. Union Raid Overview

状态：`MVP + CONTRACT DEBT`

当前命令：

```text
/妮姬 联盟突袭
```

生产 client：

```text
GetMyGuildInfo({"ignore_toast": True})
↓
guild_id
↓
GetUnionRaidLevelInfo({
    guild_id,
    nikke_area_id,
    intl_open_id: 完整 openid
})
```

## 13.1 当前已确认

```text
current_hp = 剩余 HP
max_hp = 最大 HP
```

状态：

```text
current_hp == 0 → DEFEATED
其它正 HP → UNKNOWN
未知/非法 HP → UNKNOWN
```

不按数组位置猜：

```text
CURRENT
NEXT
LOCKED
```

## 13.2 当前仍直接取 level_info 第一项

Builder：

```python
for lvl in levels:
    if isinstance(lvl, dict):
        current_level_obj = lvl
        break
```

所以多 difficulty / level 场景仍未解决。

这项仍：

```text
BLOCKED by representative multi-level response
```

## 13.3 当前 HP clamp 还有一个具体债

当前解析：

```python
current_hp = max(0, int(current_hp_raw))
```

但没有：

```python
min(current_hp, max_hp)
```

因此异常响应：

```text
current_hp > max_hp
```

时：

```text
hp_percent > 1
total_current > total_max
```

UI bar 虽然再 clamp，但 DTO/文本与总血量仍可能不一致。

统一合同应改为：

```python
safe_current = max(0, min(current_hp, max_hp))
```

并用于：

```text
RaidBossData.current_hp
hp_percent
total_current
total_progress
```

同时补：

```text
current_hp > max_hp
negative current_hp
```

测试。

---

# 14. Union Raid Phase 2

状态：`TODO，但结构证据已经存在`

这是此前文档需要修正最大的部分。

## 14.1 已有 fixture

仓库已有：

```text
union_raid_ranking.json
union_raid_my_data.json
```

Endpoint：

```text
POST /api/game/proxy/Game/GetUnionRaidData
```

请求 keys 已记录：

```text
guild_id
intl_open_id
nikke_area_id
```

结构中已经观察到：

```text
data.banned_result
data.contents_open_result
data.participate_data[]

participate_data item:
  boss_id
  day
  difficulty
  element_id[]
  icon_id
  is_final_hit
  level
  monster_model_id
  name_localvalues
  nickname
  openid
  squad[]
  step
  total_damage
```

squad：

```text
tid
lv
combat
costume_id
slot
```

## 14.2 当前 fixture 的问题

现有 capture sanitizer：

```python
int -> 0
float -> 0.0
str -> "[已脱敏]"
```

也就是说：

```text
所有 openid → 同一个 “[已脱敏]”
所有 total_damage → 同一个 “[已脱敏]”
所有数字 → 0
```

这保留了：

```text
字段结构
容器结构
```

但破坏了：

```text
同一参与者跨攻击的关系
不同参与者的区分
伤害大小关系
并列关系
squad slot 的有效值
day/step 的差异
```

所以现有 fixture 适合：

```text
schema regression
```

不适合：

```text
ranking aggregation regression
identity grouping regression
tie ranking regression
chronology regression
```

## 14.3 下一版脱敏要求

改用 relationship-preserving sanitizer。

示例：

```text
真实 openid A → user_01
真实 openid A → user_01
真实 openid B → user_02

真实 nickname A → member_01
真实 nickname B → member_02

伤害：
保留相对结构但替换为安全构造值
例如 1_000_000 / 700_000 / 700_000
```

squad 可保留：

```text
slot 1..5
lv 使用安全构造值
combat 使用安全构造值
tid 使用稳定伪 ID 或已公开静态 ID
costume_id 使用稳定伪 ID
```

## 14.4 Capture script 必须先修

当前 script 仍有：

```python
openid.split("-")[-1]
```

以及错误 GetMyGuildInfo payload。

所以 Roadmap 必须先：

```text
Fix capture_union_raid_fixtures.py
↓
relationship-preserving sanitize
↓
重新抓 fixture
↓
才开始 Phase 2 builder
```

## 14.5 Phase 2 Model

建议：

```python
RaidSquadMember
RaidAttackData
RaidParticipantSummary
RaidRankingData
RaidMyData
```

### RaidAttackData

只包含已验证字段：

```text
participant_key（内部稳定伪/真实 openid，仅 service 内）
nickname（展示字段但非 join 主键）
boss_id
day
difficulty
level
step
total_damage
is_final_hit
squad
```

不要在最终 Renderer DTO 中暴露真实 openid。

## 14.6 聚合

在同一个 GetUnionRaidData 响应内：

```text
group by openid
```

可以作为当前安全聚合方式。

目前仍未确认：

```text
GetGuildMembers.member_id
↔
GetUnionRaidData.openid
```

所以不能按 nickname 强 join。

## 14.7 Ranking

若无法证明响应覆盖完整赛季：

```text
标题：当前数据范围排名
```

不能写：

```text
赛季总排名
```

排序：

```text
total_damage DESC
```

并列：

```text
相同 total_damage → 同 rank
```

不要用 nickname/openid 作为伪官方 tiebreak。

## 14.8 “我的”

当前 capture script 通过多个 openid candidate 过滤自己的记录，说明至少结构上存在实现路径。

正式产品实现前必须确认：

```text
绑定账号的 canonical game_openid
是否与 participate_data[].openid 完全同域
```

如果不能稳定确认：

```text
/妮姬 联盟突袭 我的
→ 功能不可用
```

不能 fallback nickname。

---

# 15. CDK

状态：`单条 DONE / 批量 PARTIAL`

## 15.1 API

可用：

```text
POST GetCdkRedemption
payload {}
```

历史：

```text
POST GetCdkRedemptionHistory
payload:
{
  page_num: 1,
  page_size: 20
}
```

兑换：

```text
POST RecordCdkRedemption
payload:
{
  cdkey: original_case_code
}
```

## 15.2 输入

单条与批量共享：

```regex
[A-Za-z0-9_-]{4,64}
```

保持大小写。

## 15.3 单条

main 单条有持久化 action_runs：

```text
run key =
cdk:
qq_id:
game_uid:
SHA256(code)
```

支持：

```text
duplicate protection
running protection
stale running reclaim
unknown/retryable
```

网络/timeout：

```text
RESULT_UNKNOWN 语义
```

不会直接说“兑换失败”。

## 15.4 批量

当前：

```text
max_items = 10
default delay = 0.5s
同账号 async lock
串行
rate limit stop
CookieExpired stop
```

但批量路径：

```text
CdkService.redeem_batch()
↓
_redeem_single_core()
```

没有复用 main 单条的：

```text
action_runs persistent idempotency
```

因此：

```text
用户重复执行同一批 batch
会再次向官方接口提交这些 code
```

虽然已兑换码可能由官方返回 terminal error，但这仍是额外写请求。

如果要把批量标为 `DONE`，建议补：

```text
per-code persistent run key
或
批量命令复用单条 idempotent execution primitive
```

## 15.5 Batch 参数

当前真实代码：

```text
最多 10
0.5 秒间隔
```

旧文档出现过：

```text
20
2.0 秒
```

旧值没有足够证据，不再作为合同。

后续调整应基于：

```text
真实频控观察
安全边界
用户体验
```

---

# 16. Daily / Sign-in

状态：`PARTIAL + WRITE SAFETY DEBT`

当前已实现：

```text
GetTaskListWithStatusV2
DailyCheckIn
```

流程：

```text
先查任务
已完成 → 不写
未完成 → POST
写后再查
```

这是正确方向。

## 16.1 当前实际 retry

`perform_daily_signin()` 最多循环 3 次。

一次 POST 发生 `BlaBlaError` 后：

```text
记录 last_error
↓
重新 query status
↓
若仍未完成
↓
下一轮可能再次 POST
```

由于：

```text
BlaBlaTimeoutError
BlaBlaNetworkError
```

也属于 BlaBlaError，这意味着：

```text
第一次写请求可能已送达
但响应/网络中断
重新查询暂时仍看不到 completed
下一轮再次提交
```

这与“写请求不做盲重试”的安全合同不完全一致。

## 16.2 应修成

明确区分：

```text
业务明确失败
请求确定未发送
结果不确定
```

对 timeout / connection interruption after send：

```text
先 recheck
已完成 → SUCCESS
仍未确认 → UNKNOWN_AFTER_ACTION
停止再次 POST
```

除非后续拿到官方明确的幂等保证，否则不要自动重发。

## 16.3 默认关闭

当前配置：

```text
enable_daily_actions = false
```

所以这个债务暂时不会默认影响用户，但应在正式推荐开启前修。

## 16.4 完整 Daily Assistant 仍未实现

未来目标：

```text
签到
点赞
浏览
```

当前只有签到。

建议未来命令：

```text
/妮姬 日常 状态
/妮姬 日常 执行
/妮姬 日常 自动 开|关
```

---

# 17. Announcement / Schedule

状态：`PARTIAL + CONTRACT DEBT`

当前已有：

```text
AnnouncementRecord
body_hash
content_version
deadline parser
deadline_version
disk cache
delivery_log
format announcements
format schedule
hourly sync
```

命令：

```text
/妮姬 公告
/妮姬 日程
```

## 17.1 当前数据源

当前 fetch：

```text
GET https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetAnnouncements
```

仍未确认它就是最终目标正式 NIKKE CMS。

所以产品表述应继续：

```text
BlaBlaLink announcement MVP/fallback source
```

不能写：

```text
正式 InformationFeeds CMS 已完成
```

## 17.2 content_id 冲突债

当前：

```python
content_id = str(it.get("content_id") or it.get("id"))
```

如果两者都缺：

```text
content_id == "None"
```

多个无 ID 公告会发生 key collision。

应：

```text
缺稳定 ID → 丢弃并记录 diagnostic
```

或仅在有严格可复现 fallback key 合同时生成 key。

不能接受 `"None"`。

## 17.3 deadline_version 持久化债

正文变更时当前代码：

```text
record.content_version = existing.content_version + 1
```

重新解析 deadline 后：

```text
dl.deadline_version = existing.deadline_version + 1
```

但是没有同步：

```text
record.deadline_version
```

之后 `save_cache()` 保存的是：

```text
record.deadline_version
```

因此 reload 后 deadline version 可能回退。

另外：

```text
任何 body 变更
```

当前都会让解析出的 deadline 加 1，即使 deadline 本身没变。

更稳的合同是分别比较：

```text
content hash
deadline identity/end_at hash
```

正文变化：

```text
content_version +1
```

deadline 实际变化：

```text
deadline_version +1
```

## 17.4 Push 仍未接线

目前 delivery_log / compute key 有基础，但没有完整：

```text
订阅目标模型
自动发送 scheduler
deadline reminders
changed announcement reminders
first subscription no-backfill
per-target PushRecord
```

因此：

```text
公告查询 ≠ 公告推送完成
```

---

# 18. Guide

状态：`SKELETON`

代码路由支持：

```text
练度
红球
珍藏品
竞技场充能
```

目标路径：

```text
assets/guides/<category>/
```

但当前 `assets/` 实际只有：

```text
README.md
campaign_stages.json
cubes.json
equipment.json
favorite_items.json
sources.json
```

**没有 guides 目录。**

所以当前功能实际是：

```text
命令骨架 + 缺图提示
```

不是已经有攻略内容。

后续若加入攻略：

```text
必须记录来源、授权、更新时间、游戏版本
```

---

# 19. Voice / Poke

状态：`SPIKE`

当前 `/妮姬 戳一戳`：

```text
角色 alias
↓
VoiceResolver
↓
随机文字
↓
plain_result
```

VoiceResolver 当前自带：

```text
Alice
Red Hood
Anis
Rapi
Scarlet
Dorothy
```

以及：

```text
zh-cn
en
```

当前 adapter matrix：

```text
aiocqhttp
onebot_v11
```

但：

```text
没有真实 poke notice listener
没有音频 resolver
没有 OGG 下载
没有 ffmpeg
没有 Record 发送
没有用户 voice preference
```

所以不能把当前功能称为：

```text
角色语音
```

更准确是：

```text
互动文字 POC
```

---

# 20. AssetManager

状态：`PARTIAL`

当前资源链已经相对成熟。

## 20.1 本地与远端

支持：

```text
data/nikke/cache
项目 assets
sources.json
Nikke-DB
BlaBlaLink static asset
fallback
```

限制：

```text
MAX_BYTES = 12 MiB
MAX_PIXELS = 20,000,000
remote failure cooldown
per-request timeout
```

## 20.2 Character asset budget

单角色素材并发 ThreadPoolExecutor：

```text
max_workers = 4
```

resolve budget 默认：

```text
6 秒
```

超时：

```text
立即使用 fallback
```

保证 Renderer 不被慢资源阻塞。

## 20.3 当前线程债

`concurrent.futures.wait(timeout=6)` 后：

```text
not_done → fallback
```

但运行中的 thread 本身并不会被强制终止。

close：

```text
shutdown(wait=False, cancel_futures=True)
```

只可靠取消尚未开始的 future。

所以实际合同应该写：

```text
用户出卡 6 秒预算可保证
后台线程立即终止不可保证
```

而不是“所有资源任务都能被即时取消”。

---

# 21. Favorite Item / Cube / Equipment

状态：`PARTIAL`

当前：

```text
equipment.json
cubes.json
favorite_items.json
```

已接 AssetManager。

当前 cubes mapping：

```text
8 项
```

favorite_items：

```text
4 项
```

因此这不是完整全集。

当前正确策略：

```text
已登记 → 尝试加载
未知 → fallback
```

禁止根据 TID 猜图片或语义。

后续如果做完整 Collection：

```text
需要 verified registry
```

字段可以包括：

```text
tid
display_name
category
rarity
character_specific
resource
source
verified_at
```

---

# 22. Spine

状态：`SPIKE`

已有：

```text
NikkeDbProvider
l2d index
spine version
bundle URL
cache key
negative cache
lock
SpineTaskQueue
queue size
worker
shutdown
SPINE_VERSION_UNKNOWN
```

但是核心：

```python
SpinePreRenderer.render_full_body(...)
```

当前最终仍：

```python
return None
```

即：

```text
真实 Spine renderer 未接入
```

生产角色卡：

```text
默认 allow_spine_enqueue=False
```

因此正式用户路径靠：

```text
静态 Full Body
本地 cache
fallback
```

## 22.1 真 Spike 验收

需要真实完成：

```text
runtime 选型
license
major.minor strict match
4.1 fixture
其它版本 fixture
single/multi texture atlas
Linux headless
RGBA
animation pose
bounds/crop
peak RSS
timing
failure behavior
worker 1/2
```

未完成前，不应把 Spine 作为业务 PR 的依赖。

---

# 23. Evidence / Fixture 系统

状态：`PARTIAL`

仓库已经有真实 capture scripts，这是好的基础。

当前 fixture：

```text
character_details_sanitized.json
profile_basic_full_keys.json
outpost_full_keys.json

union_raid_overview.json
union_raid_boss_list.json
union_raid_ranking.json
union_raid_my_data.json
```

## 23.1 Profile fixture

当前 sanitize：

```text
保留 key/container
所有标量变成同类型安全值
```

适合：

```text
key contract
shape regression
```

不适合：

```text
数值语义回归
```

## 23.2 Raid fixture

同样是“完全归零/同字符串”脱敏。

Phase 2 前必须升级。

## 23.3 建议双层 fixture

以后可以分：

### shape fixture

```text
完全脱敏
只验证字段结构
```

### semantic fixture

```text
人工构造但来自真实 shape
relationship-preserving
安全伪值
用于：
聚合
排序
边界
状态机
```

这比把真实敏感值直接留在 repo 更安全，也比全部归零更有测试价值。

---

# 24. README / 文档债

状态：`DEBT`

README 当前是 PR #4 前后混合状态。

需要同步：

## 功能状态

增加：

```text
Campaign
Union Raid Overview
Announcement
Schedule
Guide skeleton
CDK batch/available/history
```

## Daily 描述

不能简单写：

```text
“签到尚未实现”
```

应写：

```text
签到写链已实现但默认关闭；
正式启用前仍需处理结果不确定情况下的重复提交策略。
```

## 测试

改为：

```text
pytest
Python 3.10–3.12 CI
180 tests current baseline
```

并补：

```text
Node extension test
```

## UI

更新：

```text
ProfileRenderer
UnionRaidRenderer
CampaignHistoryRenderer
CharacterCardRenderer
```

## 文档结构

如果决定建立 repo docs，建议：

```text
docs/
  DEVELOPMENT.md
  contracts/
  evidence/
```

否则本主文档就应作为单一开发文档，不再在源码 docstring 引用不存在的 contracts 文件。

---

# 24A. 全量“已计划但尚未完成”功能清单

> 本节专门解决“只写最近几个 PR，遗漏长期计划”的问题。  
> 这里记录的是此前已经明确讨论、设计或预留过，但截至当前 `main@deeef627` 尚未完整落地的功能。  
> 以后即使某项暂缓，也不能从主计划中删除；只能从 `TODO/PARTIAL/BLOCKED/DEFERRED` 变成 `DONE`，或明确标为 `CANCELLED` 并写原因。

---

## 24A.1 角色练度 / 单角色卡后续

当前单角色卡主链已经完成，但以下目标仍未完成。

### A-CHAR-01：HP / ATK / DEF 计算属性

状态：`TODO`

UI2 原设计把：

```text
HP
ATK
DEF
```

作为核心卡片数据的一部分，目前并没有完整生产实现。

目标：

```text
角色基础静态数据
+ 等级
+ 突破/核心
+ 装备
+ 其它已确认成长参数
↓
按已验证公式计算
↓
HP / ATK / DEF
```

约束：

```text
只能使用已验证静态资源和公式
不得根据战力反推
不得用经验公式猜
```

此前计划参考 ExiaInvasion 中可验证的静态资源/算法，但正式接入前必须：

- [ ] 固定输入字段合同。
- [ ] 固定等级/突破/核心/装备影响范围。
- [ ] 建独立 calculator。
- [ ] 对照真实账号样本。
- [ ] 容差测试。
- [ ] 公式版本化。
- [ ] 公式不确定时 UI 显示 `—`，不能显示猜测值。

### A-CHAR-02：OL 九类词条最终确认

状态：`PARTIAL`

当前已支持已知词条和 unknown fallback，但长期目标仍是：

```text
官方 9 类 OL 词条
全部用真实 function_type / function_value_type 验证
```

待确认类型包括历史设计里曾出现的：

```text
命中率
蓄力伤害
暴击率
防御力
```

验收：

- [ ] 每类至少一个真实 `state_effects` 样本。
- [ ] 删除无效 alias。
- [ ] 单位合同固定。
- [ ] unknown 仍必须可显示。
- [ ] 不因新词条出现而整卡失败。

### A-CHAR-03：角色资源 / Costume / Skin 完整链

状态：`PARTIAL`

当前有：

```text
静态 Full Body
resource_id
costume mapping
本地 override
```

但完整目标仍包括：

```text
角色默认立绘
皮肤/时装立绘
Favorite Item 形态
必要时不同 skin 的 Spine
```

待做：

- [ ] verified costume/skin registry。
- [ ] 角色详情里的 costume_id 与资源链一致。
- [ ] cache key 带 costume/skin。
- [ ] 资源不存在时回默认皮肤。
- [ ] 不猜 costume → resource 映射。

### A-CHAR-04：Favorite Item / Collectible 完整语义

状态：`PARTIAL`

当前只覆盖少量静态映射。

最终目标：

```text
TID
名称
类型
稀有度
等级/阶段
角色专属关系
资源
```

待做：

- [ ] 完整 verified registry。
- [ ] 角色专属关系。
- [ ] Favorite Item 与普通收藏品区分。
- [ ] 未知 TID 明确显示未识别。
- [ ] 后续可独立查询。

### A-CHAR-05：Harmony Cube 完整语义

状态：`PARTIAL`

当前主要解决图标定位，完整目标：

```text
TID
官方名称
等级
类型
效果
资源
```

待做：

- [ ] 完整 Cube registry。
- [ ] 当前装备魔方详情。
- [ ] 未知 TID fallback。
- [ ] 可供角色卡和独立查询复用。

### A-CHAR-06：装备静态资源与名称补全

状态：`PARTIAL`

当前已有装备资源表，但长期目标仍包括：

```text
完整装备 ID
部位
企业
品级
名称
图标
OL/改造状态
```

仅使用可确认字段。

### A-CHAR-07：角色总览 UI 后续统一

状态：`DEFERRED`

无角色名的：

```text
/妮姬 查询 练度
```

当前仍沿用 legacy 1200px 列表卡。

长期目标可以升级为：

```text
暗色横向 roster dashboard
角色头像/立绘缩略图
Lv
combat
技能
突破/核心
分页或分块
```

但不得为了视觉统一牺牲：

```text
快速响应
账号请求次数
QQ 可读性
```

这不是当前 blocker，保留在长期 UI 计划。

---

## 24A.2 Profile Dashboard 全部未完成计划

### A-PROFILE-01：Recycle Room Research 结构化

状态：`TODO`

目标 DTO：

```text
tid
lv
exp
display_name | None
category | None
```

当前只显示：

```text
X 项 · 等级合计 Y
```

必须改为可结构化展示。

### A-PROFILE-02：Collection / Memorial 结构化

状态：`TODO`

当前只有数量摘要。

目标：

```text
收藏项目
数量/等级
分类
可确认名称
```

未验证 TID 不猜。

### A-PROFILE-03：独立信息区

状态：`TODO`

最终 Profile 信息架构：

```text
BASIC
CAMPAIGN
OUTPOST
ROSTER
COLLECTION
RESEARCH
MORE
```

Campaign 不再长期挤在 Basic。

### A-PROFILE-04：My Nikkes 预览

状态：`DEFERRED`

此前参考 ShiftyPad/Profile 风格时计划过：

```text
Profile 卡中展示若干代表性角色
```

可选：

```text
Top N by combat
或
用户当前 roster 简略预览
```

如果实现：

- [ ] 不能导致重复 roster 请求。
- [ ] 只复用已经取得的数据。
- [ ] 不在 `/妮姬 我的` 里拉每个角色 Details。
- [ ] 支持 roster 获取失败时整段隐藏。

### A-PROFILE-05：Profile 视觉继续对齐参考风格

状态：`DEFERRED`

保持用户明确偏好：

```text
暗色调
蓝青信息层级
横向/仪表盘感
```

但不做主观评分。

---

## 24A.3 Union Raid 全部后续功能

Union Raid 是目前剩余业务量最大的功能域。

### A-RAID-01：可靠 level/difficulty/round selector

状态：`BLOCKED`

需要确认：

```text
level_info[] 是否同时返回多个 difficulty
是否同时返回多个 level
是否有当前 round/status/step 字段
数组顺序是否有语义
```

在确认前禁止：

```text
默认第一项就是当前赛季进度
```

### A-RAID-02：Raid Progress 独立入口

状态：`TODO`

目标：

```text
/妮姬 联盟突袭 进度
```

可以复用 Overview 数据，但需要明确：

```text
difficulty
level
Boss scope
总进度 scope
更新时间
```

### A-RAID-03：GetUnionRaidData 正式 client/service 接入

状态：`TODO`

虽然已有 fixture，但当前正式命令还未消费该接口。

### A-RAID-04：RaidAttackData

状态：`TODO`

字段只用已观察值：

```text
boss_id
day
difficulty
level
step
total_damage
is_final_hit
squad
participant identity
```

### A-RAID-05：RaidSquadMember / 历史出刀队伍

状态：`TODO`

每刀显示：

```text
5 个成员
tid
lv
combat
costume_id
slot
```

可追加静态角色名/头像，但不能修改快照数据。

### A-RAID-06：参与者聚合

状态：`TODO`

在同一个 GetUnionRaidData 响应内：

```text
group by participate_data[].openid
```

计算：

```text
total_damage
attack_count
boss distribution
每刀记录
```

真实 openid 不进入最终 DTO/UI。

### A-RAID-07：联盟伤害排名

状态：`TODO`

命令：

```text
/妮姬 联盟突袭 排名
```

排名：

```text
total_damage DESC
```

同伤害：

```text
同 rank
```

禁止用 nickname/openid 制造伪官方 tiebreak。

### A-RAID-08：赛季范围确认

状态：`BLOCKED`

必须验证：

```text
GetUnionRaidData 是否覆盖完整赛季
是否分页
是否 cursor
是否按 day/level 过滤
是否只返回当前轮
是否只返回部分攻击
```

在验证前 UI 写：

```text
当前数据范围
```

不能写：

```text
赛季总排名
```

### A-RAID-09：允许攻击数 / 已用攻击 / 剩余攻击

状态：`BLOCKED`

需要真实数据确认：

```text
每日允许次数
赛季攻击次数
剩余攻击次数
是否可从条目 day/step 安全计算
```

若没有官方明确字段，不凭经验写死。

### A-RAID-10：我的突袭记录

状态：`TODO/BLOCKED`

命令：

```text
/妮姬 联盟突袭 我的
```

显示：

```text
当前响应范围总伤害
攻击次数
每刀 Boss
每刀伤害
队伍快照
```

只有稳定 identity 可确认时开放。

### A-RAID-11：成员详情

状态：`BLOCKED`

目标：

```text
/妮姬 联盟突袭 成员 <昵称>
```

但需要确认：

```text
GetGuildMembers.member_id
↔
GetUnionRaidData.openid
```

禁止：

```text
nickname join
重名强合并
```

如果身份映射一直无法验证，可以改成：

```text
从当前排名列表选择内部 participant key
```

而不是按昵称做数据库 join。

### A-RAID-12：零攻击成员 / 完整联盟成员列表

状态：`BLOCKED`

只有 Guild Members 与 Raid participant 可以安全关联后，才能显示：

```text
参与成员
未出刀成员
```

禁止用 nickname 猜。

### A-RAID-13：攻击时间顺序 / 最近一刀

状态：`BLOCKED`

需可靠：

```text
timestamp
sequence
或官方明确 order 字段
```

没有时不能把数组顺序称“最近”。

### A-RAID-14：Boss 视觉资源

状态：`TODO`

目标：

```text
Boss portrait/icon
Boss 背景
属性/弱点图标
```

缺素材时：

```text
几何/文字 fallback
```

### A-RAID-15：Raid Ranking / My / Member 独立 Renderer

状态：`TODO`

需要分别适配：

```text
1600px 暗色战术 HUD
红/橙 + 青色强调
```

保持：

```text
不做成员评分
不做摆烂标签
```

### A-RAID-16：Raid 历史赛季

状态：`DEFERRED/BLOCKED`

如果后续发现官方存在历史赛季 API，可计划：

```text
/妮姬 联盟突袭 历史
```

但当前没有证据，不先造接口。

---

## 24A.4 Campaign / Stage 后续

### A-CAMP-01：更多章节 Stage Map

状态：`TODO`

当前只覆盖验证过的：

```text
NORMAL Chapter 46
HARD Chapter 35
```

长期目标：

```text
逐章抓取
逐章验证
逐章加入 assets/campaign_stages.json
```

禁止公式生成 stage_id。

### A-CAMP-02：更多真实成功 / 不可用 / 限流 fixture

状态：`TODO`

每新增章节同时增加：

```text
success
empty/unavailable
malformed
rate limit
```

### A-CAMP-03：Campaign History 更丰富 UI

状态：`DEFERRED`

可以加入：

```text
5 人头像/立绘
单人战力
总战力
等级
slot
```

但快照数据只能来自历史响应。

### A-CAMP-04：普通关卡详情查询

状态：`DEFERRED`

早期曾有 `stage` 类占位方向。

如果以后重新启用：

```text
/妮姬 关卡 <关卡>
```

应与“历史通关阵容”分开：

```text
关卡静态信息
≠
历史通关快照
```

只有有可靠静态数据源时实现。

---

## 24A.5 CDK 全部后续

### A-CDK-01：批量持久幂等

状态：`TODO`

当前 batch 没有完全复用：

```text
action_runs
```

目标是每个 CDK 都使用与单条一致的：

```text
qq_id + game_uid + SHA256(code)
```

执行语义。

### A-CDK-02：批量参数生产校准

状态：`TODO`

当前：

```text
max_items = 10
delay = 0.5s
```

需要通过真实生产观察决定：

```text
最大批量
间隔
rate limit backoff
```

不要把旧计划的 20 / 2s 当官方合同。

### A-CDK-03：真实账号 History Shape 验证

状态：`TODO`

继续验证：

```text
pagination
history list
字段稳定性
时间字段
状态字段
```

### A-CDK-04：可用 CDK 更完整展示

状态：`DEFERRED`

可追加已确认：

```text
有效期
奖励描述
状态
```

只有 API 真有可靠字段才展示。

### A-CDK-05：批量结果卡

状态：`DEFERRED`

如果文本过长，可以做：

```text
成功
已兑换
业务失败
RESULT_UNKNOWN
停止原因
```

的结构化图片卡。

不保存明文历史。

---

## 24A.6 Daily / 社区日常全部计划

### A-DAILY-01：统一 DailyTaskResult 状态机

状态：`TODO`

至少：

```text
SUCCESS
ALREADY_DONE
FAILED
RATE_LIMITED
COOKIE_EXPIRED
UNKNOWN_AFTER_ACTION
UNAVAILABLE
```

### A-DAILY-02：签到模糊写结果安全化

状态：`TODO`

timeout/network interruption：

```text
写后 recheck
若未确认 → UNKNOWN_AFTER_ACTION
停止再次 POST
```

### A-DAILY-03：点赞任务

状态：`BLOCKED`

完整社区日常原计划包括：

```text
点赞
```

需要真实接口/fixture 后实现。

### A-DAILY-04：浏览任务

状态：`BLOCKED`

同上，需要真实 API，不造接口。

### A-DAILY-05：只补缺少次数

状态：`TODO`

未来 DailyTaskService 应：

```text
先读取状态
只执行缺口
不重复已完成动作
```

### A-DAILY-06：统一命令

状态：`TODO`

目标命令：

```text
/妮姬 日常
/妮姬 日常 状态
/妮姬 日常 执行
/妮姬 日常 自动 开
/妮姬 日常 自动 关
```

当前 `/妮姬 签到` 可继续保留兼容。

### A-DAILY-07：每账号自动开关

状态：`TODO`

不是只有全局：

```text
enable_daily_actions
```

还应支持用户自己的：

```text
auto_daily_enabled
```

### A-DAILY-08：失败通知与汇总

状态：`PARTIAL`

未来每日汇总需要区分：

```text
完成
已完成
未知
CookieExpired
需重新绑定
限流
```

不能只写泛化“失败”。

---

## 24A.7 Announcement / Event Calendar / Push 全部计划

### A-ANN-01：正式 CMS Source Adapter

状态：`BLOCKED`

目标：

```text
Level Infinite / InformationFeeds
```

当前 GetAnnouncements 只作为 MVP/fallback。

### A-ANN-02：Announcement source abstraction

状态：`TODO`

建议：

```text
AnnouncementSource
├─ BlaBlaLinkFallbackSource
└─ InformationFeedsSource
```

### A-ANN-03：稳定 content ID

状态：`TODO`

无：

```text
content_id
id
```

不能变成 `"None"`。

### A-ANN-04：content_version 与 deadline_version 分离

状态：`TODO`

正文变化：

```text
content_version +1
```

deadline 真变化：

```text
deadline_version +1
```

### A-ANN-05：PushRecord

状态：`TODO`

目标：

```text
target
content/deadline
version
push_type
pushed_at
```

不把：

```text
pushed=true
```

塞到全局 AnnouncementRecord。

### A-ANN-06：订阅目标

状态：`TODO`

需要：

```text
群
私聊
用户偏好
管理员默认群
```

### A-ANN-07：首次订阅不补推过期内容

状态：`TODO`

### A-ANN-08：recent-window 重扫

状态：`TODO`

建议默认：

```text
最近 14 天
```

并持续关注：

```text
进行中维护
进行中活动
Raid
未来 deadline
最近正文变化
```

### A-ANN-09：活动截止提醒

状态：`TODO`

支持：

```text
24h
6h
1h
```

等 configurable reminder。

### A-ANN-10：维护延期 / 时间修改再次提醒

状态：`TODO`

deadline version 改变后允许新提醒。

### A-ANN-11：失败发送不写 PushRecord

状态：`TODO`

### A-ANN-12：公告分类与筛选

状态：`DEFERRED`

可支持：

```text
维护
活动
更新
招募
联盟突袭
开发者笔记
```

前提是分类来源稳定或有可解释规则。

### A-ANN-13：Event Calendar 图片卡

状态：`DEFERRED`

当前日程是文本。

长期目标可以做：

```text
当前活动
结束时间
剩余时间
维护窗口
Raid
```

的暗色日历卡。

---

## 24A.8 Resource Registry 全部计划

### A-ASSET-01：完整 Favorite Item registry

见角色部分。

### A-ASSET-02：完整 Cube registry

见角色部分。

### A-ASSET-03：完整 Equipment registry

见角色部分。

### A-ASSET-04：Costume registry

状态：`TODO`

### A-ASSET-05：Boss resource registry

状态：`TODO`

### A-ASSET-06：资源来源 metadata

状态：`TODO`

每个 registry 最终应能记录：

```text
source
verified_at
resource/version
license/rights note
```

### A-ASSET-07：并发资源全局限流

状态：`DEFERRED`

单卡已有约 4 worker，但多个群同时刷卡仍应有：

```text
global render/resource concurrency limit
```

### A-ASSET-08：超时线程长期运行治理

状态：`DEBT`

用户出卡可 6 秒 fallback，但后台 thread 可能继续运行。

未来需要：

```text
更细粒度 HTTP timeout
有界队列
任务 dedup
冷却
避免线程池长期被超时任务占满
```

---

## 24A.9 Spine 全部计划

### A-SPINE-01：真实 runtime 选型

状态：`SPIKE`

### A-SPINE-02：runtime license 核对

状态：`SPIKE`

必须与：

```text
游戏素材使用权
```

分开处理。

### A-SPINE-03：版本严格匹配

状态：`PARTIAL`

未知：

```text
SPINE_VERSION_UNKNOWN
```

禁止生产试错 fallback。

### A-SPINE-04：代表性 fixture

状态：`TODO`

至少：

```text
single texture
multi texture
Spine 4.1
其它 major.minor
full-body bounds
skin/costume
```

### A-SPINE-05：Linux headless render

状态：`TODO`

### A-SPINE-06：透明 RGBA PNG

状态：`TODO`

### A-SPINE-07：动画 pose / Lobby pose

状态：`TODO`

### A-SPINE-08：bounds / crop

状态：`TODO`

### A-SPINE-09：性能与内存测量

状态：`TODO`

记录：

```text
首次
预热
RSS
输入大小
输出大小
worker 1/2
```

### A-SPINE-10：生产后台队列

状态：`PARTIAL`

已有骨架，真正 renderer 完成后才能启用。

### A-SPINE-11：首张卡不阻塞

状态：`设计合同已定，生产 Spine 未完成`

永远保持：

```text
local override
→ prerender cache
→ static remote
→ enqueue Spine
→ fallback
```

第一张卡不等 Spine。

---

## 24A.10 Voice / Poke 全部计划

### A-VOICE-01：QQ poke event listener

状态：`TODO`

当前只是手工：

```text
/妮姬 戳一戳
```

### A-VOICE-02：VoicePreference 持久化

状态：`TODO`

字段可包括：

```text
enabled
character
skin
locale
```

### A-VOICE-03：用户命令

状态：`TODO`

```text
/妮姬 语音 开
/妮姬 语音 关
/妮姬 语音 角色 <角色名>
/妮姬 语音 语言 <locale>
```

### A-VOICE-04：VoiceAssetResolver

状态：`TODO`

只使用已验证资源索引。

### A-VOICE-05：Lobby_Touch 等音频候选

状态：`TODO`

### A-VOICE-06：OGG/audio cache

状态：`TODO`

### A-VOICE-07：negative cache

状态：`TODO`

### A-VOICE-08：ffmpeg probe / transcode

状态：`TODO`

### A-VOICE-09：adapter-specific Record sender

状态：`TODO`

### A-VOICE-10：adapter support matrix 真实测试

状态：`TODO`

未验证 adapter：

```text
文本 fallback
```

### A-VOICE-11：语言不能从角色 ID 猜

状态：`合同`

语音 locale 必须来自：

```text
用户设置
或明确默认
```

---

## 24A.11 Guide / 攻略全部计划

### A-GUIDE-01：正式攻略内容

状态：`TODO`

当前 repo 没有 `assets/guides/` 内容。

### A-GUIDE-02：已计划分类

至少包括：

```text
练度
红球
珍藏品
竞技场充能
```

### A-GUIDE-03：registry.json

状态：`TODO`

记录：

```text
id
category
title
files
source
credit
updated_at
game_version
```

### A-GUIDE-04：来源/授权

状态：`TODO`

不能复制未明确授权攻略正文。

### A-GUIDE-05：多图排序

状态：`TODO`

### A-GUIDE-06：分页/索引

状态：`TODO`

### A-GUIDE-07：版本过期提示

状态：`TODO`

攻略内容需要：

```text
game_version
updated_at
```

避免过期信息无提示。

---

## 24A.12 早期已计划、后来撤下占位命令的功能

这些功能过去进入过规划/占位命令范围，后来因为没有可靠数据合同而从公开命令面移除。  
它们仍属于“计划过但未完成”的功能，应保留为 `DEFERRED/BLOCKED`，而不是从主计划消失。

### A-EXT-01：独立技能查询

状态：`DEFERRED`

历史方向：

```text
/妮姬 查询 技能 <角色名>
```

当前角色卡已经显示技能等级，但：

```text
技能描述
技能倍率
技能效果
技能资源
```

仍没有独立可靠数据产品。

若未来实现，应使用合法静态数据源，不从攻略站复制正文。

### A-EXT-02：面谈 / Advise

状态：`BLOCKED/DEFERRED`

历史占位：

```text
advise
```

可能方向：

```text
角色面谈选项
好感答案
```

只有获得可合法使用且版本稳定的数据源后再实现。

### A-EXT-03：关卡详情 Stage

状态：`DEFERRED`

与 Campaign History 区分。

### A-EXT-04：企业塔 / Tower

状态：`BLOCKED/DEFERRED`

未来可能提供：

```text
企业塔进度
塔层详情
历史阵容/推荐数据（若有官方数据）
```

不能把 Profile 里的 `progress_tribe_tower` 扩写成未验证详情。

### A-EXT-05：魔方独立查询

状态：`DEFERRED`

```text
/妮姬 查询 魔方 <名称>
```

需要完整 Cube registry 后再开放。

### A-EXT-06：收藏品 / 珍藏品独立查询

状态：`DEFERRED`

需要 Favorite Item / Collection registry。

### A-EXT-07：角色图片 / 素材查询

状态：`DEFERRED`

历史 placeholder：

```text
image
```

可做：

```text
角色立绘
头像
皮肤
```

但必须遵循：

```text
资源权利
来源
缓存
大小
```

### A-EXT-08：JSON 导出

状态：`DEFERRED`

历史 placeholder：

```text
export
```

未来如果实现：

```text
/妮姬 导出 JSON
```

只能导出用户自己的非敏感账号数据。

必须排除：

```text
Cookie
x_common_params
openid
qq_id
game_uid
内部 run key
```

### A-EXT-09：图片导出 / 卡片导出

状态：`DEFERRED`

当前本来就通过 QQ 发送 PNG。

若未来提供独立下载/export：

```text
临时文件
短期 URL
权限
过期清理
```

都需要单独安全设计。

---

## 24A.13 资料 / NikkePedia 后续

当前：

```text
/妮姬 查询 资料 <角色名>
```

已经存在基础资料。

但长期资料库目标还可以包括：

```text
企业
武器
属性
爆裂
定位
基础技能静态信息
Favorite Item
Costume
资源图
```

状态：`PARTIAL/DEFERRED`

不得加入：

```text
主观强度
抄攻略正文
未经验证的阵容推荐
```

---

## 24A.14 UI / 视觉系统全部后续

### A-UI-01：统一暗色设计语言

状态：`PARTIAL`

用户明确要求整体偏暗。

不同模块：

```text
Character：角色主导
Profile：蓝青
Raid：红/橙 + 青
Campaign：战役/档案感
Announcement：日历/信息流
```

### A-UI-02：角色卡主题权重

长期设计约束：

```text
立绘 75%
企业 20%
属性 5%
```

并加入：

```text
低透明度对应企业图标水印
```

当前自动主题已存在，但以后改视觉不能破坏这一方向。

### A-UI-03：Abnormal 企业风格

状态：`PARTIAL`

保持：

```text
深紫黑
略不对称
冷紫描边
```

但不为协作角色逐个硬编码。

### A-UI-04：Renderer 统一组件

状态：`DEFERRED`

未来可以抽：

```text
字体
Panel
Badge
进度条
Footer
资源加载
```

但不做一次性大重构。

### A-UI-05：长文本 / 小屏 QQ 适配

状态：`持续`

所有新 Renderer 都需：

```text
固定最大宽度
动态高度
长昵称
长角色名
未知字段
缺图
```

测试。

---

## 24A.15 数据抓包 / Evidence / Fixture 全部计划

### A-EVID-01：修 Raid capture script

状态：`TODO/P0`

### A-EVID-02：relationship-preserving sanitizer

状态：`TODO/P0`

### A-EVID-03：semantic fixtures

状态：`TODO`

区分：

```text
shape fixture
semantic fixture
```

### A-EVID-04：Campaign 更多 fixture

状态：`TODO`

### A-EVID-05：CDK 真实响应 fixture

状态：`TODO`

尤其：

```text
available
history
business error
rate limit
```

### A-EVID-06：Announcement 正式 CMS fixture

状态：`BLOCKED`

### A-EVID-07：Daily write/read fixture

状态：`TODO/BLOCKED`

### A-EVID-08：Spine representative fixtures

状态：`TODO`

### A-EVID-09：证据分级

状态：`持续`

```text
CONFIRMED
OBSERVED
INFERRED
TODO
```

### A-EVID-10：正式 docs/evidence 目录

状态：`DEFERRED`

当前 repo 没有该目录。

如果建立：

```text
docs/evidence/
docs/contracts/
```

必须真的提交，不再只在文档里假设存在。

---

## 24A.16 CI / Engineering 全部计划

### A-CI-01：Node extension tests 进入 Actions

状态：`TODO`

```text
node --test tests/extension.test.cjs
```

### A-CI-02：branch protection / required checks

状态：`TODO`

### A-CI-03：删除重复 master trigger

状态：`DEFERRED`

确认旧 branch 不再需要后处理。

### A-CI-04：Python 3.13 compatibility

状态：`DEFERRED/BLOCKED BY ASTRBOT`

当前只声明：

```text
3.10–3.12 verified
```

### A-CI-05：AstrBot register API 迁移

状态：`DEBT`

解决：

```text
register_star deprecated
```

### A-CI-06：统一 background task registry

状态：`TODO`

追踪：

```text
daily
summary
announcement sync
其它 create_task
```

shutdown：

```text
cancel + await
```

### A-CI-07：main.py 功能域拆分

状态：`DEFERRED`

未来按：

```text
account
profile
raid
campaign
cdk
daily
announcement
guide
voice
```

拆 service/handler。

不做一次性重构。

### A-CI-08：Renderer/Asset 全局并发治理

状态：`DEFERRED`

避免群刷资源时：

```text
线程池
带宽
内存
```

同时被打满。

### A-CI-09：README / metadata / version 自动一致性

状态：`TODO`

避免：

```text
metadata.yaml
_version.py
manifest.json
README
help
```

版本/功能描述漂移。

---

# 24B. 全量未完成模块总表

| 功能域 | 当前状态 | 仍需完成的核心内容 |
|---|---|---|
| 单角色卡 | `PARTIAL（扩展）` | HP/ATK/DEF、九类 OL 最终验证、Costume/Favorite/Cube 完整语义 |
| 练度总览 | `DEFERRED UI` | legacy roster card 后续升级 |
| Profile | `PARTIAL` | Research、Collection、独立分区、可选 My Nikkes preview |
| Union Raid Overview | `MVP` | round selector、HP clamp、Boss 资源 |
| Union Raid Ranking | `TODO` | GetUnionRaidData、聚合、排名、范围确认 |
| Union Raid My | `TODO/BLOCKED` | identity、每刀、队伍快照 |
| Union Raid Member | `BLOCKED` | member_id ↔ openid |
| Union Raid History | `DEFERRED` | 历史赛季接口 |
| Campaign | `MVP` | 更多章节、fixture、未知错误合同、视觉增强 |
| CDK Single | `DONE 主链` | 真实 history shape 扩展验证 |
| CDK Batch | `PARTIAL` | persistent idempotency、参数校准、结果卡 |
| Daily Sign-in | `PARTIAL` | UNKNOWN_AFTER_ACTION |
| Daily Like | `BLOCKED` | 真实 API |
| Daily Browse | `BLOCKED` | 真实 API |
| Daily Automation | `TODO` | per-user toggle、统一状态、完整汇总 |
| Announcement Query | `PARTIAL` | content ID、版本逻辑、正式 source |
| Event Calendar | `PARTIAL` | 正式 CMS、图片卡 |
| Announcement Push | `TODO` | PushRecord、订阅、提醒、重扫 |
| Asset Registry | `PARTIAL` | Equipment/Cube/Favorite/Costume/Boss 完整 registry |
| Spine | `SPIKE` | 真正 headless render + production queue |
| Voice/Poke | `SPIKE` | poke listener、偏好、真音频、转码、Record |
| Guide | `SKELETON` | 正式内容、registry、授权、分页 |
| Skill Query | `DEFERRED` | 静态技能详情 |
| Advise | `BLOCKED/DEFERRED` | 面谈数据源 |
| Stage Detail | `DEFERRED` | 静态关卡详情 |
| Tower | `BLOCKED/DEFERRED` | 企业塔详情 |
| Cube Query | `DEFERRED` | 完整 Cube registry |
| Collection Query | `DEFERRED` | 完整收藏 registry |
| Image Query | `DEFERRED` | 角色/皮肤素材分发 |
| JSON Export | `DEFERRED` | 安全脱敏导出 |
| CI | `PARTIAL` | Node test、required checks、版本一致性 |
| Lifecycle | `PARTIAL` | background task registry、资源并发治理 |
| Evidence | `PARTIAL` | semantic fixture、正式 contracts/evidence 目录 |

---

# 24C. 完整 Roadmap（不能再遗漏长期功能）

下面的 PR 编号只是建议拆分顺序；真正执行时可以合并或重排，但功能项不能从计划中消失。

## PR #5 — Contract & Evidence Hardening

- [ ] 修 Raid capture script。
- [ ] 删除 openid split。
- [ ] GetMyGuildInfo payload 对齐生产 client。
- [ ] relationship-preserving sanitizer。
- [ ] semantic Raid fixture。
- [ ] Raid HP clamp。
- [ ] Campaign unknown error rethrow。
- [ ] Node extension test 进 CI。
- [ ] README 与当前 main 同步。

## PR #6 — Profile Research / Collection

- [ ] RecycleResearchData。
- [ ] Collection DTO。
- [ ] 独立 Profile section。
- [ ] optional My Nikkes preview 评估。
- [ ] fixtures/tests。

## PR #7 — Union Raid Phase 2 Data

- [ ] 正式 GetUnionRaidData client/service。
- [ ] RaidAttackData。
- [ ] RaidSquadMember。
- [ ] participant grouping。
- [ ] ranking。
- [ ] scope semantics。
- [ ] tie ranking。
- [ ] privacy。

## PR #8 — Union Raid Product Views

- [ ] `/妮姬 联盟突袭 进度`。
- [ ] `/妮姬 联盟突袭 排名`。
- [ ] `/妮姬 联盟突袭 我的`。
- [ ] 成员详情（仅 identity 解锁后）。
- [ ] 历史队伍。
- [ ] Boss portrait/background。
- [ ] Ranking/My/Member Renderer。

## PR #9 — Character Calculated Stats & Registries

- [ ] HP calculator。
- [ ] ATK calculator。
- [ ] DEF calculator。
- [ ] 九类 OL 最终确认。
- [ ] Favorite registry。
- [ ] Cube registry。
- [ ] Equipment registry。
- [ ] Costume registry。

## PR #10 — Campaign Coverage

- [ ] 更多 NORMAL 章节。
- [ ] 更多 HARD 章节。
- [ ] success/error fixtures。
- [ ] stage map 人工确认。
- [ ] Campaign UI 素材增强。

## PR #11 — Announcement Correctness

- [ ] content ID validation。
- [ ] content/deadline version 分离。
- [ ] source adapter。
- [ ] 正式 CMS 调研/抓包。
- [ ] cache migration tests。

## PR #12 — Announcement Push / Event Calendar

- [ ] PushRecord。
- [ ] 订阅目标。
- [ ] recent-window scan。
- [ ] deadline reminders。
- [ ] maintenance延期。
- [ ] changed content repush。
- [ ] 日历卡。

## PR #13 — Daily Write Safety & Full Daily Assistant

- [ ] UNKNOWN_AFTER_ACTION。
- [ ] 签到不盲重试。
- [ ] DailyTaskResult。
- [ ] 每账号自动开关。
- [ ] 点赞（有证据后）。
- [ ] 浏览（有证据后）。
- [ ] 完整汇总。

## PR #14 — CDK Hardening

- [ ] batch persistent idempotency。
- [ ] batch 参数生产校准。
- [ ] history pagination 实测。
- [ ] 可选 batch result card。

## PR #15 — Spine Real Spike

- [ ] runtime。
- [ ] license。
- [ ] fixture。
- [ ] 4.1 + 其它版本。
- [ ] multi-texture。
- [ ] Linux headless。
- [ ] RGBA。
- [ ] pose。
- [ ] crop。
- [ ] benchmark。
- [ ] production readiness decision。

## PR #16 — Voice / Poke

- [ ] poke event listener。
- [ ] VoicePreference。
- [ ] 语音设置命令。
- [ ] VoiceAssetResolver。
- [ ] audio cache。
- [ ] negative cache。
- [ ] ffmpeg。
- [ ] adapter sender。
- [ ] fallback。

## PR #17 — Guide Content System

- [ ] guide registry。
- [ ] 正式内容。
- [ ] source/credit/license。
- [ ] game version。
- [ ] 多图。
- [ ] 排序。
- [ ] 分页。

## PR #18 — Deferred Query Modules

只有对应数据源验证后逐个开启：

- [ ] Skill details。
- [ ] Advise。
- [ ] Stage detail。
- [ ] Tower。
- [ ] Cube query。
- [ ] Collection query。
- [ ] Character image query。
- [ ] JSON export。
- [ ] 可选图片导出。

## PR #19 — Engineering / Maintenance

- [ ] background task registry。
- [ ] branch protection。
- [ ] 版本一致性自动检查。
- [ ] AstrBot deprecated API migration。
- [ ] Python 3.13 readiness。
- [ ] global renderer/resource concurrency。
- [ ] main.py 渐进拆分。
- [ ] 正式 docs/contracts/evidence（如果决定建）。

---

# 24D. 功能不可删除规则

以后更新主计划时：

```text
已经计划过但没实现
```

不得因为“当前不做”就从文档删除。

只允许：

```text
TODO
PARTIAL
MVP
SPIKE
BLOCKED
DEFERRED
DONE
CANCELLED（必须说明取消原因）
```

例如：

```text
Advise
Tower
Cube Query
Collection Query
Image Query
JSON Export
Raid Member
Raid History
Voice
Spine
```

即使不进入最近 2–3 个 PR，也必须继续保留在“全量计划”中。

# 24E. 夜间 Agent 自主执行方案

> 用途：用户离线/睡眠期间，让 Coding Agent 在 **不猜接口、不使用真实敏感凭据、不破坏 `main`** 的前提下，尽可能连续完成所有可以通过仓库、fixture 和测试验证的开发任务。  
> 目标不是“强行把所有功能做完”，而是让 Agent **持续推进所有不需要人工确认的工作**，遇到 BLOCKED 项时自动跳过并继续下一项。

---

## 24E.1 夜间执行总原则

Agent 必须遵守：

```text
1. 不直接修改 main。
2. 从最新 main 创建独立工作分支。
3. 禁止 force push。
4. 禁止自行 merge。
5. 禁止删除或弱化现有测试。
6. 禁止用 skip / xfail 规避失败。
7. 禁止使用真实 Cookie、OpenID、QQ、game_uid 等敏感凭据。
8. 禁止为了“完成计划”而猜测未知 API、字段或身份映射。
9. 遇到需要真实抓包、人工确认或产品决策的任务：
   - 标记 BLOCKED
   - 写明原因
   - 跳到下一个安全任务
10. 每个阶段必须：
   - 修改代码
   - 补测试
   - 跑测试
   - git diff --check
   - 独立 commit
11. 某个 Phase BLOCKED 时不能停止整个夜间执行。
12. 不做无关大重构。
13. 保持现有用户命令兼容。
14. 不把内部 ID 泄露到 UI。
15. 不加入角色评分、联盟成员评价等主观系统。
```

---

## 24E.2 夜间 Agent 启动流程

建议分支：

```text
feat/overnight-backlog
```

启动：

```bash
git fetch origin
git checkout main
git pull --ff-only origin main

git checkout -b feat/overnight-backlog
```

如果分支已存在：

```text
安全切换
确认基于最新 main
不要覆盖已有未提交工作
```

基线测试：

```bash
python -m compileall -q .
pytest -q
```

如果 Node 可用：

```bash
node --test tests/extension.test.cjs
```

必须记录：

```text
起始 main SHA
起始测试结果
起始 branch
```

---

## 24E.3 Phase 1 — Contract & Evidence Hardening

优先级：`P0`

### 24E.3.1 修复 Raid capture script

文件：

```text
scripts/capture_union_raid_fixtures.py
```

当前旧合同必须移除：

```python
openid.split("-")[-1]
```

以及旧：

```text
GetMyGuildInfo(nikke_area_id + intl_open_id)
```

改为与生产 client 一致：

```json
{
  "ignore_toast": true
}
```

后续：

```text
GetUnionRaidLevelInfo
GetUnionRaidData
```

使用：

```text
guild_id
nikke_area_id
完整 intl_open_id
```

禁止 split openid。

Agent 在夜间执行时：

```text
不能实际调用真实账号
```

只做：

```text
函数重构
payload test
静态 contract test
```

测试至少覆盖：

```text
GetMyGuildInfo payload
完整 openid
不存在 split("-")
Raid 请求 payload
```

---

### 24E.3.2 Relationship-preserving Raid sanitizer

当前：

```text
所有 str → "[已脱敏]"
所有 int → 0
```

只适合 schema test。

需要新增 semantic sanitizer。

目标：

```text
真实 openid A → user_01
真实 openid A → user_01
真实 openid B → user_02
```

nickname：

```text
member_01
member_02
```

伤害：

```text
替换为安全构造值
但保留大小关系、相等关系、聚合关系
```

squad：

```text
slot 保留 1..5
tid/lv/combat/costume_id 使用安全构造值
```

fixture 分两类：

```text
shape fixture
semantic fixture
```

semantic fixture 专门用于：

```text
grouping
ranking
tie
my records
squad
```

禁止提交任何真实身份值。

---

### 24E.3.3 Raid HP clamp

当前要求统一：

```python
safe_current = max(0, min(current_hp, max_hp))
```

用于：

```text
RaidBossData.current_hp
hp_percent
cleared_percent
total_current_hp
total_progress
```

新增测试：

```text
current_hp > max_hp
current_hp < 0
正常值
```

---

### 24E.3.4 Campaign unknown error propagation

检查：

```text
client.get_main_quest_clear_lineup()
```

只允许特殊处理：

```text
1300017
212000
CookieExpired
```

其它未知：

```text
BlaBlaError
```

必须继续：

```python
raise
```

不能转换成 generic dict。

测试：

```text
未知业务码 → raises BlaBlaError
CookieExpired → 原类型保留
```

---

### 24E.3.5 Phase 1 验证

执行：

```bash
python -m compileall -q .
pytest -q
git diff --check
```

如果 Node test 存在：

```bash
node --test tests/extension.test.cjs
```

通过后提交：

```text
fix: harden raid evidence and API contracts
```

继续下一阶段，不等待用户。

---

# 24E.4 Phase 2 — CI / README / 文档同步

优先级：`P0/P1`

### 24E.4.1 Extension test 接入 GitHub Actions

仓库已有：

```text
tests/extension.test.cjs
```

如果 runner 有 Node：

```yaml
- name: Test browser extension
  run: node --test tests/extension.test.cjs
```

不为此增加复杂 npm dependency。

---

### 24E.4.2 CI branch trigger

当前：

```text
main
master
```

如果无法确定 `master` 是否仍需要：

```text
不要删除
标记 NEEDS HUMAN CONFIRMATION
```

不要猜。

---

### 24E.4.3 README 同步

README 必须准确写当前 main 已有：

```text
角色练度总览
单角色练度卡
Profile
Campaign MVP
Union Raid Overview MVP
Announcement / Schedule MVP
CDK 单条
CDK 批量
CDK 可用
CDK 历史
签到
Guide skeleton
Poke text interaction
```

同时明确未完成：

```text
Spine 真实渲染
真实语音
Guide 正式内容
Raid Ranking/My/Member
Announcement Push
Daily 点赞/浏览
```

测试数量：

```text
只能写本轮实际测试结果
不能沿用旧数字
```

---

### 24E.4.4 Phase 2 提交

验证后提交：

```text
ci: cover extension tests and sync project status
```

---

# 24E.5 Phase 3 — Profile Research / Collection

优先级：`P1`

只做当前 fixture 已确认字段。

---

### 24E.5.1 RecycleResearchData

当前：

```text
recycle_room_researches
→ X 项 · 等级合计 Y
```

目标：

```python
RecycleResearchData(
    tid=...,
    level=...,
    exp=...,
    display_name=None,
    category=None,
)
```

如果 TID 语义未知：

```text
display_name = None
category = None
```

禁止猜。

`ProfileDashboardData`：

```text
保留完整 recycle_room_researches[]
```

可以保留 summary property 兼容旧 Renderer，但 summary 必须从 DTO 计算。

---

### 24E.5.2 Collection / Memorial

如果 fixture 只有数量：

```text
不能凭空创造 item 结构
```

证据不足时：

```text
BLOCKED
继续下一个任务
```

---

### 24E.5.3 Profile Renderer

新增：

```text
RESEARCH
```

独立 section。

如果没有 verified name：

```text
研究项目 1
研究项目 2
```

不要直接把内部 tid 暴露给用户。

---

### 24E.5.4 Profile 测试

必须覆盖：

```text
recycle_room_researches = None
[]
正常列表
缺 tid
缺 lv
exp optional
未知 tid
Renderer
```

通过后提交：

```text
feat: preserve profile research structure
```

---

# 24E.6 Phase 4 — Union Raid Phase 2 Data Layer

优先级：`P1`

只基于已有或夜间生成的 semantic fixture。

禁止真实网络请求。

---

### 24E.6.1 正式 GetUnionRaidData client method

如果 client 尚无：

```text
get_union_raid_data()
```

则新增。

已确认 payload：

```text
guild_id
nikke_area_id
intl_open_id
```

完整 openid。

---

### 24E.6.2 Models

只实现已观察字段：

```text
RaidSquadMember
RaidAttackData
RaidParticipantSummary
RaidRankingData
```

禁止加入未确认：

```text
timestamp
remaining_attacks
official_rank
season_total
```

---

### 24E.6.3 Aggregation

仅允许：

```text
同一个 GetUnionRaidData response
group by openid
```

真实 openid：

```text
只能存在 service/internal 层
不能进入 public DTO / Renderer
```

聚合：

```text
total_damage
attack_count
attacks[]
```

---

### 24E.6.4 Ranking

排序：

```text
total_damage DESC
```

相同 damage：

```text
相同 rank
```

禁止：

```text
nickname
openid
```

做 hidden tiebreak。

scope：

```text
CURRENT_RESPONSE
```

UI：

```text
当前数据范围排名
```

禁止：

```text
赛季总排名
```

---

### 24E.6.5 My Raid

只有：

```text
绑定账号 canonical openid
```

能直接与：

```text
participate_data[].openid
```

比较时才开放命令。

证据不足时：

```text
只实现 build_my(participant_key)
不开放 command
```

---

### 24E.6.6 Member 功能

夜间 Agent 禁止实现：

```text
nickname join
```

成员详情继续：

```text
BLOCKED
```

直到：

```text
member_id ↔ openid
```

被真实验证。

---

### 24E.6.7 Raid Phase 2 测试

必须覆盖：

```text
同 participant 多刀
不同 participant
damage 聚合
并列排名
zero damage
empty response
malformed item
5 人 squad
squad malformed
public DTO 无 openid
```

提交：

```text
feat: add union raid participant aggregation
```

---

# 24E.7 Phase 5 — Announcement Correctness

优先级：`P1`

只修已确认 bug，不猜正式 CMS。

---

### 24E.7.1 content_id

当前不能允许：

```text
"None"
```

如果：

```text
content_id
id
```

都缺：

```text
跳过 item
记录 warning
```

测试：

```text
两个无 ID item 不发生 collision
```

---

### 24E.7.2 content_version / deadline_version

正文变化：

```text
content_version +1
```

deadline 真的变化：

```text
deadline_version +1
```

正文变化但 deadline 不变：

```text
deadline_version 不变
```

并保证：

```text
save_cache
load_cache
```

后版本不回退。

---

### 24E.7.3 正式 CMS

夜间 Agent 禁止：

```text
凭 web 搜索猜 InformationFeeds API
```

当前 GetAnnouncements：

```text
保持 fallback/MVP
```

---

### 24E.7.4 Announcement 提交

```text
fix: harden announcement identity and deadline versions
```

---

# 24E.8 Phase 6 — CDK Batch Persistent Idempotency

优先级：`P1`

目标：

```text
batch 中每个 code
复用单条兑换持久 run-key 语义
```

run key：

```text
qq_id
game_uid
SHA256(CDK)
```

要求：

```text
已成功 code 不重复请求
stale running 可恢复
failed/retryable 合同保持
RESULT_UNKNOWN 不自动判成功/失败
CookieExpired stop
RateLimit stop
account lock 保持
```

推荐抽：

```text
execute_cdk_idempotently()
```

让：

```text
单条
批量
```

共同调用。

禁止保存明文 CDK 历史。

提交：

```text
refactor: share persistent CDK redemption idempotency
```

---

# 24E.9 Phase 7 — Background Task Lifecycle

优先级：`P1/P2`

检查所有：

```python
asyncio.create_task(...)
```

尤其：

```text
daily
summary
announcement sync
```

实现统一：

```text
_spawn_background_task()
```

要求：

```text
self._background_tasks 追踪
done callback 自动移除
terminate() cancel
await/gather
suppress CancelledError
```

补 lifecycle tests。

提交：

```text
fix: track plugin background task lifecycle
```

---

# 24E.10 Phase 8 — Safe Cleanup / Documentation

优先级：`P2`

可以做：

```text
更新开发文档状态
更新 README
更新测试基线
删除明显失效注释
修正不存在的 contracts/ 文档引用
```

如果不真正创建：

```text
docs/contracts/
docs/evidence/
```

就不要在代码中声称它们存在。

禁止：

```text
重写 main.py
大规模架构重构
更改现有用户命令语义
```

---

# 24E.11 夜间必须跳过的 BLOCKED 功能

以下任务遇到时：

```text
记录 BLOCKED
继续下一任务
```

禁止猜。

```text
1. Raid member_id ↔ openid
2. Raid 完整赛季范围
3. Raid timestamp / 最近一刀
4. Raid allowed / remaining attacks
5. 更多 Campaign stage ID
6. Daily 点赞 API
7. Daily 浏览 API
8. 正式 InformationFeeds CMS
9. Spine runtime/license 最终决定
10. QQ 真语音 adapter 实机联调
11. Advise 数据源
12. Tower 详情数据源
13. Guide 正式图片授权
14. 任何需要真实 Cookie / 账号写操作的测试
```

---

# 24E.12 测试纪律

每个 Phase 至少：

```bash
python -m compileall -q .
pytest -q
git diff --check
```

如果 extension 修改或 CI 已接 Node：

```bash
node --test tests/extension.test.cjs
```

整个夜间结束前：

```bash
python -m compileall -q .
pytest -q
node --test tests/extension.test.cjs
git diff --check
git status
git log --oneline main..HEAD
```

如果测试失败：

```text
不得声称完成
```

禁止：

```text
skip
xfail
删除失败测试
放宽关键断言
为了绿 CI 改业务合同
```

---

# 24E.13 Commit 纪律

每个 Phase 一个独立 commit。

推荐：

```text
fix: harden raid evidence and API contracts
ci: cover extension tests and sync project status
feat: preserve profile research structure
feat: add union raid participant aggregation
fix: harden announcement identity and deadline versions
refactor: share persistent CDK redemption idempotency
fix: track plugin background task lifecycle
```

禁止：

```text
squash
merge main
force push
```

如果远端允许：

```bash
git push origin feat/overnight-backlog
```

可以多次 push 作为备份。

除非用户明确授权：

```text
不要自动创建 PR
不要自动 merge
```

---

# 24E.14 单 Phase 失败恢复

某 Phase 连续修复仍不能安全通过：

```text
1. git status
2. 保存当前 diff
3. 不提交破损代码
4. 回到上一绿色 commit
5. 记录 BLOCKED 原因
6. 继续下一个 Phase
```

一个失败任务不能阻塞整个夜间执行。

---

# 24E.15 夜间结束条件

直到满足：

```text
A. 所有无需人工确认的 Phase 完成
B. 剩余全部 BLOCKED
C. 环境/权限阻止继续
D. 用户中途停止
```

---

# 24E.16 夜间最终报告格式

Agent 最终必须给出：

```text
1. 起始 main SHA
2. 工作分支
3. 最终 HEAD SHA
4. 完成 Phase
5. 每个 commit SHA + message
6. 修改文件
7. 新增/修改测试数量
8. pytest 最终结果
9. compileall 结果
10. Node test 结果
11. git diff --check
12. 是否已 push
13. 全部 BLOCKED 项
14. 原计划仍未完成项
15. 下一步最需要人工确认的内容
```

禁止只回复：

```text
“全部完成”
```

必须给出可验证结果。

---

# 24E.17 夜间 Agent 直接执行 Prompt

以下内容可以直接复制给 Coding Agent：

```text
你将在用户离线期间长时间自主开发仓库：

September6969/astrbot_plugin_nikke

当前默认分支：
main

开发计划：
以仓库当前 main 和最新主开发计划为准。

目标：
在用户离线期间，尽可能多地完成“无需人工确认、无需真实账号凭据、无需猜测未知 API”的开发任务。

执行顺序：

Phase 1
Contract & Evidence Hardening
- 修 Raid capture script 的 GetMyGuildInfo payload
- 删除所有 openid split
- relationship-preserving Raid semantic sanitizer
- semantic fixture
- UnionRaidBuilder current_hp clamp
- Campaign unknown BlaBlaError rethrow

Phase 2
CI / README
- node --test tests/extension.test.cjs 接入 CI
- README 与当前 main 同步
- branch trigger 不确定时标 NEEDS HUMAN CONFIRMATION，不猜

Phase 3
Profile Research
- RecycleResearchData
- 保留 tid/lv/exp
- 不猜 TID 语义
- RESEARCH section
- evidence 不足的 Collection 跳过

Phase 4
Union Raid Phase 2 Data
- GetUnionRaidData client/service
- RaidSquadMember
- RaidAttackData
- RaidParticipantSummary
- CURRENT_RESPONSE ranking
- group by openid only inside one response
- public DTO 不含 openid
- 不做 nickname join
- identity 未确认则不开放“我的”命令

Phase 5
Announcement Correctness
- reject missing content id
- content_version / deadline_version 分离
- cache round-trip
- 不猜正式 CMS

Phase 6
CDK Batch Persistent Idempotency
- batch 每个 code 复用单条 run-key
- SHA256 only
- 不保存明文历史
- RESULT_UNKNOWN / CookieExpired / rate-limit 语义保持

Phase 7
Background Task Lifecycle
- 统一追踪 asyncio.create_task
- terminate cancel + await
- lifecycle tests

Phase 8
Safe cleanup/docs
- README
- development docs
- stale comments
- 不做大重构

任何任务需要以下信息时立即 BLOCKED 并跳过：
- Raid member_id ↔ openid
- Raid season completeness
- Raid reliable timestamp
- remaining attacks
- unknown Campaign stage IDs
- Daily like/browse endpoints
- InformationFeeds CMS
- Spine runtime/license final decision
- real QQ voice integration
- Advise/Tower unknown data source
- Guide image licensing
- real user Cookie/account write tests

每 Phase：
python -m compileall -q .
pytest -q
git diff --check

Node 可用时：
node --test tests/extension.test.cjs

测试通过才 commit。

每 Phase 独立 commit。
不改 main。
不 force push。
不 merge。
不删除测试。
不 skip/xfail。
不猜接口。
不泄露敏感 ID。
不加入主观评分。

某 Phase 失败时：
回到上一绿色 commit，
记录 BLOCKED，
继续下一 Phase。

结束前完整跑：
python -m compileall -q .
pytest -q
node --test tests/extension.test.cjs
git diff --check
git status
git log --oneline main..HEAD

最终报告：
起始 SHA
最终 SHA
branch
commits
完成 Phase
修改文件
测试结果
push 状态
BLOCKED
剩余计划
下一步人工确认项
```

---

# 24E.18 夜间自动执行的实际目标

夜间 Agent 的成功标准不是：

```text
把 5000 行计划全部改成 DONE
```

而是：

```text
尽可能把所有“仓库内证据足够”的任务连续跑完
+
所有需要真实世界证据的任务准确停在 BLOCKED
+
第二天能按独立 commit 审查和拆 PR
```

这样可以最大化夜间产出，同时避免第二天得到一个：

```text
改动巨大
接口靠猜
无法验证
不能合并
```

的分支。

# 24F. 夜间 Agent 最大化推进策略（主动解除 BLOCKED）

> 目标：在用户离线期间，不仅完成所有已经具备证据的任务，还主动研究并尽量解除原本的 BLOCKED 项。  
> 原则：**先研究、再验证、再实现；确实需要真实环境或人工决策时才停。**

---

## 24F.1 BLOCKED 不再直接跳过

夜间 Agent 遇到原本标记为 `BLOCKED` 的功能时，不再直接停止或跳过。

统一改成四级：

| 状态 | 含义 | Agent 行为 |
|---|---|---|
| `RESEARCHABLE` | 可以通过仓库、公开前端代码、静态资源、已有开源实现继续研究 | 主动搜索、建立证据、尽量解除 |
| `NEEDS_LIVE_EVIDENCE` | 最终需要一次真实账号/真实 Bot 环境验证 | Agent 先把代码、diagnostic、fixture、测试全部准备好 |
| `NEEDS_HUMAN_DECISION` | 需要用户决定产品策略、授权、许可证风险 | Agent 整理选项、风险、推荐默认值，但不替用户做决定 |
| `HARD_BLOCKED` | 公开资料、本地代码、静态分析、diagnostic 都无法继续 | 记录证据与缺口，跳到下一个任务 |

执行原则：

```text
BLOCKED
↓
先尝试转成 RESEARCHABLE
↓
如果有公开/本地证据，继续做
↓
如果只缺一次真实验证，转 NEEDS_LIVE_EVIDENCE
↓
如果只缺用户决定，转 NEEDS_HUMAN_DECISION
↓
只有所有路径都无效，才 HARD_BLOCKED
```

---

# 24F.2 Agent 的主动研究权限

夜间 Agent 可以主动做：

```text
扫描整个仓库
搜索历史 commit / branch / PR
搜索公开 GitHub 代码
搜索 BlaBlaLink/NIKKE 前端 JS bundle
搜索 source map（如果公开可访问）
搜索 endpoint 字符串
搜索公开静态 game data
搜索 Nikke-DB / ExiaInvasion 等已有公开实现
搜索 AstrBot / OneBot 官方文档
研究公开 runtime/license 文档
编写离线 diagnostic
编写 request/response parser
编写 mock/fixture test
生成 relationship-preserving fixture
建立 adapter / service skeleton
```

但必须遵守：

```text
不使用真实 Cookie
不提交真实 OpenID
不进行真实账号写操作
不自动兑换 CDK
不自动点赞/浏览/签到
不自动发送真实 QQ 消息
不把第三方攻略图直接复制进仓库
不假设许可证允许
```

---

# 24F.3 主动解除 Union Raid 阻塞

## 24F.3.1 当前 round / difficulty / level selector

状态：

```text
RESEARCHABLE
```

Agent 应主动：

```text
1. 扫 GetUnionRaidLevelInfo 前端消费逻辑
2. 搜 difficulty / level / step / manager_info / status 相关字段
3. 搜公开实现
4. 检查多份 fixture 是否有可判定规律
5. 如果找到明确 selector，写纯函数 + fixture tests
6. 如果只能得到启发式，不进入生产
```

允许输出：

```text
selector evidence report
```

只有明确证据后才解除 BLOCKED。

---

## 24F.3.2 GetUnionRaidData 是否覆盖完整赛季

状态：

```text
RESEARCHABLE → NEEDS_LIVE_EVIDENCE
```

Agent 应搜索：

```text
pagination
page
cursor
offset
day
difficulty
level
season
history
```

并检查：

```text
前端是否直接一次请求后完成排行
是否存在多次分页调用
是否存在筛选参数
```

如果公开前端明确：

```text
单次 GetUnionRaidData = 全部当前赛季
```

则可以把证据等级提高。

如果仍无法证明：

```text
保留 CURRENT_RESPONSE scope
```

同时写 diagnostic，供真实环境一次验证。

---

## 24F.3.3 我的 Raid identity

状态：

```text
RESEARCHABLE / NEEDS_LIVE_EVIDENCE
```

Agent 应：

```text
分析 storage 中 canonical game_openid
分析 x_common_params.openid
分析 GetUnionRaidData participate_data[].openid
```

写：

```text
scripts/diagnose_raid_identity.py
```

要求：

```text
不输出真实 openid
只输出 hash/equality/计数
```

示例：

```text
canonical_openid_matches_raid: YES/NO
xcommon_openid_matches_raid: YES/NO
raid_participant_count: N
my_attack_rows: N
```

如果离线证据足够：

```text
实现 identity resolver
```

否则留下 diagnostic，第二天用户只需运行一次。

---

## 24F.3.4 member_id ↔ openid

状态：

```text
RESEARCHABLE / NEEDS_LIVE_EVIDENCE
```

Agent 应主动：

```text
搜索 GetGuildMembers
搜索 GetGuildDetail
搜索前端 member list + raid ranking 的关联逻辑
搜索是否同一对象同时包含 member_id/openid
搜索是否存在额外 mapping endpoint
```

可以写：

```text
scripts/diagnose_raid_member_mapping.py
```

只输出：

```text
mapping_candidates_found
stable_one_to_one
duplicate_nickname_count
unmatched_count
```

不输出真实 ID。

如果只找到 nickname：

```text
仍然不能实现稳定 join
```

---

## 24F.3.5 最近一刀 / 时间顺序

状态：

```text
RESEARCHABLE
```

Agent 搜索：

```text
timestamp
created_at
attack_at
battle_at
day
step
sequence
order
```

并找前端排序逻辑。

只有官方字段/明确代码能支持时才实现：

```text
最近一刀
```

否则 UI 继续写：

```text
攻击记录
```

不加“最近”。

---

## 24F.3.6 已用 / 剩余攻击次数

状态：

```text
RESEARCHABLE
```

Agent 搜：

```text
remaining_count
attack_count
challenge_count
daily_count
raid ticket
union raid count
```

如果前端使用固定规则：

```text
记录来源与版本
```

如果完全靠游戏常识：

```text
不进入代码
```

---

## 24F.3.7 Raid 历史赛季

状态：

```text
RESEARCHABLE
```

搜索：

```text
History
Season
Previous
Past
UnionRaidHistory
RaidRecord
```

发现真实 endpoint 后：

```text
先实现 read-only client + fixture
不要直接做 UI
```

---

# 24F.4 主动解除 Campaign 阻塞

## 24F.4.1 更多 Stage ID

状态：

```text
RESEARCHABLE
```

Agent 可以：

```text
搜索公开静态 game data
搜索 Nikke 数据仓库
搜索前端 stage table
搜索已有开源项目的 stage mapping
```

要求：

```text
每个 mapping 必须有来源
不能用公式推导
不能靠连续数字猜
```

如果能找到完整静态表：

```text
导入 registry
补 provenance
补 tests
```

如果来源不够可靠：

```text
生成 candidate mapping
不进入 production assets
```

---

# 24F.5 主动解除 Daily 点赞 / 浏览阻塞

状态：

```text
RESEARCHABLE
```

Agent 应搜索 BlaBlaLink 前端：

```text
like
thumb
recommend
view
read
browse
task
mission
daily
point
```

寻找：

```text
状态查询 endpoint
写 endpoint
payload
response code
完成条件
```

夜间可完成：

```text
client adapter
request contract
response parser
mock tests
feature flag
UNKNOWN_AFTER_ACTION 状态机
```

但如果只有写 endpoint 没有可验证状态查询：

```text
不能默认启用
```

真实写动作保持：

```text
disabled by default
```

---

# 24F.6 主动解除正式公告 CMS 阻塞

状态：

```text
RESEARCHABLE
```

Agent 应搜索：

```text
NIKKE 官网
Level Infinite
InformationFeeds
公告页面 JS
XHR/fetch endpoint
GraphQL/REST endpoint
locale/category/page 参数
```

优先证据：

```text
官方网页前端代码
官方请求
公开 API 响应
```

其次：

```text
可信开源实现
```

如果找到：

```text
写 AnnouncementSource adapter
保存 sanitized fixture
补 pagination/locale tests
```

如果只有 HTML scraping：

```text
可作为 fallback research
不能自动宣布为正式 API
```

---

# 24F.7 主动推进 Spine

状态：

```text
RESEARCHABLE
```

Agent 可以在无人值守时完成绝大部分 Spike：

```text
runtime 候选调研
Spine 版本兼容表
license 文档整理
安装候选 runtime
Linux headless 测试
透明 PNG 输出
atlas/skeleton parser
single/multi texture
bounds/crop
benchmark
RSS
worker 1/2
failure matrix
```

允许自动下载：

```text
公开可访问的测试样本
```

禁止：

```text
使用需要账号授权的私有游戏资源
违反许可证
把第三方 runtime/source 直接复制进仓库而不满足 license
```

最终如果只有：

```text
是否接受某许可证/素材权利风险
```

未决，则转：

```text
NEEDS_HUMAN_DECISION
```

而不是整项停止。

---

# 24F.8 主动推进 QQ 语音

状态：

```text
RESEARCHABLE → NEEDS_LIVE_EVIDENCE
```

夜间 Agent 可以：

```text
查 AstrBot event API
查 aiocqhttp / OneBot poke event
实现 poke listener
实现 VoicePreference
实现 audio cache
实现 OGG/WAV pipeline
实现 ffmpeg probe
实现 adapter sender abstraction
写 mock adapter tests
```

真正：

```text
QQ 实机 poke
真实 Record 发送
```

留到：

```text
NEEDS_LIVE_EVIDENCE
```

第二天只需实机验证。

---

# 24F.9 主动研究 Advise / Tower / Cube / Collection / Skill

这些早期功能统一改为：

```text
RESEARCHABLE
```

Agent 可以搜索：

```text
Nikke-DB
公开静态 game data
前端 bundle
开源项目
```

如果找到可靠数据源：

```text
建立 registry/service
fixture
tests
```

如果没有：

```text
保持 DEFERRED
```

不能因为“想做完”而抄未经授权攻略站正文。

---

# 24F.10 Guide 功能的最大化推进

状态：

```text
RESEARCHABLE + NEEDS_HUMAN_DECISION
```

Agent 可以先做完：

```text
Guide registry
分类
多图排序
分页
版本字段
来源字段
credit 字段
过期提示
Renderer
tests
空目录 fallback
```

无法自行决定：

```text
具体第三方攻略图是否获授权
```

因此代码系统可以完成，内容授权留给用户。

---

# 24F.11 自动生成第二天只需“一次运行”的诊断工具

夜间 Agent 应尽量把需要真实账号的阻塞压缩成：

```text
第二天运行一个命令
```

推荐脚本：

```text
scripts/diagnose_raid_identity.py
scripts/diagnose_raid_member_mapping.py
scripts/diagnose_raid_scope.py
scripts/diagnose_daily_tasks.py
scripts/diagnose_voice_adapter.py
```

统一要求：

```text
默认只读
默认不写操作
不输出 Cookie
不输出真实 openid
不输出 QQ
不输出 game_uid
ID 只输出 hash/pseudonym
```

输出示例：

```text
RAID IDENTITY
canonical_match: YES
xcommon_match: YES
my_rows: 3

RAID SCOPE
distinct_days: 3
distinct_levels: 7
pagination_field_found: NO
cursor_field_found: NO

GUILD MAPPING
stable_direct_mapping: NO
nickname_duplicates: 2
```

用户第二天只需把输出交给 Agent，即可继续解除最后一层阻塞。

---

# 24F.12 最大化夜间执行顺序

新的推荐顺序：

```text
Phase 1  当前已知 Contract 修复
Phase 2  Evidence tooling 修复
Phase 3  主动 Unblock Research
Phase 4  Profile Research
Phase 5  Raid Phase 2
Phase 6  Announcement
Phase 7  Daily read/write safety
Phase 8  CDK batch
Phase 9  Background lifecycle
Phase 10 Spine Spike
Phase 11 Voice offline implementation
Phase 12 Guide system
Phase 13 Deferred query research
Phase 14 README/docs/CI cleanup
```

重要变化：

```text
不再把 BLOCKED 项全部留到最后
```

而是：

```text
先主动研究能否解除
解除后立即进入实现队列
```

---

# 24F.13 最大化 Agent 执行 Prompt

以下版本优先于 24E 中较保守的夜间 Prompt。

```text
你将在用户离线期间长时间自主开发：

September6969/astrbot_plugin_nikke

目标：
尽可能多地完成全部开发计划，包括主动研究并解除原本的 BLOCKED 项。

原则：
- 不直接改 main
- 不 force push
- 不 merge
- 不删除/弱化测试
- 不 skip/xfail
- 不使用真实 Cookie/OpenID/QQ/game_uid
- 不执行真实账号写操作
- 不猜未知 API
- 但不能因为任务标 BLOCKED 就直接跳过

遇到 BLOCKED 时执行 UNBLOCK RESEARCH：

1. 搜当前仓库
2. 搜历史 commit / PR / branch
3. 搜公开 GitHub 实现
4. 搜 BlaBlaLink/NIKKE 官方前端 JS bundle
5. 搜公开 source map
6. 搜 endpoint 字符串
7. 搜公开静态 game data
8. 搜 Nikke-DB / ExiaInvasion 等可信公开实现
9. 搜 AstrBot / OneBot 官方文档
10. 检查当前 fixture
11. 能写离线 diagnostic 的就写
12. 能建立 request/response contract 的就建立
13. 能建立 fixture/test 的就建立
14. 证据足够则解除 BLOCKED 并继续实现
15. 只有最后确实需要真实环境/人工决策才停

把阻塞重新分类为：

RESEARCHABLE
NEEDS_LIVE_EVIDENCE
NEEDS_HUMAN_DECISION
HARD_BLOCKED

不要把 RESEARCHABLE 留给用户。

优先执行：

A. 已知 Contract 修复
- Raid capture GetMyGuildInfo payload
- full openid
- relationship-preserving sanitizer
- Raid current_hp clamp
- Campaign unknown error rethrow
- Announcement ID/version
- Daily ambiguous write retry
- CDK batch persistent idempotency
- background task lifecycle
- Node extension test CI
- README/docs

B. 主动研究并解除 Raid
- current round selector
- complete season scope
- my openid identity
- member_id ↔ openid
- timestamp/order
- remaining attacks
- historical season endpoint

C. 主动研究 Campaign
- 更多 stage mapping
- 只接受有来源的静态表
- 禁止公式猜 stage_id

D. 主动研究 Daily
- like endpoint
- browse endpoint
- status query
- payload
- response
- 只做离线 client/tests
- 所有真实写操作默认关闭

E. 主动研究正式公告 CMS
- Level Infinite / InformationFeeds
- 官方网页 JS/XHR
- locale/pagination/category
- 找到真实 API 后做 adapter + fixture
- 找不到则保留 fallback

F. Profile
- structured research
- collection evidence
- renderer

G. Raid Phase 2
- RaidAttackData
- RaidSquadMember
- participant aggregation
- ranking
- my
- member only if identity unlocked

H. Spine
- runtime research
- version matching
- license report
- headless renderer spike
- multi texture
- PNG
- bounds
- benchmark
- RSS
- queue integration readiness

I. Voice
- poke listener
- VoicePreference
- audio resolver
- cache
- ffmpeg
- Record sender mock
- actual QQ send only mark NEEDS_LIVE_EVIDENCE

J. Guide
- registry
- version
- source/credit/license metadata
- pagination
- renderer
- do not import unlicensed images

K. Deferred queries
- Skill
- Advise
- Tower
- Cube
- Collection
- Image
- Export
主动找可靠数据源。
有证据就实现数据层/测试。
无证据保持 DEFERRED。

需要真实账号才能完成的部分：
不要停。
先写安全 diagnostic，让用户第二天只需运行一次。

Diagnostic 规则：
- read-only 默认
- 不打印敏感 ID
- hash/pseudonym only
- 不执行签到/点赞/浏览/CDK 等写操作

每个独立阶段：
python -m compileall -q .
pytest -q
git diff --check
Node 可用时：
node --test tests/extension.test.cjs

测试通过才 commit。

推荐每个功能独立 commit。
可以连续 push 工作分支作备份。
不要创建/merge PR，除非用户已经明确授权。

一个 Phase 失败：
- 不提交破损代码
- 回到上一绿色 commit
- 记录原因
- 继续其它任务

直到：
1. 所有可离线完成任务做完
2. 所有 RESEARCHABLE 被研究过
3. 剩余只有 NEEDS_LIVE_EVIDENCE / NEEDS_HUMAN_DECISION / HARD_BLOCKED
4. 或环境无法继续

结束前完整跑：
python -m compileall -q .
pytest -q
node --test tests/extension.test.cjs
git diff --check
git status
git log --oneline main..HEAD

最终报告必须包含：

- 起始 main SHA
- 最终 branch / HEAD SHA
- 所有 commits
- 完成的功能
- 新解除的 BLOCKED
- RESEARCHABLE 研究结果
- NEEDS_LIVE_EVIDENCE
- NEEDS_HUMAN_DECISION
- HARD_BLOCKED
- 新 diagnostic 脚本
- pytest / Node / compileall / diff-check
- push 状态
- 下一步用户只需要做的最少动作

目标不是保守地停下来，
而是在不猜、不泄密、不进行危险写操作的前提下，
尽可能把所有可以自动推进的工作推进到最远。
```

---

# 24F.14 第二天用户应看到的结果

理想结果不是：

```text
“遇到 13 个 BLOCKED，没做”
```

而应类似：

```text
完成：
7 个 Phase
11 个 commit
220+ tests

已解除：
Raid my identity → 已实现
Raid season scope → 当前响应完整性证据增强
Daily like → 已找到 endpoint，client/tests 完成，默认关闭
Announcement CMS → 已找到官方 endpoint，adapter 完成
Voice → 离线代码完成

只剩 Live Evidence：
Raid member mapping
真实 QQ voice send

只剩 Human Decision：
Spine runtime/license
Guide 图片授权
```

这才是夜间 Agent “尽量多做”的目标。

# 25. 当前已确认的代码债优先级

这部分是本次仓库扫描后最重要的新结论。

## P0 — 在继续 Raid 抓包前必须修

### D-01 capture_union_raid_fixtures.py 请求合同过期

当前脚本：

```text
openid split
错误 GetMyGuildInfo payload
```

必须改成与生产 client 一致：

```text
GetMyGuildInfo {"ignore_toast": true}
完整 openid
```

### D-02 Raid sanitizer 不保留关系

Phase 2 需要 relationship-preserving fixture。

这两项应一起修。

---

## P1 — 数据合同正确性

### D-03 UnionRaidBuilder current_hp 缺 max clamp

补：

```text
safe_current = min(max(current_hp,0),max_hp)
```

### D-04 Campaign Client 吞掉未知 BlaBlaError

除已知：

```text
1300017
212000
300001
```

外，其它 error 应 rethrow。

### D-05 Announcement content_id None collision

无 ID item 必须拒绝或稳定构造，不得 `"None"`。

### D-06 Announcement deadline_version persistence

分离：

```text
content version
deadline version
```

并确保 cache reload 后不回退。

### D-07 Daily ambiguous write retry

timeout/network after write：

```text
recheck
仍未知 → UNKNOWN_AFTER_ACTION
不盲重发
```

---

## P2 — 生产可靠性

### D-08 CDK batch 没有持久 per-code idempotency

复用 single run primitive。

### D-09 Scheduler 动态 task 未统一追踪

统一 task registry。

### D-10 Extension Node test 未接入 CI

加入：

```text
node --test tests/extension.test.cjs
```

### D-11 README 同步

更新 PR #4 后功能面。

### D-12 CI 分支与保护

```text
确认是否删除 master trigger
考虑 main required CI
```

---

## P3 — 维护债

### D-13 deprecated register

当前 CI warning：

```text
register_star deprecated
```

确认 AstrBot 新 API 后迁移。

### D-14 audioop / Python 3.13

由 AstrBot 依赖触发。

在 Python 3.13 支持前验证替代链。

### D-15 main.py 过重

当前同时承担：

```text
router
scheduler
account
daily
CDK
raid
campaign
announcement
guide
admin
```

后续新增大模块时再按功能拆，不进行一次性全项目重构。

---

# 26. 重新排序后的 Roadmap

此前路线直接从 Profile 开始，现在根据仓库扫描结果应调整。

---

## PR #5 — Contract & Evidence Hardening

这是现在最应该先做的 PR。

范围严格限定：

```text
scripts/capture_union_raid_fixtures.py
union_raid_builder.py
client.py（Campaign error）
tests
README/开发文档最小同步
```

任务：

- [ ] Raid capture 使用 `{"ignore_toast": True}`。
- [ ] 删除所有 `openid.split(...)`。
- [ ] Raid semantic sanitizer。
- [ ] 新增 relationship-preserving fixture。
- [ ] current_hp clamp。
- [ ] Campaign 未知 error rethrow。
- [ ] 新增对应测试。
- [ ] README 增补 PR #4 已完成命令。
- [ ] Node extension test 接入 CI（可同 PR，若 scope 可控）。

不做：

```text
Raid Ranking UI
Profile UI
Spine
Announcement Push
Voice
```

完成后再开始新业务。

---

## PR #6 — Profile Contract Finish

- [ ] RecycleResearchData。
- [ ] 保留 tid/lv/exp。
- [ ] 未验证 TID 不猜。
- [ ] Collection / Research 独立 section。
- [ ] Campaign/Basic 信息架构清理。
- [ ] fixture regression。
- [ ] None / [] / 0 语义不回归。

---

## PR #7 — Union Raid Phase 2 Data

只做数据层与文本/简单 Renderer。

- [ ] GetUnionRaidData client method。
- [ ] RaidAttackData。
- [ ] RaidSquadMember。
- [ ] participant grouping by openid。
- [ ] RaidParticipantSummary。
- [ ] ranking ties。
- [ ] current-response scope 标签。
- [ ] “我的”稳定 identity 判断。
- [ ] privacy tests。

命令：

```text
/妮姬 联盟突袭 排名
/妮姬 联盟突袭 我的
```

暂缓：

```text
成员 <昵称>
```

直到 member_id ↔ openid 真实映射确认。

---

## PR #8 — Announcement Correctness + Push Foundation

先修数据正确性：

- [ ] stable content ID validation。
- [ ] content_version。
- [ ] deadline_version。
- [ ] deadline hash/identity。
- [ ] cache migration tests。
- [ ] source adapter 抽象。

再做 push foundation：

- [ ] PushRecord。
- [ ] target isolation。
- [ ] first subscription no-backfill。
- [ ] recent-window rescan。

正式 CMS 未验证时：

```text
当前 GetAnnouncements 继续作为 MVP/fallback
```

---

## PR #9 — Daily Write Safety + Community Tasks

第一步先修签到：

- [ ] UNKNOWN_AFTER_ACTION。
- [ ] timeout 后不 blind retry。
- [ ] 写后 recheck。
- [ ] tests。

再研究：

```text
点赞
浏览
```

没有真实 endpoint/fixture 前不写实现。

---

## PR #10 — Spine Real Spike

完全独立。

目标：

```text
真正 render 一张透明完整人物 PNG
```

而不是继续增加抽象骨架。

---

## PR #11 — Voice

- [ ] Poke event。
- [ ] preference。
- [ ] audio resolver。
- [ ] cache。
- [ ] ffmpeg。
- [ ] adapter sender。
- [ ] text fallback。

---

## PR #12 — Guide Content / UI polish

- [ ] guides registry。
- [ ] 合法图片内容。
- [ ] source/license/update date。
- [ ] 多图。
- [ ] UI polish。

---

# 27. 下一步开发入口

当前最短路径已经不是：

```text
直接做 Profile
```

而是：

```text
main@deeef627
    ↓
PR #5 Contract & Evidence Hardening
    ↓
修 Raid capture script
    ↓
生成可用于聚合的 semantic fixture
    ↓
修 Raid HP clamp
    ↓
修 Campaign unknown errors
    ↓
README / CI 同步
    ↓
再进入 Profile / Raid Phase 2
```

原因是：

```text
现在代码主链已经很多，
下一步最危险的不是“功能少”，
而是继续建立在旧抓包脚本和不可用于聚合的 fixture 上。
```

---

# 28. 当前完成度结论

按当前 repo，而不是旧计划：

## 稳定基础已经完成

```text
安全绑定
账号加密存储
基础部署
命令路由
练度总览
单角色卡
Profile 主体
Campaign MVP
Raid Overview MVP
CDK 单条主链
Announcement 查询基础
CI
```

## 近期需要先收债

```text
Raid capture contract
Raid semantic fixture
Raid HP clamp
Campaign unknown error propagation
Announcement version correctness
Daily ambiguous write semantics
README/CI drift
```

## 大功能仍未完成

```text
Raid ranking / my / member
Profile structured Research
Announcement auto push
Daily like / browse
real Spine
real voice
guide content
```

---

# 29. “DONE” 的统一定义

以后不能只凭“命令能执行”标 DONE。

读取功能至少需要：

```text
[ ] request contract
[ ] response fixture
[ ] DTO/model
[ ] malformed strategy
[ ] network/error strategy
[ ] privacy
[ ] unit tests
[ ] command tests
[ ] renderer tests（如适用）
[ ] CI
[ ] README/开发文档更新
```

写功能额外必须：

```text
[ ] idempotency
[ ] rate limit
[ ] ambiguous timeout semantics
[ ] post-write verification
[ ] no unsafe blind retry
[ ] default enable policy
```

---

# 30. 文档维护规则

每次 PR 合并后同步：

```text
main SHA
plugin version
CI baseline
command surface
feature status
known debt
next PR
```

如果源码 docstring 引用了：

```text
contracts/foo.md
```

则：

```text
要么把该文件真正加入 repo
要么删除/改成当前存在的文档引用
```

避免“代码说有 contract 文件，但仓库里没有”的状态再次积累。

---

# 31. 当前建议的第一条开发任务

如果现在立刻开下一 PR，建议标题：

```text
fix: align raid evidence tooling and remaining data contracts
```

第一阶段只修：

```text
1. capture_union_raid_fixtures.py
   - GetMyGuildInfo payload
   - full openid
   - relationship-preserving sanitizer

2. union_raid_builder.py
   - current_hp clamp

3. client.py
   - Campaign unknown errors rethrow

4. tests
   - capture contract
   - HP over-max
   - Campaign unknown error

5. README / CI
   - 功能列表同步
   - node extension test
```

不要在同一个 PR 里继续加入：

```text
Raid ranking
Profile redesign
Spine
Voice
Announcement push
```

先让“证据工具”和“当前数据合同”重新可信，再扩功能。
