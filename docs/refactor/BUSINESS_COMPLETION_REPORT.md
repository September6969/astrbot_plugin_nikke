# BUSINESS_COMPLETION_REPORT.md — Phase 1–2 业务完善关门报告

> **基线与分支栈（2026-11-24）**
> - `origin/main`：`71e664f`（已合入 PR #141 与 PR #142）
> - 本次栈式 PR 序列（未改动本地备份 worktree `E:/_codex_work/nikkehub-ds` `9968a50`）：
>   1. **PR #144** (`feat/p1a-compliant-baseline` @ `82bee36` → `main`)：数据合规审查、基线整合、按领域拆分 Handler
>   2. **PR #145** (`feat/p1b-security-isolation` @ `225d83e` → `feat/p1a-compliant-baseline`)：P0 安全、身份隔离与外部估伤引擎隔离加固
>   3. **PR #146** (`feat/p1c-soloraid-wishlist` @ `1f41f56` → `feat/p1b-security-isolation`)：单人突袭五队编组与外部估伤纠偏、愿望单按企业官方规则重构
>   4. **PR #147** (`feat/p1d-calc-tools` @ `7c8a7c8` → `feat/p1c-soloraid-wishlist`)：咨询精确/模糊/覆盖提示、同步器即时可升、超限跨部位累计与概率重洗、`container.py` 重复参数修复
>   5. **PR #148** (`feat/p1e-events-grid` @ `2edddfc` → `feat/p1d-calc-tools`)：卡池未分类计数分离、个人订阅与全群广播语义澄清、本命九宫格统一 T2I 与人气榜 O(1) 缓存
>   6. **Phase 2 Gate** (`docs/p2-business-completion-gate` → `feat/p1e-events-grid`)：关门审计报告、能力矩阵与数据源登记

---

## 一、证据分层原则（严格区分三类状态）

本报告严格区分以下三类证据，不把代码实现或离线 Mock 测试当作真实线上验收：
1. **代码已实现（Code Complete）**：生产代码与架构边界已落地并通过静态检查（`architecture_metrics.py --check` / `compileall`）。
2. **离线 / Mock / CI 自动化已验证（Offline / CI Verified）**：本地 `pytest`（纯 Mock/离线夹具）与 GitHub Actions CI 矩阵实测通过，并标明本机 Windows 稀疏检出工作树未覆盖的资产测试范围。
3. **真实环境 / 真实账号未实测或受外部阻塞（Unverified / Blocked Live）**：依赖真实玩家凭据、未验证上游匿名接口、合法外部授权题库或真实 QQ 群推送/宿主运行时的能力，必须在上线前于受控环境中单独验收。

---

## 二、P0 / P1 审计缺口（`GAP-01`–`GAP-11`）关闭汇总

| 缺口编号 | 问题描述 | 归属 PR | 关键代码落点 | 当前验收层 | 剩余限制 / 待实测项 |
|---|---|---|---|---|---|
| `GAP-01` | 无开源许可 NikkeHub 数据集不得入公开仓 | PR #144 | 剔除 `counsel_bank.json`、`sync-level-costs.json`、`overload_recommendations.json`、`solo_raid_seasons.json`；仅保留 MIT 衍生映射 `assets/data/solo_raid_engine_names.json` 与 `LICENSE-nikke-calc.txt` | 代码完成 + PR #144 CI Python 矩阵通过 | 需通过合规渠道补充中文咨询题库与完整 1–200 级成本表 |
| `GAP-02` | ShiftyPad 会话安全漏洞 + 第三方公开接口开关缺失 | PR #145 | `integrations/web/shiftypad_service.py`（一次性 token → Cookie 会话 + CSRF/Origin + `frame-ancestors 'none'` + 16KB 限体 + `web.RequestKey`）；`features/shiftypad/{storage,identity}.py`；`core/config.py` 新增默认关闭 `enable_shiftypad_readonly`、`enable_public_share_api`；`application/commands/shiftypad.py` 增加 `nikke-api.pages.dev` 传输披露与 `确认` 门禁 | 离线/Mock 单元测试全过 | `integrations/shiftypad/official.py` 上游 `User/GetUserProfile` 尚未用本人授权测试账号实测；`nikke-api.pages.dev` 线上连通性未实时探测 |
| `GAP-03` | 养成历史跨账号污染、清库遗漏与并发回写 | PR #145 | `features/growth/history.py`、`features/character/application.py`、`application/commands/{profile,character,growth}.py` 按 `(actor, canonical_game_identity)` 隔离；增加 `clear_generation` 防并发反回写；`/妮姬 养成历史 清空` 同步清空 `roster_growth`；修复 `None` 转 `0` 假差异与同日覆盖 `changes`；支持 `query_range` | 离线单元测试通过 | 真实长周期多账号切换数据累积待生产观察 |
| `GAP-04` | `nikke-calc` 子进程隔离与单人突袭 Weak/Label/Version 错误 | PR #146 | `features/solo_raid/builder.py` 改用 `boss.weakness` 与全别名归一化；`integrations/nikke_calc/engine.py` 改为事件循环共享信号量、最小 env 白名单、进程组强杀、`MAX_OUTPUT_BYTES`、批次总超时、独立 `git rev-parse HEAD` / `git status --porcelain`（禁止静默回填 `PINNED_COMMIT`）、补齐 `resource_id` 查表；`features/solo_raid/plans.py` 持久化真实 `damage_model_label` | 离线 fake runner 单元测试通过 | 需在部署机对真实 `Jgaram/nikke-calc@67835ca` 检出执行实测 |
| `GAP-05` | 愿望单违背企业分组、160 墙（误计 SR）与普通池准入规则 | PR #146 | `features/wishlist/advisor.py`、`application/commands/calc_tools.py` 重构为仅 SSR、排除 SR/R 与 `ABNORMAL`、按 `ELYSION`/`MISSILIS`/`TETRA`/`PILGRIM` 5 槽分组、SSR-only 160 墙突破计数、手工输入走 `CharacterDirectoryResolver` 别名解析、自然数字排序 | 离线单元测试通过 | 限时/联动限定池清单随版本迭代需定期核对 `character_master.json` |
| `GAP-06` | 咨询答案查询中文 0 命中且无授权题库 | PR #144 + PR #147 | 移除无许可韩文题库分发；`features/counsel/bank.py` 显式区分 `exact`/`partial`/`ambiguous`/`none` 并在输出提示覆盖条目数、许可标注及禁止编造 | 离线单元测试通过 | 功能标记 **BLOCKED**（等待合法中文授权题库导入） |
| `GAP-07` | 本命九宫格双套损坏布局与排行榜 N+1 | PR #148 | `adapters/astrbot/command_presentation.py` 退役 `write_grid_png` 生产回退（T2I 失败时返回 `None` 交由命令层文本回退）；`templates/t2i/favorite_grid.html` 改为 `1080×1080` 非裁切固定 3×3 网格 + 清晰字体；`ui/renderers/favorite_grid_png.py` 标为废弃；`features/favorite_grid/grid.py` 引入 `COUNTS_KEY` O(1) 聚合计数 | 离线测试 + Edge `1080×1080` 视觉截图实测通过 | 携带真实本地立绘图的 T2I 渲染待部署机有全量资源时验收 |
| `GAP-08` | 三套订阅语义混淆与卡池板 `unclassified` 误计 | PR #148 | `features/calendar/board.py` 分离 `group is None` 与筛选过滤；`features/announcement/feeds.py` 去除重复 `_state()` 读取；清晰区分 `/妮姬 新闻 订阅`（个人）、`/妮姬 日程 订阅`（24h 个人提醒）与管理员 `enable_announcement_push`（全群广播） | 离线单元测试通过 | 真实 QQ 群主动推送与时间窗调度需线上宿主机验收 |
| `GAP-09` | 超限洗词条未跨 4 部位累计、盲锁与生产固定 `seed=0` | PR #147 | `features/overload_advice/advisor.py` 新增 4 部位 `matched_counts` 累计、低阶（`<= 5/15`）锁定提示与每件蓝石头消耗计算 `1 + locked_in_slot`；生产模拟改用 `random.SystemRandom()` (`seed=None`) 且同件未锁行整体重洗；接入可选绑定账号对比（`账号[:角色]`）并修复 `core/container.py` 重复 `card_loader` | 离线单元测试 + `create_container()` 集成测试通过 | 未绑定真实线上装备数据时仍依赖用户手工传参 |
| `GAP-10` | 同步器缺 1–200 级与当前库存直接可升估算 | PR #147 | `features/sync/{cost_table,calculator}.py` 新增 `gainable_levels()` 与 `SyncLevelPlan.{reachable_level,gainable_levels}`、覆盖区间提示与手工补录引导；补齐更新器往返校验单测 | 离线单元测试通过 | 仍不猜测未导入等级成本，需导入合法完整成本表或手工输入三项累计成本 |
| `GAP-11` | `toolbox.py` 过载整合与 PR #142 / 架构门禁协调 | PR #144 | 按领域拆分为 `application/commands/{shiftypad,growth,solo_raid,calc_tools,info_feeds,favorite_grid}.py` + `adapters/astrbot/toolbox_routes.py`；保留 PR #142 8 类帮助导航；`architecture_metrics.py` 保持热点限额零违规 | 本地 + PR #144 CI 静态门禁全过 | — |

---

## 三、自动化验证与环境边界实录

### 3.1 PR-1D/PR-1E 修复后核心业务矩阵验证（本地 Windows Worktree + Junction）
在 `docs/p2-business-completion-gate` 最新基线（含 `core/container.py` `7c8a7c8` 与 `tests/test_announcement_feeds.py` `2edddfc` 修复）执行 22 个核心测试文件：
- **Pytest 结果**：`144 passed, 29 subtests passed`（耗时 `7.52s`，`exit 0`），覆盖：
  - `test_main_refactor_integrity.py`（验证 `create_container()` 装配与字段完整）
  - `test_announcement_feeds.py`、`test_calendar_board_view.py`、`test_calendar_subscriptions.py`、`test_informationfeeds.py`
  - `test_favorite_grid.py`、`test_toolbox_commands.py`、`test_toolbox_runtime.py`
  - `test_overload_advice.py`、`test_counsel_bank.py`、`test_sync_level_calculator.py`、`test_wishlist_advisor.py`
  - `test_solo_raid_engine.py`、`test_solo_raid_five_teams.py`、`test_growth_history.py`
  - `test_shiftypad_{web,readonly_store,identity,command,shared_readonly}.py`、`test_public_share_profile.py`、`test_release_metadata.py`
- **静态架构门禁**：`python scripts/audit/architecture_metrics.py --check` 返回 `exit 0`（`gate_violations: []`，`main.py` 283/300，`core/container.py` 260/350）。
- **视觉截图验证**：Headless Edge `1080×1080` 实图渲染 `templates/t2i/favorite_grid.html`，确认 3×3 网格居中、P1–P9 徽章与长角色名可读且底行无裁切。

### 3.2 本地全量运行（PR-1D/1E 修复前全仓扫描 `task-1295`）精确记录与限制说明
本机工作树为 Windows **sparse-checkout** 环境（仅本地检出 `assets/data` 与 `assets/guides`，不含 `assets/blablalink`、`assets/fonts`、`assets/tarot`、`assets/icons`、`assets/mappings` 等大型资源目录），且未安装本地 Playwright Chromium 浏览器；在 `core/container.py` 与 `test_announcement_feeds.py` 修复前曾跑过一次全量 258 文件测试：
- **原始结果**：`2238 passed, 156 failed, 21 skipped, 649 subtests passed`。
- **156 个失败的逐类归因**：
  1. **2 类可修复回归（已在本序列修复并在 3.1 复测通过）**：`test_main_refactor_integrity.py::test_container_creation_and_fields`（已于 PR #147 `7c8a7c8` 修复）与 `test_announcement_feeds.py` 2 条断言（已于 PR #148 `2edddfc` 修复）。
  2. **其余 153 项为本机工作树/系统环境限制（非业务代码回归）**：
     - 稀疏检出缺失资源目录（`assets/blablalink`、`assets/fonts`、`assets/tarot`、`assets/icons`、`assets/mappings`），对应测试已包含在 GitHub Actions 完整检出环境中；
     - Windows 非管理员创建符号链接权限（`WinError 1314` in `test_guide_application_contract.py[symlink_outside]`）；
     - Windows 多线程并发 `os.replace` 写锁冲突（`WinError 5` in `test_upstream_source_hardening.py::test_concurrent_cache_saves_never_corrupt_the_file`）；
     - 本地缺少 Playwright Chromium 可执行文件（`test_arena_web.py` 等浏览器端到端用例）。

### 3.3 GitHub Actions CI 状态说明
- **PR #144**（base=`main`，`82bee36`）：
  - **通过**：`Test (Python 3.12, AstrBot ==4.24.0)`、`Test (Python 3.12, AstrBot >=4.24,<5)`、`Test (Python 3.13, AstrBot ==4.24.0)`、`Test (Python 3.13, AstrBot >=4.24,<5)`、`Static gates (architecture + mypy)`、`Extension (Node)`、`Analyze (actions / c-cpp / javascript-typescript / python)`。
  - **失败**：`CodeQL`（因 PR #144 携带 `9968a50` 原始 `shiftypad_service.py:298` Reflected XSS，已在 PR #145 重写为 Cookie+CSRF+无内联 CSP 模板消除）及 `Spine 4.0 headless worker build`。
- **PR #145–#148**：由于 `.github/workflows/ci.yml` 仅对 `branches: [master, main]` 的 `pull_request` 触发工作流，栈式分支在基准改为 `main` 前显示 `no checks reported`；按栈序合并或将 base 切至 `main` 时将自动触发完整 CI 矩阵（含完整 `assets/` 与 Chromium 浏览器测试）。

---

## 四、真实环境 / 生产部署前仍须完成的外部验收清单

1. **ShiftyPad 上游公开接口契约验证**（`acct.shiftypad` — 当前状态 `BLOCKED`）：需用管理员授权的测试账号实测 `https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile` 匿名响应字段、状态码及频率限制。
2. **第三方分享 API 与代理安全**（`misc.public_share`）：上线前若开启 `enable_public_share_api`，需确认 `https://nikke-api.pages.dev` 可达性及隐私披露合规；反代与 `web_trusted_proxy_ip` 需在线上 HTTPS 实网复验。
3. **咨询中文授权题库引入**（`tool.counsel` — 当前状态 `BLOCKED`）：当前内置韩文表已清空停用，须接入经授权合法的中文题库后再激活查询实用性。
4. **外部 `Jgaram/nikke-calc` 引擎实机试跑**（`combat.solo_raid`）：部署机需克隆指定 commit `67835ca3033a95482749ea2db35a8ee2a0856a92` 并保持工作区干净，实跑真实赛季 JSON 验证子进程预算与输出。
5. **BlaBlaLink 实号接口与 QQ 群主动推送**（`comm.daily_tasks_cdk`、`event.calendar`、`event.announcement`、`event.news_feeds`）：在授权测试账号与测试 QQ 群实测绑定、23 次/批量练度接口（`AUD-010`）、签到/CDK `UNKNOWN_AFTER_ACTION` 恢复确认与日程/公告主动投递。

---

## 五、Phase 2 关门结论与 Phase 3–7 进入边界

- Phase 1A–1E 全部已规划业务修复、安全隔离与数据合规改造已通过栈式 PR #144–#148 交付并完成离线/架构验证。
- 除受外部授权/上游契约阻塞的 `acct.shiftypad` 与 `tool.counsel` 保持显式阻断与优雅降级外，其余功能均具备清晰配置开关、绑定门禁与可验证离线基线。
- **按“先业务，后交互”原则，Phase 3–7（公共功能大厅 `/hall` 与个人指挥官工作台 `/workspace` 网页开发）在本 Phase 2 关门报告审阅批准前保持暂停，待确认后启动。**
