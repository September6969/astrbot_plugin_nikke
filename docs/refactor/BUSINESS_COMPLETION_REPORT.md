# BUSINESS_COMPLETION_REPORT.md — Phase 2 最终集成候选复审与关门报告

> **基线与集成候选分支（2026-11-25）**
> - 上游 `origin/main`：`71e664f41d8a8b370887c10580069edb8f99e42a`（PR #141 & #142 已合并）
> - 最终集成候选分支：**`integration/phase2-candidate`**（PR **#150** → `--base main`：https://github.com/September6969/astrbot_plugin_nikke/pull/150 ）
>   - 已验证核心逻辑、独立复审整改与实机缺陷修复提交 SHA：**`e7497462585c1ccf2eface1b628944dd76b799ab`**（`e749746`，前序：`164d3b6` → `65ba5f0` 独立复审 P1/P2 → `2fff002` Linux Python 3.12 POSIX 修复 → `e749746` 实机 SoloRaid 补全与详情重试）；本轮关门文档提交随后同步并触发最终全量 CI。
> - 真实服务器隔离只读验收记录见 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)。
> - 既有栈式 PR（#144–#149）与本地备份 worktree `9968a50` 均完整保留未破坏。

---

## 一、证据分层原则

本报告严格区分四类证据边界，拒绝将离线 Mock 或静态检查充当线上完整验收：
1. **代码实现与静态门禁**：源码架构约束（`scripts/audit/architecture_metrics.py --check`）、`mypy`、CodeQL 与 `compileall` 零报错。
2. **Linux CI 全矩阵自动验收**：Ubuntu 完整资源目录 + Playwright Chromium + Docker Spine 4.0/4.1 Worker，Python 3.12 / 3.13 × AstrBot `==4.24.0` / `>=4.24,<5` 全矩阵通过。
3. **部署服务器隔离只读验收（`ssh serv` + 真实有效账号 `***9910` + 生产 `nikke-t2i` + 真实 `nikke-calc@67835ca`）**：在不干扰生产库、不发 QQ 消息、不执行实号写操作前提下验证全链路只读指令、14 张真实 T2I 截图、冷热 HTTP/缓存指标与进程树/生命周期回收（详见 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)）。
4. **受控降级 / 阻断 / 未线上触发边界（`DEGRADED` / `BLOCKED` / `NOT_TESTED`）**：`acct.shiftypad`、`tool.counsel`、可选外部导表与高风险写操作（签到/日常/CDK/续期）及 QQ 群真实发送按要求保持默认阻断/关闭或由 Mock 覆盖。

---

## 二、Phase 2 独立复审、Follow-up 与实机整改汇总

| 议题编号 | 关键代码落点 | 整改要点 | 测试与实机证据 |
|---|---|---|---|
| **P1-01 外部估伤引擎进程树生命周期与跨平台清理** | [integrations/nikke_calc/engine.py](../../integrations/nikke_calc/engine.py), [adapters/astrbot/runtime.py](../../adapters/astrbot/runtime.py#L144-L148) | 将进程树生命周期与直属子进程 `returncode` 解耦：Windows 引入 `CreateJobObjectW`（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）+ `TerminateJobObject` + `QueryInformationJobObject` 校验及 `taskkill` 兜底；POSIX 采用 `start_new_session=True` + `os.killpg` + `_posix_pgid_has_live_processes`（读取 `/proc/<pid>/stat` 过滤容器 PID 1 未回收 `Z`/`X`/`x` 僵尸），并通过 `_wait_direct_exit` 消除 Python 3.12 `proc.wait()` 在派生子进程继承 `stdout`/`stderr` 时的阻塞；父退后残存管道先限短预算 `pipe_drain_timeout` 再强杀；清理以 `_run_uninterruptible` 包裹在 `async with semaphore:` 内；`aclose()` 先等待 `_spawning == 0` 再回收，清理异常上浮至 `cleanup_failures` | [tests/test_solo_raid_engine.py](../../tests/test_solo_raid_engine.py) 覆盖 9 组真实 OS PID 故障场景（在 `serv` Python 3.12.14 上 **8 passed in 2.53s**，Linux CI 3.12/3.13 全过） |
| **P1-02 订阅基线按类型状态机保护** | [features/announcement/feeds.py](../../features/announcement/feeds.py) | 拆分 `uninitialized` / `initialized` / `initialized_unavailable` 三态与 `kind_subscribed_at`，保证“新闻/视频/日程”单一来源长期不可用后首次恢复时先建基线不倒灌历史（>14 天归档亦不补推），并兼容缺 `kind_states` 的旧持久化记录；投递前复核 `enabled` 与在订 `kinds` | [tests/test_announcement_feeds.py](../../tests/test_announcement_feeds.py) 8 场景单测全过；`serv` 上 YouTube `ConnectError` 时实测安全建基线提示、`mock_sent=0` |
| **P2-01 外部引擎版本固定基线 4 态可信度** | [integrations/nikke_calc/engine.py](../../integrations/nikke_calc/engine.py), [core/providers/toolbox.py](../../core/providers/toolbox.py) | 引入 `git_verified_pinned` / `self_reported_unverified` / `unverified` / `mismatch_or_dirty` 四态；生产默认 `require_git=True`，联动核验 `solo_raid_engine_names.json` 声明 `engine_commit` 与实际 `git rev-parse HEAD` / clean 状态 | [tests/test_solo_raid_engine.py](../../tests/test_solo_raid_engine.py) 4 态全测；`serv` 克隆 `67835ca` 标示为 `Git 核验固定基线` |
| **实机验收 Bug 修复：已绑定名单目录补全 & 详情限流重试** | [application/commands/solo_raid.py](../../application/commands/solo_raid.py), [features/character/application.py](../../features/character/application.py) | 修复绑定账号拉取 `GetUserCharacters` 缺 `burst`/`element`/`name_zh_cn` 导致 `1007(?)` 且不触发 `nikke-calc` 的问题；为 `GetUserCharacterDetails` Top-20 并发突发的 `request too frequently` 增加 `1` 次退避重试 | [tests/test_toolbox_commands.py](../../tests/test_toolbox_commands.py) 与 [tests/test_roster_option_summary.py](../../tests/test_roster_option_summary.py) 新增回归测试全过；`serv` 实号计算 **`1,813,859,815`** 并出图 |
| **P2-02 文档路径与能力数一致性修正** | [CAPABILITY_MATRIX.md](./CAPABILITY_MATRIX.md), [DATA_SOURCE_REGISTRY.md](./DATA_SOURCE_REGISTRY.md), [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md) | 修正能力总表数量描述为 `30 项`，明确区分代码就绪 / CI / 实机验收状态，清除全部本机工作树绝对路径链接并替换为仓库相对路径，同步最新提交 SHA | 全仓 `docs/` 零本机绝对链接残留 |
| **前序 ShiftyPad / 愿望单 / 校验器闭环** | [deploy/Caddyfile](../../deploy/Caddyfile), [wishlist_pool_eligibility.json](../../assets/data/wishlist_pool_eligibility.json), [validate_external_data.py](../../scripts/operations/validate_external_data.py) | `log_skip /shiftypad/*` & `/api/shiftypad/*`、`access_log=None`、`no-referrer`、171 SSR 准入 `fail-closed` 表及 5 类导入 Schema CLI 校验 | [tests/test_shiftypad_web.py](../../tests/test_shiftypad_web.py), [tests/test_wishlist_advisor.py](../../tests/test_wishlist_advisor.py), [tests/test_external_data_validator.py](../../tests/test_external_data_validator.py) 全过 |

---

## 三、完整自动化 CI 与实机验收摘要

### 3.1 PR #150 GitHub Actions CI 状态（代码提交 `2fff002` 与 `e749746` 已验证，最终文档提交将继续同步全绿）
- `Test (Python 3.12, AstrBot ==4.24.0)`：**PASS**
- `Test (Python 3.12, AstrBot >=4.24,<5)`：**PASS**
- `Test (Python 3.13, AstrBot ==4.24.0)`：**PASS**
- `Test (Python 3.13, AstrBot >=4.24,<5)`：**PASS**
- `Static gates (architecture + mypy)`：**PASS**
- `Spine 4.0 headless worker build`：**PASS**
- `Extension (Node)`：**PASS**
- `CodeQL` + `Analyze (actions / c-cpp / javascript-typescript / python)`：**PASS**
- *Spine Phase 3A candidate dry-run (manual only)*：*skipping*（仅 `workflow_dispatch` 手动任务）

### 3.2 服务器隔离只读与 T2I 视觉验收结论
- 在 `ssh serv` 隔离容器运行中完成 `***9910`（186 名妮姬）全套只读命令验收、**14 张真实 `nikke-t2i` 卡片像素与视觉检查**、真实 `nikke-calc@67835ca` 5 队计算（`1,813,859,815`）、`RuntimeCoordinator` 逆序清理（`survivors=[]`、`lingering_nikke_calc_procs=[]`、`sqlite_integrity="ok"`）及故障注入。完整逐项实据载于 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)。

---

## 四、外部阻塞与运维前提

1. **`acct.shiftypad`（`BLOCKED`）**：缺少授权 ShiftyPad 测试凭据；启用前除配置开关外还须确认宿主机 Caddy 同步 [`deploy/Caddyfile`](../../deploy/Caddyfile) 的 `log_skip /shiftypad/*` 规则。
2. **`tool.counsel`（`BLOCKED`）**：未发现合法可再分发中文咨询题库；维持显式缺口提示与导入器 `license` 校验。
3. **可选外部导表与实号写开关（`DEGRADED` / `NOT_TESTED`）**：`sync_level_cost_table_path`、`solo_raid_season_path`、`overload_recommendations_path` 缺省时均按合法降级模式运行；`enable_daily_actions`、`enable_cdk_redemption`、`enable_announcement_push`、`enable_public_share_api`、`arena_web_enabled` 保持默认关闭。

---

## 五、合并顺序与回滚方案（本阶段停止门禁）

- **禁止直接先合并 PR #144 到 `main`**（含早期 CodeQL XSS 缺陷）。
- **推荐合入方式**：由人工审阅并批准 **PR #150（`integration/phase2-candidate`）**，在最终 HEAD SHA 全部 12 项 CI 确认通过后以 **Squash & Merge** 或 **Merge Commit** 合入 `main`，并关闭被覆盖的中间栈式 PR（`#144`–`#149`）。
- **本阶段停止声明**：按“先业务，后交互”门禁要求，本次**不合并 `main`**，**不开启 Phase 3–7（`/hall`、`/workspace`）开发**。
- **回滚方案**：若合入 `main` 后出现回归，执行 `git revert -m 1 <merge_sha>`（或 `git revert <squash_sha>`）一键回退至 `origin/main` `71e664f`；运行期亦可通过保留的布尔配置开关即刻热熔断高风险模块。
