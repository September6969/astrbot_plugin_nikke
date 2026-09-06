# 夜间开发阶段报告

## 基线与边界

- 起始 origin/main：`deeef6277f09a42918d71b44f49170398a05558b`。
- 工作分支：`feat/overnight-backlog`，独立 worktree。
- 完整开发计划由用户附件原样放入 docs/DEVELOPMENT_PLAN.md；优先执行 24F 的研究与连续推进策略。
- 没有修改 main/master、force push、merge 或创建 PR。
- 没有读取真实凭据、执行真实账号写操作或 QQ 消息发送；公开官网匿名读取已验证。
- 这是可审核的阶段交付，不是全计划完成验收；仍有后续离线开发。
- 本文所在版本的最终提交用 `git rev-parse HEAD` 查看，提交清单用下方命令完整重现。

## 完成内容

1. 当前合同：Raid HP 钳制、Campaign 未知业务异常上抛、抓取工具完整身份透传及固定载荷。
2. 证据工具：跨响应一致匿名身份、同比例整数伤害；读取失败不生成成功 fixture，多账号不隐式选择。
3. Profile：研究/收藏结构化 None/空/零值保真、独立展示区，9 类研究名称与官网枚举交叉确认。
4. Raid：当前响应伤害排名、精确阵容校验、受控未知状态；历史赛季只读客户端合同。
5. 公告：正式 InformationFeeds 主源及旧源回退、全文 HTML 提取、分页上限、缓存和独立版本。
6. Daily：模糊写结果只读复核，不盲目重复写；无法确认时持久化 unknown。
7. CDK：批量逐码结果持久化，已成功/终态结果复用，未知结果不由批量隐式重放。
8. 生命周期：动态后台任务统一登记、错误回收，关闭时取消并等待任务。
9. Voice：默认关闭的 OneBot 自身 poke 监听，本地授权索引、偏好、缓存、超时转换、mock sender。
10. Guide：带来源/许可/版本的本地 registry、路径边界、排序与分页 API，命令读取索引。
11. Campaign：静态映射由 88 项扩展到 3572 项；可复现导入器与来源元数据。
12. Tower：7350 层静态 registry 和免绑定查询命令。
13. 单次只读诊断：默认离线；显式开启才读账号，只输出固定状态、布尔值和计数。
14. 工程：README/帮助同步，CI 增加独立 Node 扩展测试和工作分支 push 触发。
15. 继续阶段：公告目标订阅、当前会话管理员命令、默认关闭的调度、24/6/1 小时提醒、失败退避及 PushRecord 成功持久化。
16. 继续阶段：攻略命令分页；Spine 无运行时 atlas/JSON 预检查；英文月份日期和明确日期范围校验。

## 新解除的 BLOCKED

| 项目 | 证据与进展 |
| --- | --- |
| 正式公告源 | 官网配置/SDK/API 交叉确认，真实匿名适配器拿到 1 条非空全文；生产查询使用正式源 |
| 更多关卡 ID | 官网公开表匿名 HTTP 200；3572 个明确标签直接映射，无 ID 公式 |
| 研究名称 | 官网 QueryKeys + RecycleResearchStatTable + tid 消费代码一致，已用于 Profile |
| 塔层资料 | 官网表 HTTP 200；7350 层本地查询 |
| 历史 Raid 请求合同 | 官网 JS 明确端点和 payload；已建客户端与 mock 测试，响应仍待真实证据 |
| 部分早期静态数据 | 好感等级、珍藏品稀有度、单魔方属性、角色目录均可匿名读取；完整服务尚待开发 |

详细来源与证据等级见 [研究记录](evidence/overnight.md)。不把人工测试称作真实接口验收。

## NEEDS_LIVE_EVIDENCE

- Raid 当前账号与攻击身份的对应、成员 join、多轮选择、分页/赛季覆盖、最近一刀精确时间、已用/剩余次数。
- 历史赛季响应结构；新增方法未用真实账号调用。
- CDK 历史生产包体及完整错误分布。
- Daily 真实状态语义；只读诊断不能证明点赞/浏览写入后的完成条件。
- QQ/NapCat 实际语音播放；目前只有 mock sender，没有实际发送。
- CMS 非英文站与更多栏目尚未联调；英文 NEWS 已匿名验证，不能再整体标记为源不可用。
- 真实公告发送尚未验收；当前发送器仅 mock，API 返回与最终平台送达仍需区分。
- 092b88f 的远端 Actions 已验证 Linux Python 3.10/3.11/3.12 和 Node 全绿；后续提交以对应 Actions 为准。

## NEEDS_HUMAN_DECISION

- Spine 有效运行时许可及 Linux 部署资源预算；未安装运行时或进行真实 PNG spike。
- 有权使用的语音和攻略素材。索引默认为空，未复制攻略站正文或下载游戏音频。
- 公告目标语言/栏目和自动推送启用策略（当前英文查询，推送开关默认关闭）。

## HARD_BLOCKED

当前没有证据足以判定某项在技术上永久不可实现。许可不足不是可绕过的技术障碍，归入上方决策项。

## 仍可继续的离线工作（不伪装成 live blocker）

- 公告最近 14 天深度重扫、栏目筛选、多事件分段解析。订阅/调度/时窗已实现；发送成功后进程崩溃而尚未持久化的窗口仍可能重复，不能宣称 exactly-once。
- Advise/Cube/Collection/Skill 完整静态 registry、具体查询服务和数据更新工具；已有可达性研究未等同产品完成。
- Guide 目录交互、过期版本治理；命令分页已实现。
- CDK 单条与批量的持久化编排仍可进一步抽取共同入口，现有 store key 和互斥范围已经统一。
- Spine 二进制版本解析、真实渲染 spike 和 Linux 性能基准尚未实现；atlas/JSON 无运行时预检查已实现。
- 诊断目前不抓成员列表/历史赛季；不能一次性填满所有身份、分页与写后状态证据。

## 测试

本地 Python 3.10：228 passed、2 warnings、31 subtests passed；Node：3 passed。
两个警告来自 faiss 的 NumPy 私有命名空间和 AstrBot register 装饰器弃用。
每个功能阶段执行全量回归后单独提交。公开 CMS 匿名实测独立于 mock 测试。

在仓库目录执行：

```powershell
$env:PYTHONPATH = (Get-Location).Path + '/..'
python -m compileall -q .
pytest -q
node --test tests/extension.test.cjs
git diff --check
```

本机实际复用 `E:/DevCache/nikke-test-venv/Scripts/python.exe` 与同环境 pytest，未额外安装运行时。

## 明天最少操作

不需要提供或上传任何凭据。若要补充真实只读证据，在自己的部署环境/单账号数据目录运行一次：

```powershell
$env:PYTHONPATH = (Get-Location).Path + '/..'
python -m astrbot_plugin_nikke.scripts.diagnose_readonly --live-readonly --data-dir '<现有单账号 nikke 数据目录>'
```

只回传命令的脱敏 JSON 输出，不上传数据库、secret.key、Cookie 或原始 bundle。
若目录有多个账号，工具会拒绝隐式选择；无需为了诊断删除其它账号，应先完善显式选择支持。
此命令不会兑换 CDK、点赞、浏览计数上报、签到或发 QQ 语音。
默认完全离线冒烟：`python -m astrbot_plugin_nikke.scripts.diagnose_readonly`。

## 提交清单

```text
8afacc4 fix: align raid capture and remaining API contracts
b964f18 feat: preserve anonymous raid evidence relationships
ee7b42e fix: separate announcement content and deadline versions
7f2aa1f fix: stop ambiguous daily writes after read-only verification
2921ed8 feat: preserve structured profile research and collection counts
a40cf8f fix: track and drain plugin background tasks
646b8f3 feat: add current-response union raid damage ranking
76c85c4 fix: persist per-code batch redemption outcomes
06ae0b7 feat: add versioned local guide registry with provenance
149682a feat: consolidate privacy-safe read-only diagnostics
6ef7ad2 feat: add evidenced read-only raid season client
33baf69 feat: add opt-in local voice playback and poke filtering
ee3628c feat: integrate verified public InformationFeeds announcement source
4406ac6 feat: expand campaign stage IDs from verified public table
fe0cea0 feat: resolve profile research types from official static keys
682d312 fix: bound voice files and publish cache atomically
d8c4f30 test: preserve public CMS evidence and locale contracts
692b690 feat: expose public tower floor reference without account access
26e9e10 test: enforce safe raid capture contracts and failure handling
092b88f docs: record overnight delivery and extend branch CI coverage
104238e feat: persist announcement subscriptions and delivery planning
9b618c4 feat: wire opt-in announcement subscriptions and scheduler
a6f0265 feat: expose bounded guide pagination in commands
5ed857a feat: add runtime-free Spine bundle preflight inspection
2404fd6 fix: validate deadline ranges and support explicit English dates
73440dd fix: persist announcement delivery retry backoff
```

最后的报告/README/CI 提交包含本文自身；完整含 SHA 的列表：

```text
git log --reverse --format="%H %s" deeef6277f09a42918d71b44f49170398a05558b..HEAD
```
