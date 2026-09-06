# NIKKE BlaBlaLink 插件 — 审核修复、最大自治执行与后续开发总文档（历史规则）

> 仓库：`September6969/astrbot_plugin_nikke`  
> 本文是 overnight 阶段的执行规则和历史快照；不是当前状态入口。当前主分支基线、PR #5 和工作区以 [POST_MERGE_STATUS.md](POST_MERGE_STATUS.md) 为准。
> 本文快照中的主分支基线：`main@deeef6277f09a42918d71b44f49170398a05558b`
> 本文快照中的工作分支：`feat/overnight-backlog`，已由 PR #5 合并，不是当前开发分支。
> 当前 HEAD 与提交数量以 `git rev-parse HEAD`、`git rev-list --count origin/main..HEAD` 为准，避免固定计数过期。
> 本文目的：统一此前讨论中的 **审核修复、Agent 最大自治、Guide/Spine/Voice 资源策略、人工边界、后续开发顺序和执行 Prompt**。  
> 本文优先于此前较保守的“人工任务”说明。

新的阶段任务入口为 [POST_MERGE_PHASE2_PLAN.md](POST_MERGE_PHASE2_PLAN.md)；其 A/B 顺序和边界优先于本文中针对 overnight 阶段的当前性描述。

---

# 1. 总原则

本项目从现在开始采用：

```text
Agent 最大自治
+
最小人工参与
+
安全可回滚
+
真实证据优先
```

基本规则：

```text
能由 Agent 自己研究、验证、写代码、跑测试、写工具、查公开前端、查公开 API、
查公开静态资源、查 GitHub、查官方文档、做只读诊断、做受控实验解决的问题，
默认都由 Agent 自己完成。

不要因为：
- 计划里写 BLOCKED
- 仓库当前没有
- 需要额外研究
- 需要写临时脚本
- 需要分析 JS
而停下来。
```

正确流程：

```text
问题
↓
仓库研究
↓
Git 历史
↓
公开 Web / GitHub / 官方文档
↓
前端 JS / source map / API / 静态资源
↓
已有 fixture
↓
diagnostic
↓
受控真实实验
↓
建立合同
↓
补测试
↓
实现
↓
全量验证
```

---

# 2. 当前 GitHub 审核结论

当前工作分支总体质量较好，GitHub Actions 已覆盖：

```text
Node extension test
Python 3.10
Python 3.11
Python 3.12
```

当前已确认 CI 全绿。

但合并前仍有若干需要优先修复的问题。

---

# 3. 合并前必须修复的问题

## 3.1 P1 — Raid semantic sanitizer 可能泄露原始伤害比例

当前 semantic sanitizer 使用：

```text
所有 total_damage
→ 计算 GCD
→ 按 GCD 归一
→ 再乘 1000
```

问题：

```text
如果 GCD = 1
→ 输出值与真实伤害成精确线性关系
→ 除以 1000 就能恢复原始伤害
```

即使 GCD 不为 1，也保留了精确比例。

### 必须改成

只保留：

```text
同一用户关系
不同用户关系
tie 关系
排序关系
聚合关系
slot/day/level/step 等必要结构
```

不保留：

```text
真实数值
可逆比例
精确伤害比例
```

推荐做法：

```text
真实响应
↓
身份关系映射
↓
重新生成纯合成伤害
↓
只保证排序/tie/聚合关系
↓
输出 synthetic semantic fixture
```

---

## 3.2 P1 — Guide 未登记素材 fallback 绕过授权 registry

当前 Guide 已有 registry 机制，要求：

```text
source
credit
license
updated_at
game_version
```

但当前命令仍可能在 registry 没内容时，直接读取：

```text
assets/guides/<category>/
```

并发送第一张图片。

这会绕过 registry。

### 当前最新决定

Guide **暂时完全不做内容改动**。

规则：

```text
保留当前占位
不生成攻略图
不抓第三方内容
不自动填充
不新增素材
等待用户以后上传
```

同时合并前应修：

```text
registry 未登记
→ 不发送裸目录图片
→ 保留 placeholder 文案
```

Guide 框架可以保留。

---

## 3.3 P1 — 单条 CDK cancellation 可能留下 running

批量 CDK 已处理：

```text
CancelledError
→ unknown
→ 不自动重放
```

但单条路径仍需要相同保护。

必须增加：

```python
except asyncio.CancelledError:
    store.finish_run(
        run_key,
        "unknown",
        "兑换中断，结果未确认，请先检查官方历史"
    )
    raise
```

并补 regression test：

```text
单条兑换
→ 请求开始
→ task cancel
→ run status = unknown
→ 后续不能自动重放
```

---

## 3.4 P1 — docs/DEVELOPMENT_PLAN.md 状态过期

当前工作分支已新增/完成很多内容，但主开发文档仍残留夜间开发前的状态。

必须重新同步：

```text
DONE
PARTIAL
RESEARCHABLE
NEEDS_LIVE_EVIDENCE
NEEDS_HUMAN_DECISION
DEFERRED
```

不能继续把已经完成的内容写成 TODO/BLOCKED。

---

## 3.5 P2 — Voice cooldown 应改为 per-user / per-session

当前全局：

```text
self._last_voice_poke
```

会导致：

```text
用户 A 戳 Bot
↓
10 秒内用户 B 也被 cooldown
```

应改成：

```text
(platform, sender/session) -> timestamp
```

至少支持：

```text
用户 A cooldown 不影响用户 B
```

补测试。

---

## 3.6 P2 — CI 临时工作分支 trigger 清理

当前 CI 中包含：

```text
feat/overnight-backlog
```

作为 push trigger。

合并前建议移除临时工作分支，只保留正式长期分支。

---

# 4. Agent 最大自治权限

Agent 可以自主使用：

```text
仓库扫描
git history
branch/PR/issue
GitHub Actions
公开 Web
公开 GitHub
NIKKE 官网
BlaBlaLink 前端
Level Infinite / PlayerInfinite
公开 JS bundle
公开 source map
公开 API
公开 static JSON
公开 CDN
AstrBot 文档
OneBot 文档
aiocqhttp 文档
Spine 官方文档
开源实现
```

Agent 可以自主创建：

```text
scripts/diagnose_*.py
scripts/capture_*.py
scripts/import_*.py
scripts/inspect_*.py
scripts/benchmark_*.py
scripts/verify_*.py
scripts/migrate_*.py
```

Agent 可以自主：

```text
安装隔离开发依赖
构造 fixture
构造 synthetic data
写 mock
写 parser
写 adapter
局部重构
补 migration
补缓存
补索引
补 registry
补 benchmark
补 source provenance
更新 README
更新开发计划
更新 evidence
```

---

# 5. Agent 允许的真实环境动作

## 5.1 真实只读

在用户已授权环境中，Agent 可以自行执行：

```text
Profile 查询
Raid 查询
Campaign 查询
Daily 状态查询
CDK 历史查询
公告查询
读取本地绑定账号
读取 x-common
```

条件：

```text
不打印 Cookie
不打印真实 OpenID
不打印 game_uid
不打印 QQ
不上传数据库
不提交真实敏感响应
```

允许提交：

```text
脱敏 shape fixture
synthetic semantic fixture
hash
布尔结果
计数
字段列表
匿名 ID
```

---

## 5.2 受控真实写实验

为了解除 `NEEDS_LIVE_EVIDENCE`，Agent 可以在用户当前“最大自治授权”下进行：

```text
单次点赞
单次浏览
单次普通 Daily 写动作
单次 QQ 测试消息/语音
单次公告测试发送到明确测试会话
```

必须：

```text
before read
↓
write once
↓
after read
```

并且：

```text
不得自动 retry
timeout/network ambiguity
→ UNKNOWN_AFTER_ACTION
```

禁止：

```text
循环写
批量刷任务
大规模群发
大规模点赞/浏览
规避 rate limit
```

---

# 6. Guide 最终决定

Guide 当前状态：

```text
PLACEHOLDER / DEFERRED
```

Agent 暂时不要：

```text
生成攻略图
抓第三方攻略
复制第三方攻略正文
复制第三方排版
替换 placeholder
添加正式攻略内容
```

保留：

```text
GuideRegistry
分页
registry 结构
placeholder 文案
命令框架
测试
```

用户以后上传素材后，再接入。

因此：

```text
Guide 不再列为当前开发重点
Guide 不再列为当前人工任务
Guide 保持现状
```

---

# 7. Spine 最终架构

Spine 不需要用户上传素材。

当前方向明确为：

```text
服务器按需实时/准实时渲染
→ PNG
→ 持久缓存
→ 后续直接复用
```

---

## 7.1 Spine 目标链路

```text
角色卡需要人物图
        ↓
检查 PNG cache
        ↓
┌──────────────┴──────────────┐
│                             │
命中                        未命中
│                             │
直接用缓存              NikkeDbProvider
                              ↓
                    获取 l2d / Spine bundle
                              ↓
                    识别 Spine major.minor
                              ↓
                    Server-side Spine Runtime
                              ↓
                     渲染透明 RGBA PNG
                              ↓
                        自动裁切 bounds
                              ↓
                         persistent cache
                              ↓
                        角色卡后续复用
```

---

## 7.2 第一次请求策略

第一张卡不能无限等待 Spine。

建议：

```text
首次预算 5～8 秒
```

如果：

```text
预算内完成
→ 当前卡直接使用新 PNG
```

如果：

```text
超过预算
→ 当前卡用静态 fallback
→ 后台继续渲染
→ 渲染完成写 cache
→ 下一次直接命中
```

---

## 7.3 Spine cache key

至少包括：

```text
character/resource_id
costume/skin
bundle version
spine major.minor
renderer/runtime version
resource hash/version
```

避免：

```text
换皮肤读旧图
资源升级读旧图
runtime 变化读旧结果
```

---

## 7.4 Spine 并发

建议：

```text
worker = 1～2
queue <= 20
per-key dedup
negative cache
failure cooldown
```

不能：

```text
同一资源 20 个请求
→ 渲染 20 次
```

必须：

```text
single-flight
```

---

## 7.5 Spine Agent 负责

Agent 自行完成：

```text
runtime 候选调查
major.minor 匹配
bundle loader
skel/json
atlas
multi-texture
透明 RGBA
bounds/crop
PNG 输出
cache
queue
dedup
timeout
negative cache
headless Linux
CPU benchmark
RSS benchmark
latency
fallback
CharacterCardRenderer 接线
AssetManager/NikkeDbProvider 接线
shutdown lifecycle
```

---

## 7.6 Spine 用户只负责

只有当真正准备生产采用某 runtime 时：

```text
最终许可证 Yes / No
```

如果 Agent 能给出一个许可明确、用户可接受的方案，用户只做最终确认。

---

# 8. Voice 最终架构

Voice 不需要用户提前上传全部语音素材。

目标：

```text
按需获取源语音
→ 服务端按需转码/编码
→ QQ/Adapter 可发送音频
→ persistent cache
→ Record 发送
```

---

## 8.1 Voice 目标链路

```text
用户戳 Bot / 触发角色语音
        ↓
确定：
character
skin/costume
locale
voice_type
voice_id
        ↓
检查 encoded audio cache
        ↓
┌──────────────────┴──────────────────┐
│                                     │
命中                                未命中
│                                     │
直接 Record 发送               VoiceResourceProvider
                                      ↓
                         voice_map / GET_VOICE_URL
                                      ↓
                              获取原始 voice asset
                                      ↓
                           校验格式/大小/时长/hash
                                      ↓
                                source cache
                                      ↓
                         服务器转码到 adapter 可接受格式
                                      ↓
                                encoded cache
                                      ↓
                                 Record 发送
```

---

## 8.2 Voice 不应该提前批量打包进 GitHub

仓库里保留：

```text
provider
resolver
mapping parser
cache logic
transcode logic
tests
```

不要把：

```text
大量官方原始语音
```

直接提交仓库。

运行时：

```text
需要哪个
→ 获取哪个
→ 缓存哪个
```

---

## 8.3 Voice 两层缓存

推荐：

```text
data/nikke/voice_cache/
  source/
  encoded/
```

`source/`：

```text
原始下载资源
```

`encoded/`：

```text
QQ/Adapter 最终可发格式
```

好处：

```text
以后编码参数变更
→ 只重建 encoded
→ 不用重新下载源素材
```

---

## 8.4 Voice cache key

至少包括：

```text
resource_id / character
costume/skin
locale
voice_id
source hash/version
target adapter
encoding profile
encoder version
```

---

## 8.5 QQ 音频格式不能硬编码猜

Agent 必须根据实际部署：

```text
AstrBot
aiocqhttp
OneBot adapter
Record.fromFileSystem
```

确定最终发送格式。

优先：

```text
如果 adapter 能接受 WAV/OGG/MP3 并自己处理
→ 插件不重复转 Silk
```

只有实际 adapter 明确需要：

```text
Silk
```

才增加对应编码。

不能：

```text
因为 QQ 常见 Silk
→ 就把 Silk 写死成项目合同
```

---

## 8.6 Voice 首次触发预算

Voice 转码通常比 Spine 快。

建议：

```text
下载 + 转码预算 3～5 秒
```

如果完成：

```text
本次直接发语音
```

如果超时：

```text
本次发文本 fallback
后台继续
下次直接命中 cache
```

---

## 8.7 Voice 并发

必须：

```text
per-key dedup
single-flight
bounded concurrency
timeout
negative cache
failure cooldown
```

---

## 8.8 Voice Agent 负责

Agent 自行完成：

```text
voice_map 解析
GET_VOICE_URL 解析
character → locale → skin → voice mapping
source fetch
source cache
format sniffing
duration guard
size guard
hash
transcode
encoded cache
adapter capability detection
Record sender
Poke listener
per-user cooldown
text fallback
mock tests
真实测试会话验证
```

---

## 8.9 Voice 用户只负责

如果 Agent 无法直接访问真实 QQ Bot 环境：

```text
用户最后戳一次 Bot
确认是否真的收到/播放语音
```

如果以后准备：

```text
把官方/第三方原始语音直接公开分发
```

才需要单独确认素材分发边界。

---

# 9. Raid 后续任务

Agent 应尽量自行完成：

```text
Raid current round selector
完整 response scope
my identity
member_id ↔ openid
timestamp/order
remaining attacks
历史赛季
排名
我的
成员
攻击历史
```

方法允许：

```text
公开前端
真实只读 API
fixture
只读 diagnostic
Git 历史
公开 GitHub
静态资源
对比测试
```

如果真实账号数据是唯一剩余缺口：

```text
Agent 先写一个只读 diagnostic
```

用户只运行一次命令。

---

# 10. Daily 后续任务

## 10.1 已完成原则

签到写安全：

```text
写一次
→ 只读复核
→ 不确认则 UNKNOWN_AFTER_ACTION
→ 不自动重发
```

必须继续保持。

---

## 10.2 Like / Browse

Agent 应自行：

```text
找 endpoint
找 payload
找 status query
写 client
写 parser
写 mock
写 fixture
写 before/after diagnostic
做单次受控真实实验
```

只有：

```text
before
→ write once
→ after
```

能证明 Daily 状态变化后，才正式启用。

---

# 11. Announcement 后续任务

当前正式 InformationFeeds 只读来源已经找到并接入。

后续 Agent 继续：

```text
adapter 稳定性
locale
pagination
category
fallback
deadline parser
delivery cleanup
push retry state cleanup
多语言真实验证
```

公告真实推送：

```text
默认关闭
明确订阅
成功后才记 delivered
失败不记 delivered
```

继续保持。

---

# 12. Campaign 后续任务

当前大量 stage mapping 已通过静态表导入。

必须继续遵守：

```text
不计算 stage_id
不猜连续编号
只接受明确来源
```

后续：

```text
完善 source provenance
扩展更多模式只接受真实标签
完善 richer lineup renderer
```

---

# 13. CDK 最终策略

Agent 自行采用保守默认：

```text
max_items <= 10
delay >= 1.0 sec
serial only
rate limit → stop
CookieExpired → stop
RESULT_UNKNOWN → no automatic replay
```

Agent 可以根据真实频控证据后续自行调整。

禁止：

```text
自动拿有价值真实 CDK 做批量实验
```

---

# 14. Profile 后续任务

Agent 继续完成：

```text
structured Recycle Research
Collection/Memorial 结构
BASIC
CAMPAIGN
OUTPOST
ROSTER
COLLECTION
RESEARCH
MORE
```

仍然：

```text
不对 /妮姬 我的 做每个角色 CharacterDetails
```

避免大规模 API 请求。

---

# 15. Character Card 后续任务

Agent 继续：

```text
HP/ATK/DEF 公式
所有 OL 属性最终验证
Favorite Item registry
Cube registry
Equipment registry
Costume chain
portrait/skin chain
legacy roster UI 升级
```

要求：

```text
只用可验证公式/静态表
不从 combat 反推
未知字段不猜
```

---

# 16. 人工任务压缩后的最终边界

采用最大自治后，用户本人原则上只剩：

## 16.1 最终许可证 / 法律决定

例如：

```text
是否正式采用某 Spine runtime
是否公开分发某官方/第三方素材
```

Agent 负责：

```text
研究
总结
风险
推荐
```

用户只：

```text
Yes / No
```

---

## 16.2 真实设备最后一步

如果 Agent 无法访问：

```text
真实 QQ 客户端
```

用户只需要：

```text
戳一下 Bot
确认语音实际播放
```

---

## 16.3 不可逆/有价值资源

例如：

```text
真实有价值 CDK
购买许可证
付费服务
账号安全设置
```

需要明确确认。

---

## 16.4 生产 secret/database 备份

必须保证：

```text
nikke.sqlite3 有备份
secret.key 有备份
```

不能：

```text
提交 Git
上传公开位置
发给 Agent
```

如果 Agent 本身有服务器权限，可以帮做备份，但只能放在用户授权的私有位置。

---

# 17. 用户不再需要做的事情

以下全部默认交给 Agent：

```text
找 API
找 endpoint
分析 JS
分析 source map
找 static JSON
找 resource mapping
写 diagnostic
写 capture
写 import
写 fixture
写 mock
写 parser
写 adapter
生成测试 WAV
做 Spine benchmark
处理 voice source cache
处理 QQ audio cache
判断 CDK 默认 delay
扫描 secret 泄漏
检查 Git
检查日志
检查 CI
更新 README
更新 docs
更新 evidence
做局部重构
补测试
```

---

# 18. Agent “不要问我”规则

下面这些 Agent 自己决定：

```text
函数名
文件名
DTO 拆分
测试结构
fixture 命名
cache 目录
timeout 默认值
并发保守值
日志格式
错误枚举
mock 方式
内部 API
局部重构
CI 细节
```

只有这些才问：

```text
不可逆外部副作用
消费有价值资源
许可证/法律最终采用
真实设备物理确认
重大产品方向冲突
```

---

# 19. 推荐执行顺序

```text
Phase 1
Review Fix
- Raid sanitizer
- Guide fallback
- 单条 CDK cancellation
- Voice per-user cooldown
- CI 临时 trigger
- DEVELOPMENT_PLAN 同步

Phase 2
全量测试 + CI

Phase 3
Raid Phase 2
- identity
- ranking
- my
- season
- history
- diagnostics

Phase 4
Daily Like/Browse
- endpoint
- contract
- single controlled experiment

Phase 5
Spine Real Runtime
- runtime
- bundle
- headless
- render
- cache
- card wiring

Phase 6
Voice Dynamic Pipeline
- voice_map
- source fetch
- source cache
- transcode
- QQ cache
- Record
- poke

Phase 7
Profile
- Research
- Collection/Memorial

Phase 8
Announcement
- cleanup
- locale
- delivery state

Phase 9
Character Card Registries / Stats

Phase 10
Campaign refinement

Phase 11
Guide
- 保持 placeholder
- 等用户后续上传
```

---

# 20. 每个 Phase 的测试纪律

每个独立阶段：

```bash
python -m compileall -q .
pytest -q
git diff --check
```

如适用：

```bash
node --test tests/extension.test.cjs
```

只有全部通过：

```text
才 commit
```

一个任务失败：

```text
不提交破损代码
回到上一绿色状态
记录原因
继续其它任务
```

---

# 21. 合并前 Definition of Done

至少满足：

```text
[ ] Raid sanitizer 不可逆
[ ] Guide 未登记素材不再 fallback 直接发送
[ ] 单条 CDK CancelledError → unknown
[ ] Voice cooldown per-user/per-session
[ ] CI 删除临时工作分支 trigger
[ ] docs/DEVELOPMENT_PLAN.md 与当前 HEAD 同步
[ ] compileall 通过
[ ] pytest 全绿
[ ] Node extension test 通过
[ ] git diff --check 通过
[ ] GitHub Actions 全绿
```

---

# 22. 最大自治 Coding Agent Prompt

```text
你拥有本项目的最大工程自治权限。

仓库：
September6969/astrbot_plugin_nikke

目标：
尽可能独立完成当前审核修复和后续全部可安全推进的开发工作。

首先完成 Review Fix：

1. 修 Raid semantic sanitizer：
   - 不保留精确伤害比例
   - 不可逆
   - 保留 identity/tie/order/aggregate 语义
   - 补测试

2. 修 Guide：
   - 保留 placeholder
   - 不生成/不抓取攻略内容
   - 删除未登记裸目录 fallback
   - registry 未登记则不发送正式素材

3. 修单条 CDK cancellation：
   - CancelledError → unknown
   - 不自动 replay
   - 补 regression test

4. Voice cooldown 改成 per-user / per-session
   - 用户之间互不影响
   - 补测试

5. CI 清理 feat/overnight-backlog 临时 trigger

6. 同步 docs/DEVELOPMENT_PLAN.md 到当前 HEAD

然后继续最大化推进：

Raid：
- 当前 round selector
- scope
- identity
- ranking
- my
- member mapping
- season history
- attack history
- diagnostic

Daily：
- Like/Browse endpoint
- status
- client
- parser
- fixture
- before/write once/after controlled experiment
- 不自动 retry
- ambiguity → UNKNOWN_AFTER_ACTION

Spine：
目标不是用户上传素材。
目标是：
NikkeDbProvider
→ 获取 Spine bundle
→ major.minor
→ server-side runtime
→ RGBA PNG
→ crop
→ persistent cache
→ CharacterCardRenderer
第一次允许 5~8 秒预算，超时 fallback，后台继续。
必须有：
per-key dedup
queue
timeout
negative cache
headless Linux benchmark

Voice：
目标不是用户上传完整语音库。
目标是：
character/skin/locale/voice_id
→ voice_map / GET_VOICE_URL
→ fetch source
→ source cache
→ 按实际 AstrBot/OneBot adapter 能力转码
→ encoded QQ audio cache
→ Record
→ Poke
第一次预算 3~5 秒，超时文本 fallback。
不要硬编码 Silk，先验证 adapter 能力。
必须有：
per-key dedup
bounded concurrency
timeout
negative cache
per-user cooldown

Guide：
保持 placeholder。
不要生成攻略图。
等待用户以后上传。

CDK：
保守默认：
max_items <= 10
delay >= 1s
serial
rate limit stop
CookieExpired stop
RESULT_UNKNOWN no replay

允许你主动：
- 扫 repo
- git history
- PR/branch/CI
- 搜公开 Web/GitHub
- 分析 NIKKE/BlaBlaLink 前端 JS/source map/API/static JSON/CDN
- 查官方文档
- 写 diagnostic/capture/import/benchmark/verify 工具
- 构造 synthetic fixture
- 写 mock/property/fuzz tests
- 安装隔离开发依赖
- 做真实只读诊断
- 做一次性受控低风险实验

不要因为 BLOCKED 停止。
先执行 UNBLOCK RESEARCH。

真实写实验必须：
read before
→ write exactly once
→ read after
禁止自动 retry。
ambiguous → UNKNOWN_AFTER_ACTION。

硬禁止：
- 泄露 Cookie/OpenID/game_uid/QQ/secret.key/token
- 绕过认证/验证码/访问控制
- 自动消费真实有价值 CDK
- 批量真实兑换
- 大规模真实群发/点赞/浏览
- 购买许可证
- 替用户接受法律条款
- force push
- 自动 merge main

普通工程判断不要问用户。
只有：
许可证最终 Yes/No
不可逆资源
真实设备最后一步
重大产品方向冲突
才需要用户。

每个阶段执行：
python -m compileall -q .
pytest -q
git diff --check
node --test tests/extension.test.cjs（如适用）

测试全绿后独立 commit。

一个任务失败不能停止整个计划。

最终报告必须包含：
- 起始 main SHA
- 最终 branch / HEAD
- commits
- 完成功能
- 修复项
- 新解除 BLOCKED
- DONE
- PARTIAL
- NEEDS_LIVE_EVIDENCE
- NEEDS_HUMAN_DECISION
- HARD_BLOCKED
- tests
- CI
- 仍需用户做的最少动作
```

---

# 23. 最终状态模型

以后统一使用：

```text
DONE
PARTIAL
RESEARCHABLE
NEEDS_LIVE_EVIDENCE
NEEDS_HUMAN_DECISION
DEFERRED
HARD_BLOCKED
CANCELLED
```

其中：

```text
RESEARCHABLE
```

不能留给用户。

Agent 必须先研究。

---

# 24. 最终资源策略总结

```text
Spine
→ 动态资源
→ 服务器按需实时/准实时渲染
→ PNG cache
→ 角色卡复用

Voice
→ 动态资源
→ 服务器按需获取
→ 转码/编码为 QQ/Adapter 可发送格式
→ Audio cache
→ Record 复用

Guide
→ 保留 placeholder
→ 当前不做
→ 等用户后续上传
```

---

# 25. 最终目标

目标不是让用户成为项目测试工程师。

最终应尽量达到：

```text
Agent：
研究
编码
测试
抓公开数据
分析协议
写工具
跑诊断
做 benchmark
做缓存
做动态资源链
更新文档
维护 CI

用户：
最终授权
最终许可证决定
真实设备最后一步
不可逆资源确认
```

只要某项工作可以通过 Agent 自己研究、写代码、跑测试、访问公开资料、访问已授权只读环境、做安全的受控实验完成：

```text
默认由 Agent 完成。
```
