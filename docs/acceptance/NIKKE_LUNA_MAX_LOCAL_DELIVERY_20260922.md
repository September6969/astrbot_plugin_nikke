# NIKKE Luna Max 本地交付与后续运行门槛

> 历史快照说明：本记录下方的 `LOCAL_IMPLEMENTATION_COMPLETE` 只对应旧 `plan_luna_max` 运行及其修复后 checkpoint，不代表 `full_repository_refactor_v2` 已完成。R21（2026-09-23）复核确认 Profile 命令现已唯一走 `ProfileCommandHandler` → `ProfileApplication`；`profile_application_enabled` 不存在于当前配置或入口代码，兼容回退路径已收敛。旧条目中“默认关闭开关/保留回退”的描述不适用于当前工作树。

## 当前结论

当前状态：`LOCAL_IMPLEMENTATION_COMPLETE`（审核后 A74 重工及最终本地回归已完成）。

这表示计划中所有本地任务已经完成或以证据保留，当前隔离工作树通过适用的本地回归，并且遗留的外部门槛已经单独列出。它不表示 `RELEASE_READY`、`DEPLOYED` 或 `MIGRATION_COMPLETE`。

本报告对应：

- 计划：`planning/plan_luna_max.md`，hash `AAA9EBE727CEBAAC2D66BA4D582CA4B43F66DC130C7E1BCC466514D4D510C612`。
- 任务索引：`planning/plan_luna_max_tasks.json`，hash `014E6DEF38B56EB8B8EC326E7B4E1B876234FEFA729ED0584D83732258AD02F7`。
- 基线：`92951b49efbf4205453391f6331cc57b1e807803`。
- 隔离工作树：`E:/DevCache/nikke-luna-max-runs/20260922T101830Z-2356cfe3/work/astrbot_plugin_nikke`。
- 本次运行台账：`E:/DevCache/nikke-luna-max-runs/20260922T101830Z-2356cfe3`。

计划文档中的实施规则和验收标准已用于本地工作；其中关于 push、PR、合并、真实发送、部署和退役的描述不被当作授权。用户请求授权了本地实现，未授权这些外部副作用。

## 本地交付内容

### 已完成的实现与保护

- Profile：补齐命令级合同、application 边界、T2I payload 边界和实际入口路由；新链路受默认关闭的 `profile_application_enabled` 保护，保留兼容入口和回退路径。
- 生命周期与副作用：补齐公告取消/进程退出未知窗口合同，保留 Daily/CDK 的发送前意图和 `UNKNOWN_AFTER_ACTION` 语义；后台任务统一登记并在关闭时等待清理。
- 公告：发送前持久化 `DISPATCH_INTENT`，明确失败才受控重试，发送异常/取消/游标提交失败进入 `UNKNOWN_AFTER_ACTION` 并禁止自动重发；仍未宣称跨进程 exactly-once。
- Voice/资源/Spine：保留身份精确匹配、fail-closed 资源选择、缓存/取消/编码清理和 Python/Node 合同；当前 voice map 为 schema v3、2106 条映射，但真实 QQ 播放和授权仍待现场证据。
- 入口/配置/容器：主入口、兼容别名、权限、默认关闭写开关、版本注册和唯一容器所有者已核对。
- 文档事实：活跃文档中的 voice map 统计和外部证据边界已收敛；历史 evidence 文档保留为历史记录，不冒充当前现场状态。

### 回归与证据

- A74 审核后完整行为回归（单列并排除既存架构门禁）：`1199 passed, 2 skipped, 658 subtests passed`。
- 架构门禁单独复核：`6 failed, 4 passed`；失败仍为已登记的热点大小、main 处理器、依赖方向、AssetManager 所有者、空转发模块与 Calendar 导入环，不把它们描述为通过。
- A74 投递窄测：`12 passed`；A74 影响组：`243 passed, 85 subtests passed`。
- presentation 合同：`68 passed, 2 skipped`；Node 扩展/Spine 表面：`10 passed`。
- Python 3.14 的 `compileall`、包导入、`git diff --check` 均通过；Python 3.10 `compileall` 通过。Node `10 passed`。
- Python 3.10/3.13 环境未安装 pytest；上述 pytest 结果来自 Python 3.14，不替代 CI 支持矩阵。
- 当前正式源码指纹见 `E:/DevCache/nikke-luna-max-runs/20260922T101830Z-2356cfe3/source_manifest.json` 和 `state.json.source_manifest`，覆盖基线至当前 checkpoint 的源码差异。
- Voice registry、缓存音频校验、账号列表、角色名 map 的固定输入 before/after median/P95 已记录；关闭耗时和 `tracemalloc` 峰值已记录。
- 详细证据：[F90_final_local_verification.md](../../../../evidence/F90_final_local_verification.md)。

### 当前 patch/提交状态

- 当前本地 checkpoint：`116a50957941c76733ecb9b96b6ec647814217ad`（公告硬退出后孤儿发送意图恢复）；工作树干净。该提交仅在隔离分支本地存在。
- 没有修改 `E:/NIKKE_Luna_Max_Project/source/astrbot_plugin_nikke` 主工作区。
- 没有 push、创建 PR、merge、部署、修改远端 ruleset、读取真实账号、写真实数据库、发送真实 QQ 消息或触发真实 CDK/签到动作。
- 审核后正式 `source_manifest.json` 已重新生成并逐文件自校验；不要用旧 patch hash `b7dcbebd...` 或旧 manifest `7604f27c...` 代表当前源码。
- 没有 push、创建 PR、merge、部署、修改远端 ruleset、读取真实账号、写真实数据库、发送真实 QQ 消息或触发真实 CDK/签到动作。
- 运行模型与推理强度没有宿主可独立核验的标识；本报告不把计划中的 `gpt-5.6-luna/max` 写成已证实执行事实。

## 架构决策与兼容边界

1. `core/container.py` 保持唯一 `NikkeStore`、客户端、Web、Voice、Announcement、Calendar、Daily 和渲染资源装配点；不增加第二套 store/client/scheduler。
2. 新的 Profile application/payload 只抽取已验证的边界，不把 AstrBot、HTTP、SQLite 或 renderer 细节倒灌进 application；旧公开 shim 暂不删除。
3. 写入动作继续采用明确成功、拒绝、未知三态；发送可能已经发生时不凭超时自动重放。
4. 公告自动推送保留单实例限制；若要多实例部署，必须先补共享协调或明确的部署约束，不能把进程内锁当作跨实例方案。
5. 角色/服装/资源映射未知、损坏或没有官方分母证据时 fail-closed；不猜测相邻 ID、后缀或资源所有者。
6. V1 兼容路径、回退渲染和旧公开导入在真实稳定观察、消费者盘点和退役授权前继续保留。

## 回退与恢复

- 本次没有部署，因此不存在需要执行的生产回退；真实数据库、密钥、Cookie、token 和 QQ 状态均未触碰。
- 若本地审查拒绝 patch：保留运行台账和日志，可另从基线创建新的隔离工作树进行对照；不要对主工作区执行强制 reset、清理或覆盖。
- 当前 checkpoint 尚未推送或提交 PR。若维护者之后要求建立 PR/触发 G01，应先复核当前 `state.json`、manifest、自检日志及目标提交，再单独执行获准的外部动作。
- 若外部部署后需要回退：必须使用部署前保存的应用 SHA、`nikke.sqlite3` 与 `secret.key` 成对备份及目标环境的健康/日志证据；写入未知状态不得通过重新运行 V1 动作来“补偿”。
- 任何删除 V1、删除兼容 shim、删除旧资源或清理运行台账的动作，都需要单独的人工范围确认，不属于本地实现完成的默认步骤。

## 外部门槛清单

| 门槛 | 当前状态 | 最小执行动作与输入 | 完成证据 |
| --- | --- | --- | --- |
| G01 当前提交的完整 CI | `NEEDS_LIVE_EVIDENCE` | 在明确提交/PR授权后，以当前提交运行 Python 3.10–3.13、Node 22 和 Spine worker/Docker 检查；当前本地 Node 为 24.15.0，Docker 不可用 | 当前提交对应的 CI 全部 required checks 和可读日志 |
| G02 真实读取与视觉/音频验收 | `NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION` | 提供具体测试账号、数据范围、QQ/NapCat/AstrBot 会话和资源/音频许可；按功能抽样记录真实数据、图像和听检结果 | 脱敏的账号范围、样本、图像/音频结论和许可边界 |
| G03 部署及逐切片默认启用 | `NEEDS_HUMAN_DECISION` | 在 G01/G02 通过后，明确 merge/deploy、备份、回滚窗口、目标 SHA 和逐项启用开关；先做只读健康/版本检查 | 部署 SHA、成对备份/恢复检查、`/healthz`、唯一调度所有者和回退证据 |
| G04 稳定观察及旧实现退役 | `NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION` | 部署后至少观察 7 天和两个相关调度周期（取较长者），检查真实流量、低频边界、日志和全部旧消费者，再取得删除范围授权 | 观察窗口数据、异常/未知写入报告、消费者清单和退役批准 |

以上门槛不会由本地合成 fixture、静态测试或本报告自动满足。

## 集中决策项

1. 是否接受当前隔离工作树作为待审 patch，并单独授权 checkpoint commit。
2. 是否授权创建 PR/触发 G01 CI；本次执行未进行该动作。
3. 是否提供 G02 所需的真实账号、QQ 会话、资产/音频权限和抽样范围。
4. G01/G02 通过后，是否授权 G03 部署；G04 完成前不删除 V1 或兼容 shim。
