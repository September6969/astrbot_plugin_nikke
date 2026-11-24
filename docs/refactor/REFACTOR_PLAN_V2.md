# NIKKE AstrBot 插件系统性重构整改计划（V2）

> **仓库地址**：`https://github.com/September6969/astrbot_plugin_nikke`
> **规划方案**：方案 B（渐进式系统重构）
> **状态**：待项目所有者决策与批准（尚未进入代码实施）

> **实施说明（PR-6C 补记，2026-11-22）**：本计划已按 PR-0 → PR-6C 实施，正文保留批准时的原文，不再改写；当前状态以 [FINAL_DELIVERY.md](FINAL_DELIVERY.md) 的「REFACTOR V2 交付记录」与代码为准。正文中已过期的数字：
> - 数据库为 `SCHEMA_VERSION = 3`（自 `ab610f5` 起即为 3；红线 3 与 §4 写作 2 与代码不符，`V2_PHASE0_BASELINE.md` 已记录；V2 未改动 schema）。
> - 热点余量：`main.py` 现 252 行、门槛已由 700 收紧为 300；`command_runtime.py` 现 314/400（PR-2 后为 318）。
> - PR-6C 的遗留方法区间实为 `main.py:249-497`（PR-2 新增 `nikke_hash_prefix` 后下移），而非 229-478；「36 个」即 35 个未注册公开方法加 `_dispatch_account_command`，涉及约 22 个测试文件、52 个测试函数（另有 8 个 AST 守卫），而非「24 组」。
> - 「8 条既有跨层边」已全部清零，`CROSS_LAYER_BASELINE_ALLOWLIST` 为空集。
> - PR-6A 所述 `features/voice/feedback.py`「0 引用」不准确（有 2 个测试引用），已先改测试再删除。
> - PR-6C 删除的 `scripts/` 根兼容壳为 79 个，保留运维入口 `backup_nikke_data`、`upgrade_preflight`、`cleanup_cache`、`diagnose_readonly` 与 `update_nikke_db.sh`。

---

## 1. 文档说明与审计基线

本文档是面向维护者与 PR 提交者的可执行整改移交计划，整合了基于最新主分支的增量复核结果、全量已复核问题清单、分阶段小 PR 实施路线、回归保护门禁及待拍板事项。

### 1.1 权威基线快照

| 基线项 | 实测值 |
| :--- | :--- |
| 权威主分支 HEAD | `origin/main` @ `ab610f5b62b5f3f03e5329bfa8b81c07b989bc75`（PR #128「新增妮姬竞技场排阵与帮助详解」已合入） |
| 对照旧基线 | `ede461f5550c67b33d2251b3025b8e19daef01a5`（PR #127，已淘汰；`ab610f5` 较其新增 61 个文件、+9,162 / -29 行） |
| 架构门禁基线 | `python scripts/audit/architecture_metrics.py --check` 退出码 `0`：648 个 `.py` 文件、267 个生产模块、1,724 条内部导入边、0 个导入循环、0 个既有门禁违规 |
| 热点文件行数余量 | `main.py` 490/700；`adapters/astrbot/command_runtime.py` **389/400（仅余 11 行）**；`core/asset_manager.py` 278/300；`features/calendar/schedule_service.py` 263/450；`features/announcement/service.py` 165/450；`core/container.py` 222/350 |
| 当前未纳入门禁的既有跨层边（8 条） | ① 6 条 `application.commands.{campaign,cdk,character,daily,profile,raid}` → `integrations.blablalink.client`<br>② 1 条 `features.calendar.schedule_service` → `integrations.calendar.blabla_source`<br>③ 1 条 `integrations.spine.prerenderer` → `scripts.spine.inspect_spine_bundle` |
| 前端扩展测试 | `node --test tests/extension.test.cjs` 4 passed / 0 failed |
| 类型检查配置 | `mypy.ini` 覆盖 37 个模块（当前尚未接入 `.github/workflows/ci.yml`） |

### 1.2 测试环境说明（提 PR 前必读）

- `pytest.ini` 配置了 `testpaths = tests` 与 `pythonpath = . ..`，测试统一采用 `from astrbot_plugin_nikke...` 导入包路径。
- 如果本地 worktree 目录名**不是** `astrbot_plugin_nikke`（例如默认随机工作树目录名），直接运行 `pytest` 会因父目录找不到名为 `astrbot_plugin_nikke` 的包而在收集阶段报 193 个 `ModuleNotFoundError`。
- **实测验证**：将 `ab610f5` 置于规范目录名 `astrbot_plugin_nikke` 下执行 `python -m pytest --collect-only -q`，退出码 `0`、0 错误收集 **1,955 项测试**；定向运行竞技场、帮助详解、架构与发布元数据测试组（`test_arena_core.py`、`test_arena_commands.py`、`test_arena_statistics.py`、`test_arena_t2i.py`、`test_help_detail.py`、`test_full_refactor_architecture.py`、`test_release_metadata.py`）全部通过（`128 passed, 27 subtests passed`）。
- **严格禁止**通过在 `conftest.py` 注入 `sys.modules` 别名或修改生产模块相对/绝对导入来掩盖目录名问题；正确做法是在 Phase 0 采用规范工作树命名（`<worktrees>/<branch>/astrbot_plugin_nikke`）或标准可编辑安装配置。

### 1.3 总体定位

PR #103 已建立起较扎实的 `adapters/` → `application/` → `features/` ← `integrations/`、`core/container.py` 单一组合根、`RuntimeCoordinator` 统一生命周期以及 `AnnouncementDelivery` 写后防重放状态机。本方案采用**方案 B（渐进式系统重构）**，保留上述成熟底座，分 **7 个阶段（11 个隔离 PR）** 按优先顺序逐步修复安全、稳定性、交互、性能、UI 与结构债务。

---

## 2. 全局硬性约束与开发红线（PR 提交者必读）

1. **优先级排序**：安全与数据正确性 > 真实运行缺陷 > 用户交互障碍 > 结构维护成本 > 视觉优化 > 非必要增强。
2. **高危 PR 严格隔离**：涉及 `core/storage.py`、凭据加密、账号绑定授权或外部写操作状态机的 PR，**绝不允许**与大规模结构清理、文件搬迁或 UI 改动混在同一个 PR 中提交。
3. **兼容与产品保留底线**：
   - 数据库保持 `SCHEMA_VERSION = 2` 向后兼容，不破坏现有迁移与 `nikke.sqlite3` + `secret.key` 成对备份契约；
   - 保留全部必要的用户命令兼容性，包括 `/妮姬`、`/nikke`、`#妮姬`、`#nikke` 及现有历史平铺别名；
   - 默认保留现有**塔罗**与**语音**功能，不将功能下线作为仓库减重首选方案；
   - 移除 `main.py` 全局注入宿主 `wake_prefix` 时，必须同时提供不污染宿主其他插件的 `#妮姬` / `#nikke` 可靠触发替代方案。
4. **账号换绑硬红线**：
   - 仅在同一 QQ 换绑到**不同游戏身份**（`game_openid` / `game_uid` 变更）时重置继承的自动授权（`auto_daily_enabled`、`daily_scope_v2`）；同游戏账号续绑 Cookie 保持原授权；
   - **严禁**在换绑时删除 `action_runs` 历史记录或清除 `UNKNOWN_AFTER_ACTION` 保护（相关持久化键已按游戏身份隔离）。
5. **社区任务与写操作状态机硬红线**：
   - 严格区分**执行租约**（进程存活锁，可设计保守超时与进程代次安全回收机制）与**动作结果状态**（`UNKNOWN_AFTER_ACTION`）；
   - **`UNKNOWN_AFTER_ACTION` 绝不允许在超时后自动解锁或自动重放**；仅允许在人工核实后通过受权限控制且带审计留痕的显式确认机制解除后续新周期的暂停阻断。
6. **练度查询优化前置要求**：
   - 不预设「必须降为 2 次请求」的僵化目标；须先通过只读探针验证 BlaBlaLink 批量 `GetUserCharacterDetails` 接口在全量或 Top 20 场景下返回的装备槽位、词条及 `state_effects` 是否完整无截断，再决定复用全量批量详情或安全分批方案。
7. **UI 与资产压缩前提**：
   - 统一基础设计规范（色彩语义、字号可读下限、CSP、显式 `canvas` 视口、溢出防护），不强求不同功能卡片统一成单一样式；
   - 所有图片与静态资产压缩/优化必须在保持画质清晰度、角色一致性、Spine 锚点 SHA-256 契约与 AstrBot/NapCat 部署兼容性的前提下进行。
8. **休眠/历史代码清理前提**：
   - 任何已停用的历史代码在提交删除 PR 前，必须逐项完成**静态引用、动态调用（`getattr`/字符串路由）、外部运维脚本依赖及回退用途**四重核查并附清单。
9. **架构门禁渐进收紧节奏**：
   - Phase 0 先将当前 8 条既有跨层边登记为显式基线（allowlist），阻止新增跨层违规（确保 Phase 0 不立即变红）；后续阶段每清零一类跨层边，再从 allowlist 移除并转为硬门禁。

---

## 3. 已复核问题清单索引（`AUD-001` – `AUD-027`）

> **证据等级区分**：「**运行复现**」= 已在 `ab610f5` 隔离快照通过真实模块运行复现结果；「**代码路径证实**」= 经源码逐行追踪确认但未运行真实端到端进程。

| 编号 | 严重度 | 证据等级 | 所属模块与位置 | 问题描述与触发条件 | 核心修复要求 | 需生产验收 |
| :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **AUD-001** | **P0** | 运行复现 | `integrations/web/bind_template.py:665`<br>`integrations/web/service.py:268`<br>`features/account/status.py:6` | 后端 `consume_bind_session` 写入并返回 `status="success"`，但绑定页 JS 仅判断 `'consumed'` / `'bound'`。任意正常绑定完成后页面持续每 2.5s 轮询直至过期误报「链接已过期」。 | 前端轮询同时兼容 `'success'`、`'consumed'`、`'bound'` 并处理 `'failed'` 状态；适当放宽轮询间隔。 | 是 |
| **AUD-002** | **P0** | 运行复现 | `core/storage.py:301-319`<br>`features/daily/runner.py:320-350` | `consume_bind_session` 使用 `ON CONFLICT(qq_id) DO UPDATE` 时未重置 `auto_daily_enabled`（及旧 `daily_scope_v2`）。A 账号开启自动日常后直接重绑至 B 账号，调度器自动对未授权的 B 账号执行签到。 | 仅当 `(game_openid, game_uid)` 变更时重置 `auto_daily_enabled=0` 与旧 `daily_scope_v2`；同账号续绑保留授权；**完整保留 `action_runs` 与 `UNKNOWN_AFTER_ACTION`**。 | 是 |
| **AUD-003** | **P0** | 运行复现 | `core/lifecycle/scheduler.py:76-87,129-133`<br>`core/config.py:81-84`<br>`core/lifecycle/coordinator.py:122-129` | `scheduler.run()` 无异常边界且 `read_schedule_clock` 未捕获 `sqlite3.OperationalError`。实测注入 SQLite 锁错误后协调器状态立刻转为 `FAILED` 并关闭全部服务。 | `scheduler.run()` 捕获非 `CancelledError` 异常并退避重试 + 降频告警，仅向上传播取消信号。 | 否 |
| **AUD-004** | **P1** *(由 P0 下调)* | 代码路径证实 | `integrations/web/service.py` (`BindingWebService._request_ip`, `_requests`)<br>`integrations/web/bind_template.py:674`<br>`deploy/Caddyfile:3` | `ab610f5` 已引入 `web_trusted_proxy_ip` 与分桶限流缓解反代同桶问题；但该配置默认留空时 3 人并发绑定仍共享 60/min 触发 429，且 `_requests` 字典无过期 IP 淘汰。 | 完善代理配置校验与文档；为 `_requests` 增加周期清理与容量上限；降低前端轮询频次。 | 是 |
| **AUD-005** | **P0** | 运行复现 + 代码路径证实 | `features/daily/action_models.py:101-112`<br>`features/daily/actions.py:68-72,195-198` | ① 进程崩溃后 `account_execution_lease` 永远处于 `LEASED`；② 单次社区动作网络超时写入 `UNKNOWN_AFTER_ACTION` 后 `_unresolved` 跨全部历史周期阻塞且无恢复通道。 | 租约与结果状态彻底解耦：租约引入进程标识+保守超时回收；`UNKNOWN_AFTER_ACTION` 严禁自动解锁/重放，仅提供带审计留痕的显式人工确认解除后续周期阻断。 | 是 |
| **AUD-006** | **P0** | 运行复现 + 代码路径证实 | `core/privacy.py:10-60`<br>`application/commands/cdk.py:121-122,149-150` | 实测 `sanitize_log_text` 漏掉多对 Cookie（如 `game_channelid`）、`/bind/<token>`、`/arena/open/<token>`、独立 `Bearer <jwt>` 与带空格引号值；`cdk.py` 两处异常原文直出聊天窗口。 | 重写脱敏正则覆盖完整 Cookie 头、绑定/竞技场链接令牌、JWT 与扩展敏感键；`cdk.py` 全部异常走脱敏友好文案。 | 否 |
| **AUD-007** | **P1** | 运行复现 + 代码路径证实 | `core/storage.py:74-84`<br>`integrations/web/service.py` (`_storage_ready`)<br>`core/health.py` (`collect_runtime_health`) | 设置 `NIKKE_ENCRYPTION_KEY` 环境变量时不生成磁盘 `secret.key`，导致 `/healthz` 永久 503 且健康检查误报「密钥缺失」；磁盘建密钥用 `write_bytes` + `chmod` 存在权限 TOCTOU 与并发覆写风险。 | 用 `os.open(..., O_WRONLY\|O_CREAT\|O_EXCL, 0o600)` 原子创建密钥；新增 `store.has_valid_key()` 统一校验环境变量与文件密钥。 | 是 |
| **AUD-008** | **P1** | 运行复现 | `main.py:206-218`<br>`adapters/astrbot/command_runtime.py` (`nikke`, `_legacy`, `normalize_nikke_prefix`) | `NikkePlugin.nikke` 固定 4 参且仅针对 `日常 任务` 与 `竞技场` 做局部拼接，实测 `/妮姬 兑换 批量 CDK1 CDK2` 丢弃 `CDK2+`、`/妮姬 查询 练度 Red Hood` 截断为 `Red`、空格日程订阅与嵌套 `查询` 参数截断；`#` 前缀解析存在误吞与大小写敏感问题。 | 在 `adapters/astrbot/` 提取统一命令解析器（基于 `event.message_str` 处理空白/换行尾参），同时兼容单测直接位置传参，清理 `_legacy` 4 处死分支。 | 是 |
| **AUD-009** | **P1** | 运行复现 + 代码路径证实 | `integrations/blablalink/client.py:258`<br>`application/commands/{profile,campaign,character,cdk}.py`<br>`features/daily/runner.py` | `_check_binding_validity` 直接抛出父类 `CredentialExpiredError`，但 `profile`/`campaign`/`character`/`cdk` 仅捕获子类 `CookieExpired`。实测向聊天泄漏 `CredentialExpiredError: ...` 且不触发 `invalidate_cookie`；`cdk`/`daily` 未清内存客户端缓存。 | 全部命令处理器统一捕获 `CredentialExpiredError` 并清理缓存，移除 `application/commands/` 对 `blablalink.client` 的 6 处直连，错误提示统一去 Python 类名。 | 否 |
| **AUD-010** | **P1** | 代码路径证实 | `features/character/application.py` (`roster`, `_roster_option_summaries`)<br>`integrations/blablalink/client.py:699-844`<br>`application/commands/character.py` | `/妮姬 查询 练度` 先调用 `get_roster(True)` 拉全量详情却丢弃装备/词条，随后 Top 20 逐个调用 `get_character_detail`（未命中 `("roster", False)` 缓存再拉一次名单 + 20 次单卡详情 = 23 POST），且缺延迟反馈。 | **先做只读接口字段完整度验证**：确认批量接口在全量/Top 20 时是否完整无截断返回装备词条与 `state_effects`，再据实测采用复用或安全分批方案，并补延迟反馈。 | 是 |
| **AUD-011** | **P1** | 运行复现 | `adapters/astrbot/runtime.py:129-148`<br>`core/lifecycle/coordinator.py:166` | 实测关闭执行顺序为 `['client', 'calendar', 'feedback', 'voice', 'assets', 'web']`——在 `BindingWebService` 停止接流之前就关闭了 `BlaBlaClient`，停服瞬间在途绑定会失败。 | 调整 `_register_cleanup` 登记顺序，使 `client` 先注册、`web` 最后注册，确保逆序清理最先关闭外部入口 `web.stop()`。 | 否 |
| **AUD-012** | **P1** | 运行复现 + 代码路径证实 | `features/calendar/subscriptions.py`<br>`integrations/calendar/blabla_source.py:21-22`<br>`features/calendar/schedule_service.py` | 实测 `SeasonPass`（标题「月度通行证 · …」）因正则只认 `.*pass` 而落入 `活动Pass`，`月度Pass` 订阅零命中；`ttl_seconds=300` 等于调度周期 `300s` 频繁误转 `STALE` 暂停全员提醒；`PARTIAL` 同步错误阻断全站提醒；倒计时文案多计 1 小时。 | 依据 `metadata["official_type"] == "SeasonPass"` 精确匹配；将 `ttl_seconds` 调至 `900s`（保留真连续失败转 `STALE` 的 fail-closed 语义）；区分单条无效与全源失败。 | 是 |
| **AUD-013** | **P1** | 代码路径证实 | `core/lifecycle/scheduler.py:74-103`<br>`application/commands/daily.py`<br>`features/daily/runner.py` | ① `run_daily` 用 UTC 日期存结果、`send_summary` 用 CST 查结果且要求精确分钟匹配（`daily_hour<8` 提前 22h 触发，任务耗时跨过 `08:30` 即丢汇总，同分钟重启重发）；② 预检失效把当日标为 `expired` 导致重绑后当天不可补签；③ `DISPATCH_INTENT` 缺 `stale_after`。 | 统一汇总对齐 `community_day` 并增加带 DB 幂等键的补发窗口；仅在真正进入 `DISPATCH_INTENT` 后才锁定当日防重放，预检 `expired`/限流允许重绑后当日重试。 | 是 |
| **AUD-014** | **P1** | 运行复现 + 代码路径证实 | `integrations/web/service.py:283-295`<br>`core/storage.py:267-272` | 实测并发 `submit_cookies` 输家分支调用 `fail_bind_session`（无 `AND used_at IS NULL`）将已成功的 `'success'` 会话覆写为 `'failed'`；非法 JSON 负载返 500；Cookie 值与 UA 未拒 `;`/`\r`/`\n`。 | `fail_bind_session` 补 `AND used_at IS NULL`；统一 JSON 异常返回 400；严格校验 Cookie 值与 UA 禁止 `;` 与换行符。 | 否 |
| **AUD-015** | **P1** | 运行复现 + 代码路径证实 | `features/arena/{roster,analyzer,optimizer,statistics}.py`<br>`integrations/arena/web_routes.py`<br>`application/commands/arena.py` | 实测：① 私聊基于 `get_roster(False)` 仅出基础键，7/20 个珍藏模板推荐数为 `0`；② `product(*slots)` 按单模板平均上限 `102` 截断导致 `nayuta-carry` 等大模板在 `searched=956<2048` 即偏置截断；③ 替补按字母排序盲选；④ `solve()` 同步阻塞事件循环最高 1s。 | 将 `analyze`/`solve` 移入 `asyncio.to_thread()`；改为多槽均衡采样及按热度/充能替补；私聊明确支持可选/已缓存珍藏声明（严格区分官方确认与手动标记）。 | 是 |
| **AUD-016** | **P1** | 代码路径证实 | `integrations/spine/{worker_caller,prerenderer}.py`<br>`runtime/spine_worker/entrypoint-xvfb*.sh`<br>`runtime/spine_worker/main_sfml.cpp` | worker 超时未杀进程组致 `Xvfb` 孤儿残留；并发共享 `:99` 互相杀 Xvfb；透传完整 `os.environ`；`--list-animations` JSON 未转义且漏删 `.utf8`；生产 `prerenderer` 逆向导入 `scripts.spine.inspect_spine_bundle`。 | 将 `inspect_spine_bundle` 迁入 `integrations/spine/`；使用白名单环境变量与进程组超时查杀；动态 display + `trap`；修复 `main_sfml.cpp` 转义与唯一临时文件。 | 否 *(CI Docker E2E 验证)* |
| **AUD-017** | **P1** | 代码路径证实 | `templates/t2i/_shared/components.css`<br>`templates/t2i/{profile,campaign,roster}.html`<br>`ui/payloads/{campaign,character,roster}.py`<br>`ui/renderers/t2i.py` | `profile.html` `.today` 状态色在浅蓝底上 WCAG 对比度仅 1.59–1.87:1；`campaign`/`character` payload 缺 `canvas` 致跳过 viewport 设置；`campaign.html` SVG 占位溢出与两行长名溢出；`roster.html` 缺 CSP、72px/70px 列溢、表头碰撞与高度漏算。 | 修复 `.today` 高对比度配色；补齐所有模板 `canvas` 与 CSP；修复 `campaign`/`roster` 盒模型溢出与高度计算，确保 432px 缩略图下辅助字号可读。 | 是 |
| **AUD-018** | **P1** | 运行复现 + 代码路径证实 | `main.py:53-56`<br>`core/feedback.py:55-95`<br>`core/config.py`<br>`adapters/astrbot/command_presentation.py` | 实测 `start_delayed_feedback` + 立即 `cancel()` 使 3/3 个句柄永久滞留 `_active_handles`；`normalize_runtime_config` 放行 `"false"` 为真；`main.py:53-56` 全局向宿主 `wake_prefix` 注入 `#` 污染其他插件；`_renderer()` 永久缓存 `html_render=None`。 | 改用 `add_done_callback` 清理句柄；完善配置布尔/字符串归一化；`_renderer()` 拒绝缓存 `None`；移除全局 `wake_prefix` 注入并提供插件级隔离 `#妮姬` 入口替代。 | 是 |
| **AUD-019** | **P1** | 代码路径证实 | `features/character/{stat_calculator,builder}.py`<br>`application/commands/character.py`<br>`features/raid/{builder,query}.py`<br>`features/campaign/{builder,stage_resolver}.py`<br>`integrations/blablalink/client.py:463,692,704,817` | 缺失魔方/珍藏记录静默按 0 计算却标 `calculated_verified`；`builder.py:421` 缺空判断；单卡文本回退输出 `0.1181percent`/`魔方：未知`；突袭按本地时区解析 UTC 日期且休赛期丢统计；战役以 `name_code` 误查 `battle_tid`；空 `area_id` 多处 `int("")` 崩。 | 缺失装备/魔方/珍藏改为 fail-closed；修复文本回退格式化；突袭统一 UTC 解析与补全 `previous_season`；修正战役索引；封装 `_require_area_id`。 | 是 |
| **AUD-020** | **P2** | 代码路径证实 | `integrations/nikke_db/provider.py`<br>`core/assets/spine_manifest.py`<br>`integrations/blablalink/fetch_client.py`<br>`integrations/calendar/visual_cache.py`<br>`features/announcement/synchronization.py`<br>`integrations/announcement/information_feeds.py` | `NikkeDbProvider` 子目录纹理切片错位 + `asyncio.run` 重复解析；`spine_manifest` `declared_ids` 漏 `@skin`；`FetchClient` `HALF_OPEN` 无单探针锁且 4xx 熔断主机；`CalendarVisualCache` 漏放行 BlaBla CDN 假 IP 且带 GameKee 头；公告无同步锁致 `.tmp` 竞态且 `gather` 单条失败弃全批。 | 修复路径前缀过滤与 `@skin` 正则；`FetchClient` 仅 5xx/超时记熔断并加探针锁；`CalendarVisualCache` 补 BlaBla CDN 并清错误头；公告同步加单飞锁与部分容错。 | 否 |
| **AUD-021** | **P2** | 代码路径证实 | `core/storage.py`、`ui/renderers/t2i.py`<br>`features/character/face_guided_centering.py`<br>`ui/payloads/character.py`、`ui/t2i_assets.py`<br>`core/assets/{prefetcher,image_cache}.py`<br>`features/calendar/snapshot_repository.py` | 同步 `sqlite3`、Pillow 编解码、日历 `fsync` 与纯 Python 2k×2k Alpha 循环阻塞事件循环；`character.html` 每次内联 ~1.94MB 字体（含重复 `font_noto` 与 3 个未用字重）及未渲染水印；`T2IAssetResolver` 命中前重复全图 SHA-256；`prefetcher` 14 任务/卡 vs 全局 16 上限；缓存目录与 `action_runs` 无清理。 | Pillow/日历 `fsync` 移入 `asyncio.to_thread()`；Alpha 投影改 Pillow C 级操作；`character` 仅按需嵌入激活字体与已渲染字段；优化缓存查重键与上调预取槽位；补安全运维清理。 | 否 |
| **AUD-022** | **P2** | 代码路径证实 | `adapters/astrbot/command_runtime.py`<br>`core/providers/announcement.py`<br>`extension/{background,popup,manifest}.*`<br>`README.md` | `README` 列出的公告过滤/诊断命令被路由拦截；管理员 `公告 订阅` 亦消费 `CalendarService` 与个人 `日程 订阅` 同群双重提醒；扩展将 `game_token` 与登录字段存 `chrome.storage.local` 且申请过宽 `tabs` 权限。 | 按决策对齐公告路由与 README；分离公告推送与日程截止提醒；扩展临时续期材料迁 `chrome.storage.session` 并缩窄为 `activeTab`。 | 是 |
| **AUD-023** | **P2** | 代码路径证实 | `features/calendar/*`、`features/character/*`<br>`main.py:229-478`、`ui/payloads/calendar.py`<br>`ui/theme.py`、`templates/t2i/arena_*.html`<br>`assets/{cube,favorite,currency,fonts,tarot,spine-rendered}/`、`scripts/*` | 日历 ~2,800–3,200 行停用多源代码与 4 倍重复写盘；4 套服装解析器 + 3 套 `SpineBundle` + 休眠 `face_guided_centering`；`main.py` 36 个生产不可达历史方法；`ui/payloads/calendar.py`（798L）混入领域逻辑；`assets/` 56 个逐字节重复图标 + 16.36MB 未用 OTF + 大体量媒体。 | **先逐项验证无动态/脚本/回退依赖后再清理**；去重 56 个图标与无用 OTF；合并重复抽象、下沉领域逻辑、对塔罗/Spine 做无损/高保真压缩（保留功能）。 | 否 *(资产压缩后做冷启验证)* |
| **AUD-024** | **P3** | 代码路径证实 | `features/profile/{currency_registry,builder}.py`<br>`application/commands/profile.py`<br>`features/calendar/{merge,query,canonical_models}.py`<br>`ui/payloads/calendar.py:629`、`core/providers/voice.py`<br>`features/voice/{scene_catalog,feedback}.py`<br>`features/guide/registry.py`、`integrations/character/stat_resources.py`<br>`extension/popup.html`、`docs/architecture/ASTRBOT_COMMAND_ENTRY_MAP.md` | `CurrencyRegistry.errors` 无界增长 + 矛盾死币种表 + `躯体标签`/`白银积分券` 不一致；`calendar.py:629` 与 `canonical_models.py` UTC/CST 日期差 1 天、`EXPIRED` 失败反升 `STALE`、未开始活动显距结束；`Voice` 缺 `ffmpeg` 静默失效；`GuideRegistry` 每命令重读 JSON；`stat_resources` 缓存永不过期且持锁联网；扩展 checkbox 拉伸；映射文档过期。 | 随所在阶段顺手修复，同步刷新 `README.md` 与 `ASTRBOT_COMMAND_ENTRY_MAP.md`。 | 否 |
| **AUD-025** *(新增)* | **P1** | 运行复现 | `core/providers/web.py:30`<br>`integrations/web/service.py:76` | PR #128 引入 `web_trusted_proxy_ip`，直接传给 `ip_address()` 且未经 `normalize_runtime_config` 校验。实测填入 `"caddy"` 或 CIDR 网段直接抛未捕获 `ValueError`，导致插件启动失败。 | 在 `normalize_runtime_config` 校验 `web_trusted_proxy_ip`（支持可选 CIDR，非法值降级为空并记告警，不阻断启动）。 | 否 |
| **AUD-026** *(新增)* | **P2** | 运行复现 | `adapters/astrbot/command_runtime.py` | PR #128 合入后 `command_runtime.py` 已达 **389 / 400 行**硬门槛边缘，随时可能因小改动触红门禁。 | 在 Phase 2 拆分参数解析器与收口帮助逻辑，将行数压回 ≤ 330 行。 | 否 |
| **AUD-027** *(新增)* | **P2** | 代码路径证实 | `adapters/astrbot/command_runtime.py:176-177`<br>`application/commands/help.py` | `/妮姬 帮助 详解` 仅判断 handler 子属性是否不为 `None`，而 `main.py` 无论 `enable_daily_actions` 开关真假均始终构造对应对象，导致写开关关闭时仍向用户展示「日常任务」「账号续期」教学。 | 传入真实配置开关状态，按配置动态过滤未启用功能的教学主题。 | 否 |

---

## 4. 分阶段 PR 实施计划（Phase 0 → Phase 6）

> 每个 PR 均为**独立可审查、可测试、可单步 `git revert` 回滚**的工作单元；严格禁止把高危存储/写操作和大规模代码搬迁混在同一个 PR。

### Phase 0：更新基线、修复测试环境、建立回归保护（`PR-0`）

- **目标**：建立基于 `ab610f5` 的可靠全量测试与架构基线，不改任何生产业务逻辑。
- **修改范围与涉及文件**：
  - 文档/工具/测试新增（不改 `features/`、`core/`、`integrations/`、`adapters/`、`application/`、`ui/`、`main.py`）：
  - 若需兼容任意检出目录名运行 `pytest`，评估采用最小标准可编辑安装元数据或固定开发指南要求在 `astrbot_plugin_nikke` 目录运行（禁止在 `tests/` 写 `sys.modules` 别名黑魔法）；
  - `scripts/audit/architecture_metrics.py`：以**显式基线清单（allowlist）**登记当前 8 条既有跨层边（6 条 `application -> blablalink.client`、1 条 `features.calendar -> integrations.calendar`、1 条 `integrations.spine -> scripts.spine`），对**新增**跨层边报错（确保 Phase 0 对现状仍返回 0 违规）；
  - `.github/workflows/ci.yml`：接入 `mypy` 检查步骤（与 `mypy.ini` 当前 37 文件基线对齐）与 `architecture_metrics.py --check` 步骤；
  - `tests/`：补充黄金命令路由兼容表测试、隐私脱敏边界测试用例、换绑/租约/调度/T2I 回归夹具骨架。
- **需保留的现有行为**：生产运行时零变化；原有 1,955 项测试全绿。
- **验证命令与完成判据**：
  - `python scripts/audit/architecture_metrics.py --check` 退出码 `0`；
  - `python -m pytest -v` 0 collection error、全量通过；
  - `node --test tests/extension.test.cjs` 与 `mypy` 全绿；
  - 形成生产 `serv` 与 `main (ab610f5)` 的版本核对及数据库成对备份 SOP 记录。
- **回滚策略**：单个 revert commit 即可回退，零运行时影响。
- **是否需要真实环境验收**：否（仅需在只读模式下核对 `serv` 当前 commit 与备份可用性）。

---

### Phase 1：安全、账号授权、绑定及运行稳定性

#### `PR-1A`：存储与账号授权边界加固（高危，独立审批）
- **解决问题**：`AUD-002`, `AUD-007`, `AUD-014`
- **修改范围与涉及文件**：
  - `core/storage.py`：
    - `consume_bind_session()`：在 `ON CONFLICT(qq_id) DO UPDATE` 前查询原绑定记录的 `(game_openid, game_uid)`，**仅当游戏身份发生变化时**重置 `auto_daily_enabled=0` 与旧 `daily_scope_v2`；同游戏账号续绑保留原有授权；**完整保留全部 `action_runs` 历史与 `UNKNOWN_AFTER_ACTION` 保护**；
    - `fail_bind_session()`：SQL 增加 `AND used_at IS NULL` 防止后发失败覆盖已成功会话；
    - `_load_or_create_key()`：改用 `os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` 原子创建密钥文件，捕获 `FileExistsError` 重读，消除权限 TOCTOU 与并发覆写；
    - 新增 `has_valid_key()` 方法（兼容 `NIKKE_ENCRYPTION_KEY` 与 `secret.key`）。
  - `integrations/web/service.py`（`_storage_ready`）与 `core/health.py`（`collect_runtime_health`）：统一改用 `has_valid_key()` 判定密钥就绪状态。
- **需保留的现有行为**：`SCHEMA_VERSION = 2` 不变；现有加密数据无需重加密；同账号续绑不丢自动签到偏好。
- **新增/调整测试**：换绑不同游戏号自动撤销继承授权但保留历史 `action_runs`；同游戏号续绑保留 `auto_daily_enabled=1`；并发 `fail_bind_session` 不覆写 `success`；`NIKKE_ENCRYPTION_KEY` 模式下 `/healthz` 返回 200 且健康报告无「密钥缺失」；`os.open` 原子建密钥权限与竞态测试。
- **前置条件**：所有者批准 Decision 1；发布前执行 `scripts/operations/upgrade_preflight.py` 与 `backup_nikke_data.py` 成对备份。
- **风险与回滚策略**：**高风险**（涉及存储与授权边界）。单独小 PR 提交；异常时停止服务、切回前版并按成对备份恢复（无 schema 变化，向后兼容）。
- **完成标准**：上述新增与存储全量测试通过，`/healthz` 在文件密钥与环境变量密钥两种部署均返回 200。
- **是否需要真实环境验收**：**是**（测试账号验证换绑+续绑行为、环境变量密钥容器 `/healthz` 探测）。

#### `PR-1B`：Web 绑定页面、脱敏与运行稳定性修复
- **解决问题**：`AUD-001`, `AUD-003`, `AUD-004`, `AUD-006`, `AUD-011`, `AUD-014`, `AUD-018`（句柄/配置/渲染缓存）, `AUD-025`
- **修改范围与涉及文件**：
  - `integrations/web/bind_template.py`：JS 轮询兼容识别 `'success'`、`'consumed'`、`'bound'` 并处理 `'failed'`，轮询间隔调整为 4s，外链补充 `rel="noopener noreferrer"`；
  - `integrations/web/service.py` & `core/config.py`：对 `web_trusted_proxy_ip` 做 `ip_address` / `ip_network` 容错校验（非法值降级为空并记告警，禁止启动崩盘）；为 `_requests` 增加惰性淘汰与容量上限；`/api/bind/session` 与 `/api/bind/cookies` 统一捕获 `JSONDecodeError` / 非法结构返回 400；严格拒绝 Cookie 值与 `user_agent` 中的 `;`/`\r`/`\n`；`normalize_runtime_config` 补齐布尔（禁止 `"false"` 转 `True`）与字符串兜底校验；
  - `core/privacy.py` & `application/commands/cdk.py`：加固 `sanitize_log_text` 覆盖完整 `Cookie:`/`Set-Cookie:`、`/bind/<token>`、`/arena/open/<token>`、独立 `Bearer`/JWT、带空格引号值及扩展敏感键；`cdk.py` L121-122、L149-150 异常输出改走脱敏友好文案；
  - `core/lifecycle/scheduler.py`：`run()` 增加 `except Exception` + 退避重试与告警节流，单次 SQLite 锁失败不终止调度器和宿主生命周期；
  - `adapters/astrbot/runtime.py`：调整 `_register_cleanup` 顺序使 `web.stop` 最后登记（逆序关闭时最先停接流）、`client.aclose` 最先登记（最后关闭）；
  - `core/feedback.py` & `adapters/astrbot/command_presentation.py`：`_active_handles` 改为 `task.add_done_callback` 清理；`_renderer()` 当 `html_render()` 返回 `None` 时不缓存实例。
- **需保留的现有行为**：绑定 API JSON 字段兼容；正常日志排查字段不被误遮盖。
- **新增/调整测试**：绑定页状态轮询（`success`/`failed`/`expired`）、Caddy XFF 与多网段配置容错、非法 JSON 返回 400、SQLite 锁超时调度器存活测试、关闭回调逆序断言、脱敏攻击向量矩阵、延迟反馈 0 泄漏测试。
- **回滚策略**：无存储结构变更，可直接单步 `git revert` 并重启服务。
- **完成标准**：所有单测与扩展测试通过；`architecture_metrics.py --check` 0 违规。
- **是否需要真实环境验收**：**是**（真实浏览器绑定全流程、反代多端并发无误 429、重启确认停服日志顺序）。

---

### Phase 2：命令解析、帮助导航、QQ 交互与竞技场合并后兼容（`PR-2`）

- **解决问题**：`AUD-008`, `AUD-009`, `AUD-015`（事件循环阻塞）, `AUD-018`（`wake_prefix` 替换）, `AUD-022`（帮助/公告/扩展）, `AUD-026`, `AUD-027`
- **修改范围与涉及文件**：
  - `adapters/astrbot/` & `main.py`：
    - 抽离独立 `command_parser.py` 统一基于 `event.message_str` 解析尾参（支持换行输入与多词角色名、空格批量 CDK、空格日程订阅、嵌套 `查询` 子命令），保留现有直接调用位置参数签名与全部 `/妮姬`、`/nikke` 兼容；移除 `_legacy` 4 个不可达死分支；同步使 `command_runtime.py` 行数降至 **≤ 330 行**（远离 400 行红线）；
    - 移除 `main.py:53-56` 对 `context.astrbot_config["wake_prefix"]` 的全局写修改，**同时**在 `main.py` 新增插件级受限入口（仅匹配 `^\s*#(?:妮姬|nikke)(?:\s|$)`）转发至同一 `command_runtime.nikke`，实现零宿主污染的 `#妮姬` / `#nikke` 兼容；
  - `application/commands/{profile,campaign,character,cdk,daily,raid}.py`：统一捕获 `CredentialExpiredError` 并执行账号缓存失效，移除对 `integrations.blablalink.client` 的 6 处直连，统一温和错误文案（含「请私聊发送 /妮姬 账号 绑定」提示，隐藏 Python 类名）；
  - `features/help/catalog.py`、`application/commands/help.py`、`adapters/astrbot/command_runtime.py`：将帮助首页、分类帮助与帮助详解收口为单一数据源，修复 `push` 别名误映射，修复 `help_detail` 按真实 `enable_daily_actions` 配置动态显隐；按 Decision 4a 对齐公告过滤子命令路由与 `README.md`；
  - `integrations/arena/web_routes.py` & `application/commands/arena.py`：将 `analyzer.analyze()` 与 `ThreeTeamOptimizer.solve()` 迁入 `asyncio.to_thread()`；
  - `extension/{background.js,popup.js,popup.html,manifest.json}`：临时登录/续期材料从 `chrome.storage.local` 迁至 `chrome.storage.session`、`tabs` 权限收窄为 `activeTab`、修复 `popup.html` checkbox 拉伸及 `popup.js` cookie 域名读取一致。
- **门禁收紧**：清零 `application.commands -> integrations.blablalink.client` 6 条跨层边后，从 Phase 0 allowlist 移除并设为硬门禁。
- **前置条件**：所有者拍板 Decision 3（`wake_prefix` 替代方案）与 Decision 4a（公告子命令）。
- **新增/调整测试**：Phase 0 黄金路由兼容表 + 多词角色/空格批量 CDK/嵌套查询/换行三队导入测试；AstrBot 宿主配置未修改 + `#妮姬` 真实过滤测试；6 个处理器 `CredentialExpiredError` 回归；帮助主题按配置动态显隐测试；Node 扩展 `storage.session` 契约测试；竞技场并发响应延迟回归。
- **回滚策略**：不涉及 DB 迁移，命令与路由改动可通过单个 revert 回滚；扩展独立打包可回退上一版 zip。
- **完成标准**：全量测试、Node 测试与收紧后的架构门禁全绿。
- **是否需要真实环境验收**：**是**（真实 QQ 测试 `#妮姬` 触发、多词名、空格批量 CDK、帮助与帮助详解导航、竞技场网页及扩展重装绑定）。

---

### Phase 3：日程订阅、社区自动化、状态机及调度正确性

#### `PR-3A`：日程订阅、时间语义与双订阅整理
- **解决问题**：`AUD-012`, `AUD-022`（双订阅重叠）, `AUD-024`（日程部分）
- **修改范围与涉及文件**：
  - `features/calendar/subscriptions.py` & `integrations/calendar/blabla_source.py`：以 `metadata["official_type"] == "SeasonPass"` 精确匹配 `月度Pass` / `活动Pass`；对齐支持类型列表与文案；修正 `剩余不足{hours+1}小时` 提示与 UTC `start_day` 边界；
  - `features/calendar/{schedule_service,merge,query,canonical_models}.py`：将 `ttl_seconds` 由 `300s` 调整为 `900s`（维持连续失败转 `STALE` 并停推的 fail-closed 机制）；`PARTIAL` 单条解析警告不再一刀切阻断全部提醒；修复 `EXPIRED` 失败反升 `STALE`、修复 `remaining_display()` UTC/CST 混用与未开始活动倒计时显示；
  - `core/providers/announcement.py` & `features/announcement/{delivery,application}.py`：按 Decision 4b 解耦管理员公告订阅与日历截止提醒，避免同群双重推送；为 `AnnouncementDelivery` 增加未决数量监控上限与已完结投递归档。
- **前置条件**：所有者拍板 Decision 4b（双订阅去重分工）。
- **新增/调整测试**：`SeasonPass` 命中 `月度Pass` 不误中 `活动Pass`；300s+ 周期同步不误判 `STALE`；`EXPIRED` 故障不降级回 `STALE`；CST 00:00–07:59 跨日显示正确；同群开启双订阅仅收到一次各自职责提醒。
- **是否需要真实环境验收**：**是**（测试群实际接收个人日程 `@订阅者` 提醒）。

#### `PR-3B`：社区任务状态机与日常调度修复（高危写操作，独立审批）
- **解决问题**：`AUD-005`, `AUD-013`
- **修改范围与涉及文件**：
  - `features/daily/action_models.py`、`features/daily/actions.py`、`application/commands/community_automation.py`：
    - **执行租约（可安全回收）**：`account_execution_lease` 写入进程实例标识与保守租约超时（如 10 分钟），仅当确认原持有进程已超时/非本代次存活时才允许接管释放，防止崩盘永久锁死；统一 `DailyRunner._account_lock` 与 DB 租约均使用 `account_scope`；
    - **动作结果状态（绝不自动解锁）**：`UNKNOWN_AFTER_ACTION` 严禁在超时后自动恢复或自动重放；仅新增受权限保护的显式人工核实恢复命令（带操作人、时间与原 `run_key` 审计记录），确认后仅解除后续新周期阻断、绝不补跑未决历史；修复 `NOT_SENT` 误扣周期预算及旧 `binding_revision` 永久残留告警；
  - `core/lifecycle/scheduler.py`、`features/daily/runner.py`、`application/commands/daily.py`：
    - 统一自动日常与汇总均基于 `community_day`（附 UTC/CST 映射一致性校验），修复 `daily_hour < 8` 提前 22h 触发；
    - 每日汇总增加基于 DB 幂等键的补发窗口，既不因前序社区任务耗时错过 `08:30`，也不在同分钟重启时重发；
    - 仅在已进入写前 `DISPATCH_INTENT` 后才锁定当日防重放，**预检阶段**的 `CredentialExpiredError` / `RATE_LIMITED` 允许同日重绑后补签；`DISPATCH_INTENT` 补充 `stale_after=120`；
    - 统一私聊异常通知路由登记，并隔离 `_notify()` 异常不阻断后续任务。
- **前置条件**：所有者拍板 Decision 2（`UNKNOWN_AFTER_ACTION` 显式恢复入口形态）。
- **新增/调整测试**：模拟崩溃后超时租约安全回收测试；`UNKNOWN_AFTER_ACTION` 跨 72 小时仍严格拦截自动重放 + 人工确认后仅允许新周期执行测试；72h 调度仿真（跨 UTC 零点、凌晨 `daily_hour`、任务延迟超汇总时间、同分钟重启）；预检失败重绑当日补签测试。
- **风险与回滚策略**：**高风险**（写操作与定时调度）。生产可随时通过 `enable_daily_actions=false` 熔断降级，代码独立 revert。
- **是否需要真实环境验收**：**是**（在测试账号与独立试验开关下验证签到、汇总与故障通知）。

---

### Phase 4：角色查询性能、数据计算、竞技场算法、Spine 与数据源可靠性

> 按低耦合拆分 3 个子 PR：`PR-4A`（前置验证 + 核心业务与角色性能）、`PR-4B`（竞技场算法）、`PR-4C`（Spine 与上游数据源）。

#### `PR-4A`：练度查询前置验证与角色/突袭/战役/资料核心修复
- **解决问题**：`AUD-010`, `AUD-019`, `AUD-021`（事件循环与 Alpha 循环部分）, `AUD-024`（Profile/资源部分）
- **必须先执行的验证步骤（不预设固定请求数）**：
  1. 先编写只读验证脚本（或用脱敏抓包回放对比），在授权只读账号核查 BlaBlaLink `GetUserCharacterDetails` 在传入全量 `name_codes` 与 Top 20 `name_codes` 时，返回的 `equipment` 槽位、`equip_option*_id` 与 `state_effects` 是否与单角色请求 100% 一致、是否存在分页或长度截断；
  2. 根据验证结论确定最优落地方式：若批量接口返回完整且未截断，则直接复用全量批量结果或合并 Top 20 为 1–4 批请求并复用 `get_roster` 缓存；若存在长度截断或字段缺失，则采用验证通过的安全批大小 + 缓存复用；同时补齐延迟反馈与基准耗时/请求数记录。
- **其余修改范围**：
  - `features/character/{builder,stat_calculator,face_guided_centering,face_anchor}.py` & `application/commands/character.py`：补齐 `overload_tier_registry` 空判断；缺失魔方/珍藏记录改 fail-closed 报错；修复文本回退百分比与物品显示名；以 Pillow C 级投影替换 `robust_alpha_bounds` 纯 Python 双重循环，消除双次全图 RGBA SHA-256；
  - `integrations/character/stat_resources.py`：引入磁盘缓存 TTL、将同步 HTTP 请求移出 `RLock`、消除 `tables_mapping()` 9 次重复拷贝；
  - `features/raid/{builder,query}.py`、`features/campaign/{builder,stage_resolver}.py`、`features/profile/{builder,currency_registry}.py`、`application/commands/profile.py`：突袭时间强制按 UTC 解析、休赛期回填 `previous_season` 统计；移除战役错误的 `name_code->tid` 查询与奇次重复 ID 覆盖；修复 `CurrencyRegistry.errors` 泄漏、统一 `躯体标签`/`白银积分券`；
  - `integrations/blablalink/client.py`：统一 `_require_area_id` 校验、`invalidate_cache` 取消在途任务、`invalidate_account_cache` 兼容 `cookie_valid=False`、引入并发信号量与 `IsolatedAsyncClient`；
  - `core/storage.py` + `ui/renderers/t2i.py`（非阻塞部分）：耗时较重的本地计算与渲染前 Pillow 处理逐步纳入 `asyncio.to_thread()`。
- **完成标准**：练度查询验证报告完成且优化前后数据 100% 一致；角色/突袭/战役/资料回归全绿。
- **是否需要真实环境验收**：**是**（只读核对 `/妮姬 练度` 真实返回数据完整性、单角色卡与休赛期突袭）。

#### `PR-4B`：竞技场搜索算法与私聊珍藏支持
- **解决问题**：`AUD-015`（算法与珍藏可达性）
- **修改范围与涉及文件**：
  - `features/arena/analyzer.py`：改进模板遍历与多槽采样策略，避免大模板（如 `nayuta-carry`、`noah-biscuit-stall`）耗尽全部单模板预算在尾槽；同爆裂阶段替补按模板出现频次/充能效率排序，替代纯字母顺序盲选；
  - `features/arena/{roster,identity,application,statistics}.py` & `application/commands/arena.py`：在私聊模式支持读取已缓存详情或用户可控珍藏标记（严格标注「官方详情确认」vs「手动标记」vs「基础名单推测」，禁止伪造持有状态）；在相似匹配统计文案中明确样本组合口径限制。
- **完成标准**：`test_arena_*.py` 全绿并新增珍藏可达性与搜索覆盖率断言。
- **是否需要真实环境验收**：**是**（实测 QQ 私聊 `/妮姬 竞技场 解队` 与珍藏模板推荐）。

#### `PR-4C`：Spine 运行时、Nikke-DB 与外部数据源加固
- **解决问题**：`AUD-016`, `AUD-020`
- **修改范围与涉及文件**：
  - `integrations/spine/{prerenderer,worker_caller}.py` & `runtime/spine_worker/*`：将 `inspect_spine_bundle` 迁入 `integrations/spine/`（消除最后 1 条 `integrations -> scripts` 跨层边并转为硬门禁）；`worker_caller` 使用白名单环境变量与进程组超时查杀；`entrypoint-xvfb*.sh` 改为动态 display + `trap` 清理；修复 `main_sfml.cpp` `--list-animations` JSON 转义与唯一 `.utf8` 临时路径；
  - `integrations/nikke_db/provider.py` & `core/assets/{spine_manifest,prefetcher,downloader}.py`：修复子目录纹理相对路径切片与 `asyncio.run` 重复解析；修复 `spine_manifest.py` `declared_ids` 遗漏 `@skin`；合理提高 `MAX_PREFETCH_TASKS` 避免 2 并发互饿；`AssetDownloader` 移除类级全局信号量与未锁字典；
  - `integrations/blablalink/fetch_client.py`、`integrations/calendar/visual_cache.py`、`features/announcement/synchronization.py`、`integrations/announcement/information_feeds.py`：修复 `FetchClient` `HALF_OPEN` 单探针锁与 4xx 误熔断；`CalendarVisualCache` 放行 BlaBla CDN 假 IP 并清除错误 GameKee 头；公告同步增加单飞锁、唯一临时文件与明细 `return_exceptions=True`。
- **完成标准**：CI 全矩阵（含 Linux Docker Spine 4.0/4.1 worker E2E）通过；`integrations -> scripts` 门禁收紧转绿。
- **是否需要真实环境验收**：否（CI Docker worker 已覆盖核心渲染路径；部署 Spine worker 环境按 Release Checklist 冒烟）。

---

### Phase 5：T2I UI、移动端可读性、模板与渲染资源优化（`PR-5`）

> **设计原则**：统一基础设计规范（token、最低可读字号、CSP、显式 `canvas`、溢出保护），**尊重不同功能各自的信息结构，不强求统一为单一卡片形式**；优化负载以**画质、角色一致性和部署兼容性不降级**为硬前提。

- **解决问题**：`AUD-017`, `AUD-021`（渲染阻塞、字体重复与 base64 负载）, `AUD-024`（`calendar.py:629` 等）
- **修改范围与涉及文件**：
  - `ui/renderers/t2i.py`、`ui/t2i_templates.py`、`ui/t2i_assets.py`：将 `campaign`/`profile`/`union_*`/`character` 全部 Pillow 处理移入 `asyncio.to_thread()`，缓存模板与 builder 实例；`T2IAssetResolver` 命中本地路径缓存前跳过重复 15MB RGBA 全图 SHA-256；
  - `templates/t2i/_shared/tokens.css` & `components.css` & `raid.css`：梳理基础视觉变量（明确暗色/亮色共享语义变量与最低字号/间距约定），清除 `.schedule .state-*` 死选择器与 `raid.css` 自覆写；
  - `templates/t2i/profile.html`：修复 `.today .state-*` 浅底对比度（达到 ≥ 4.5:1 WCAG AA），保护 `.identity-grid .kv>strong` 超长文字；
  - `templates/t2i/campaign.html` & `ui/payloads/campaign.py`：补充显式 `canvas`、修复 SVG 占位溢出与两行长名裁剪、提升辅助字号改善 432px 缩略可读性（保留其适合阵容横排的既有构图或按审阅意见微调）；
  - `templates/t2i/roster.html` & `ui/payloads/roster.py`：补充 CSP meta、修正 70px→72px 列宽与表头挤压、修正 `avatar_note` 高度累加、提升小注字号；
  - `templates/t2i/character.html` & `ui/payloads/character.py`：补充 `canvas: {width: 1600, height: 2400}`；**仅嵌入当前激活排版实际用到的子集字体**，移除重复 `font_noto`、未渲染的 `corporation_watermark` 与 10+ 死字段（无损降载 > 1MB）；补齐长名省略号、7 位战力防撞与魔方/珍藏缺图占位；
  - `templates/t2i/calendar_schedule.html` & `ui/payloads/calendar.py`：修复 L629 UTC/CST 日期差；补充 `.is-oversize` 样式防撞击页脚；强模糊背景改用降采样分辨率替代 1600×1200 无损 PNG（模糊后视觉完全一致）；
  - `templates/t2i/arena_matchup.html` & `arena_three_teams.html` & `ui/payloads/arena.py`：抽取共享样式片段减少复制，修正分页高度公式。
- **验证方式与完成标准**：
  - 全模板 CSP 与 `canvas` viewport 门禁通过；
  - 使用本地 Playwright 输出合成原图与 **432px 手机缩略图**对照检查：0 对比度失效、0 溢出裁切、主次文字在 432px 下可辨识，单角色卡 HTML payload 明显减重且视觉画质与既有卡面一致；
  - 如评估格式转换（例如高质量 WebP/JPEG），须先在测试 QQ/NapCat 验证发图兼容与清晰度，无明确优势或存疑则保持 PNG。
- **回滚策略**：纯展示层 PR，可按单模板回退，零数据或业务影响。
- **是否需要真实环境验收**：**是**（手机 QQ 实看 432px 缩略图及点开原图画质）。

---

### Phase 6：代码结构瘦身、文档整理与资产治理（多 PR 渐进执行）

> **前置硬约束**：保留塔罗与语音功能；所有待删休眠/历史代码均须先输出「静态引用 + 动态调用 + 外部脚本依赖 + 回退用途」四重核查清单；任何高危存储或写操作绝不混入本阶段 PR。

- **解决问题**：`AUD-023`, `AUD-024`
- **子 PR 划分**：
  - **`PR-6A`（无功能损失的资产去重与高保真压缩）**：
    - 合并 `assets/{cube,favorite,currency}/` 与 `assets/icons/{cube,favorite,currency}/` 之间的 56 个逐字节重复图标并统一 `core/paths.py`；
    - 核实 `assets/fonts/` 中 16.36MB `NotoSansHans-*.otf` 的仅存 2 个离线脚本依赖（改为按需脚本加载或复用已验证字体），核实 `ReplicaSans.otf` 许可与在 `NOTICE` 补全 `Nikke-db` 归属；
    - **保留塔罗与语音功能**：对塔罗原图（139.25MB）与预渲染 Spine PNG（119.56MB）在画质与锚点 SHA-256 校验约束下进行压缩优化（例如塔罗高保真无损/近无损压缩并核验旋转逻辑，Spine 仅做不改变解码像素值的 PNG 无损优化以绝对保证 `nikke_portrait_anchor` 字节级像素一致）；
    - 为 `Voice` 缺 `ffmpeg` 补齐开启反馈与告警日志，仅删除经核查 0 引用的 `features/voice/{scene_catalog,feedback}.py`。
  - **`PR-6B`（日历/角色/容器结构瘦身与跨层边清零）**：
    - 在完成依赖核查并获批后，清理 `features/calendar/` 长期停用的 GameKee/Official 源与空转 $O(N^2)$ 跨源合并逻辑（保留源适配器抽象接口），通过依赖注入消除 `features.calendar.schedule_service -> integrations.calendar.blabla_source`（并转硬门禁），消除 `schedule_events.json` 4 倍重复写盘，将 `ui/payloads/calendar.py` 领域逻辑下沉至 `features/calendar/`；
    - 核查后清理或拆分 `face_guided_centering.py` 未启用实验路径、合并 `costume_asset_resolver.py` 与 `visual_resolver.py`、统一 `SpineBundle`/`SpineRenderError`、清理 `features/raid/application.py` 废弃方法、`profile/builder.py:32-121` 矛盾死币种表、`ui/theme.py` 死调色板与 `core/container.py:116` 死变量；
    - 为 `GuideRegistry` 补缓存；为缓存目录与已完结 `action_runs` 历史增加运维安全清理策略（严禁清理未决 `UNKNOWN_AFTER_ACTION`）。
  - **`PR-6C`（入口历史兼容清理与文档同步）**：
    - 将 24 组直接调用 `main.py:229-478` 未注册方法的测试迁至 `command_runtime` / 正式处理器后，核查确认无外部动态调用后移除 36 个生产 0 可达遗留方法（100% 保留全部 QQ 命令）；
    - 清理无文档/CI 引用的冗余 `scripts/` 根兼容壳（保留运维文档公开入口如 `backup_nikke_data.py`、`upgrade_preflight.py`）；
    - 全面更新 `README.md`、`docs/architecture/ASTRBOT_COMMAND_ENTRY_MAP.md` 与 `docs/refactor/FINAL_DELIVERY.md`。
- **完成标准**：
  - Phase 0 登记的 8 条既有跨层边基线**全部清零并转为硬门禁**，`architecture_metrics.py --check` 退出码 `0`；
  - `pytest` 全量、`node --test`、`mypy`、`scripts/audit/audit_assets.py` 全绿；
  - 资产压缩前后抽检画质、角色立绘对齐与锚点校验 100% 通过。
- **回滚策略**：3 个子 PR 相互独立，不改 Git 历史，任意子 PR 可单独 revert。
- **是否需要真实环境验收**：仅 `PR-6A`（资产变更后）需在全新部署目录冷启动验收资源加载正常。

---

## 5. 回归保护与真实环境最小验收清单

### 5.1 八项回归保护基线（贯穿 Phase 0–6）
1. **命令兼容基线**：锁定 `/妮姬`、`#妮姬`、`/nikke`、`#nikke`、全部中文/英文/平铺别名、多词参数及竞技场命令；
2. **权限与默认关闭合同**：未绑定/群聊/私聊/管理员四象限权限，及 `allow_group_bind`、`enable_daily_actions`、`enable_cdk_redemption`、`enable_announcement_push`、`enable_arena`、`arena_web_enabled` 默认全关 fail-closed；
3. **异常与边界固定样本**：换绑不同游戏号、同号续绑、SQLite 锁超时、空 `area_id`、UTC 00:00–07:59 跨日、多对 Cookie 脱敏、7/20 珍藏竞技场；
4. **T2I 与文本回退双检**：检查视口、CSP、对比度、零溢出、432px 可读性与「渲染失败不重查上游」（不使用僵化像素 diff 阻断合理 UI 修复）；
5. **持久化、生命周期与恢复**：`DelayedFeedbackManager` 零泄漏、租约超时回收、`UNKNOWN_AFTER_ACTION` 跨重启不重放、停服逆序（`web` 先于 `client`）、env-key `/healthz`；
6. **CI 与渐进式架构门禁**：Phase 0 先允许既有 8 条跨层边并拦截新增边，随 Phase 2/4C/6B 逐项清零收紧；CI 纳入 `mypy` 与 `architecture_metrics.py --check`；
7. **数据库升级与成对备份步骤**（涉及 `core/storage.py` 或写状态机发布必跑）：
   ```bash
   python scripts/operations/upgrade_preflight.py --data-dir /实际路径/AstrBot/data/nikke
   python scripts/operations/backup_nikke_data.py --data-dir /实际路径/AstrBot/data/nikke --destination /安全备份目录
   ```
8. **真实 QQ / NapCat / AstrBot 人工最小验收清单**（严禁以单元测试全部通过代替）：
   - [ ] 私聊 `/妮姬 账号 绑定` → 扩展提交 → 绑定页自动展示成功 → `/妮姬 账号` 状态正常；
   - [ ] 3 个以上客户端并发访问绑定页无 429，`/healthz`（含环境变量密钥模式）返回 200；
   - [ ] 群聊与私聊分别测试 `/妮姬`、`#妮姬`、`/nikke` 触发，确认 `#` 未误触发宿主其他插件；
   - [ ] 测试 `/妮姬 兑换 批量 CDK1 CDK2`（空格多码）、`/妮姬 查询 练度 <多词英文名>`、`/妮姬 帮助` 与 `/妮姬 帮助 详解 <主题>`；
   - [ ] 测试 `/妮姬 我的`、`/妮姬 查询 练度`、`/妮姬 突袭`、`/妮姬 战役` 图片送达且手机 QQ 432px 缩略图清晰可读；
   - [ ] 测试 `/妮姬 日程` 与 `/妮姬 日程 订阅 协同,月度Pass`，在 24h 窗口验证群内仅 `@订阅者` 且无同群双推重复；
   - [ ] 私聊测试 `/妮姬 竞技场 解队` 与 `/妮姬 竞技场 三队` 网页回查（确认 15 秒内响应不卡死其他指令）；
   - [ ] 测试账号在灰度开关下验收签到、汇总补发与停服重启恢复日志。

---

## 6. 提 PR 前需向项目所有者确认的 6 项决策（Decision 1 – Decision 6）

> 请审阅后对以下 6 项决策批复选择，对应 Phase 将据此精确落地；未获批的高危或产品变更不擅自推进。

### Decision 1（对应 Phase 1 / `PR-1A` — 高危授权边界）
- **背景**：同一 QQ 直接重绑至**另一个游戏账号**时，当前代码保留 `auto_daily_enabled=1`，会未经用户同意对新游戏号自动签到（`AUD-002`）。
- **选项**：
  - **A（推荐）**：仅当 `(game_openid, game_uid)` 变更时自动重置 `auto_daily_enabled=0` 与旧 `daily_scope_v2`，同游戏号续绑 Cookie 保持原授权；完整保留 `action_runs` 与 `UNKNOWN_AFTER_ACTION` 保护。
  - **B**：无论是否同游戏号，每次重新绑定都一律重置为关闭。

### Decision 2（对应 Phase 3 / `PR-3B` — 高危写操作恢复机制）
- **背景**：社区浏览/点赞一旦进入 `UNKNOWN_AFTER_ACTION`，当前无任何恢复通道，会跨未来所有周期永久阻断该动作（`AUD-005`）。
- **选项**：
  - **A（推荐）**：严禁超时自动解锁与自动重放；新增**受权限保护的显式人工核实恢复命令**（如私聊 `/妮姬 日常 任务 确认恢复` 或仅管理员可用），记录审计日志后仅放行后续新周期、绝不补跑历史未决动作。
  - **B**：QQ 内不提供任何恢复入口，仅通过运维离线 CLI 脚本人工核销。

### Decision 3（对应 Phase 2 / `PR-2` — `#妮姬` 兼容与宿主 `wake_prefix` 隔离）
- **背景**：`main.py:53-56` 启动时向宿主全局 `wake_prefix` 注入 `"#"`，影响同宿主其他插件与对话（`AUD-018`）。
- **选项**：
  - **A（推荐）**：停止修改全局 `wake_prefix`，改在 `main.py` 使用插件级受控正则过滤器（仅拦截 `^\s*#(?:妮姬|nikke)(?:\s|$)`）转发至同一路由，在 AstrBot 矩阵验证无宿主污染且零配置兼容 `#妮姬`。
  - **B**：维持现状继续修改全局 `wake_prefix`。

### Decision 4（对应 Phase 2 & 3A — 公告命令对齐与双订阅去重）
- **4a. 公告子命令与 README 冲突（`AUD-022`）**：
  - **A（推荐）**：开放 `/妮姬 公告 语言|分类|搜索|诊断` 与管理员 `深度刷新` 路由（后端 `AnnouncementCommandHandler` 已实现），使代码与 `README.md` 一致。
  - **B**：保持仅开放基础 `/妮姬 公告`，同步清理 `README.md` 与后端不可达代码。
- **4b. 管理员 `公告 订阅` 与个人 `日程 订阅` 重叠推日历截止（`AUD-022`）**：
  - **A（推荐）**：解耦职责——管理员「公告订阅」只推官方公告本身，活动截止提醒统一归个人「日程订阅」，消除同群双重截止提醒。
  - **B**：保留现状并在文档提示双推冲突。

### Decision 5（对应 Phase 6 / `PR-6B` — 停用多源日历代码处置）
- **背景**：`features/calendar/` 约 ~2,800–3,200 行属于已停用的 GameKee 与官方公告日历源及跨源去重代码（`AUD-023`）。
- **选项**：
  - **A（推荐）**：完成四重依赖核查后，在 Phase 6 清理已确认无用的 GameKee/Official 日历源及空转跨源去重实现（保留源适配抽象与 Git 可溯历史），聚焦 BlaBlaLink 日历。
  - **B**：短期内计划恢复 GameKee 抓取，保留全部多源模块，仅修复当前 BlaBla 模式的 $O(N^2)$ 空转与 4 倍重复落盘。

### Decision 6（对应 Phase 6 / `PR-6A` — 静态大资产高保真压缩边界）
- **背景**：保留塔罗（139.25MB）与预渲染 Spine PNG（119.56MB）功能前提下，两类图片占仓库总体积近 80%（`AUD-023`）。
- **选项**：
  - **A（推荐）**：清理 56 个逐字节重复图标与 16.36MB 未用 OTF 字体；对塔罗采用高保真视觉抽检通过的压缩（兼容旋转逻辑），对 Spine 预渲染图仅做**保证解码像素零变化的无损 PNG 优化**（绝对保持 `nikke_portrait_anchor` 契约与画质）。
  - **B**：仅清理 56 个重复图标与未用 OTF，不改动塔罗与 Spine 图片文件。
