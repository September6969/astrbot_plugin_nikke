# BUSINESS_COMPLETION_REPORT.md — Phase 2 最终集成候选复审与关门报告

> **基线与集成候选分支（2026-11-25）**
> - 上游 `origin/main`：`71e664f41d8a8b370887c10580069edb8f99e42a`（PR #141 & #142 已合并）
> - 最终集成候选分支：**`integration/phase2-candidate`**（PR **#150** → `--base main`：https://github.com/September6969/astrbot_plugin_nikke/pull/150 ）
>   - 覆盖链路：`PR #144–#149` 全部有效变更 + `65ba5f0`（独立复审 P1/P2）+ `2fff002`（Python 3.12 POSIX 管道与僵尸进程修复）+ `e749746`（实机 SoloRaid 补全与详情限流重试）+ 最终门禁收尾修复（进程树并发清理幂等/占槽/提前返回保存 `cleanup_error`、`feeds.py` 订阅时间界限过滤及脱敏文档修订）。
> - 真实服务器隔离只读验收记录见 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)。
> - 既有栈式 PR（#144–#149）与本地备份 worktree `9968a50` 均完整保留未破坏。

---

## 一、证据分层原则

本报告严格区分四类证据边界，拒绝将离线 Mock 或静态检查充当线上完整验收：
1. **代码实现与静态门禁**：源码架构约束（`scripts/audit/architecture_metrics.py --check`）、`mypy`、CodeQL 与 `compileall` 零报错。
2. **Linux CI 全矩阵自动验收**：Ubuntu 完整资源目录 + Playwright Chromium + Docker Spine 4.0/4.1 Worker，Python 3.12 / 3.13 × AstrBot `==4.24.0` / `>=4.24,<5` 全矩阵通过。
3. **部署服务器隔离只读验收（`ssh serv` + 实测有效样本账号 `***9910` + 生产 `nikke-t2i` + 真实 `nikke-calc@67835ca`）**：在不干扰生产库、不发 QQ 消息、不执行实号写操作前提下验证只读指令、14 张真实 T2I 截图、冷热 HTTP/缓存指标与进程树/生命周期回收（详见 [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md)）。
4. **受控降级 / 阻断 / 未线上触发边界（`DEGRADED` / `BLOCKED` / `NOT_TESTED`）**：`acct.shiftypad`、`tool.counsel`、可选外部导表、高风险写操作（签到/日常/CDK/续期）、公网网页及 QQ 群真实发送按要求保持默认关闭或由 Mock/CI 覆盖；提示参考 UID `84522455` 经全库只读检查未定位到对应记录，记为明确非阻塞未完成项。

---

## 二、Phase 2 独立复审、实机发现与最终收尾汇总

| 议题编号 | 关键代码落点 | 整改要点 | 测试与实机证据 |
|---|---|---|---|
| **P1-01 & 收尾 1 外部估伤引擎进程树生命周期** | [integrations/nikke_calc/engine.py](../../integrations/nikke_calc/engine.py), [adapters/astrbot/runtime.py](../../adapters/astrbot/runtime.py#L144-L148) | 解耦直属子进程 `returncode` 与进程树清理（Win32 Job Object + `taskkill` / POSIX `killpg` + `/proc/<pid>/stat` `Z`/`X`/`x` 僵尸过滤 + Python 3.12 `_wait_direct_exit`）；`pipe_drain_timeout` 防派生继承管道阻塞；`_cleanup_managed` 通过共享 `cleanup_task` + `asyncio.shield` 实现 `aclose()` 与 `finally` 真正并发幂等；`TimeoutError`/`_OutputLimitExceeded`/`OSError` 提前返回统一先执行 `_final_reap()` 再返回且保留 `cleanup_error`；`_drive()` 的 `collector_task` 在取消/超时时显式取消回收；清理失败时保留 `_leaked_handles` 且不放行并发槽位（直至后续 `aclose()` 重试成功后释放） | [tests/test_solo_raid_engine.py](../../tests/test_solo_raid_engine.py) 覆盖 10+ 组真实 OS PID 故障场景（在 `serv` Python 3.12.14 上 `2.53s` 通过，新增并发幂等/占槽/提前返回测试全过） |
| **P1-02 & 收尾 2 订阅按类型状态机与时间边界** | [features/announcement/feeds.py](../../features/announcement/feeds.py) | 独立维护 `uninitialized` / `initialized` / `initialized_unavailable` 三态防止长故障恢复倒灌；并在 `plan()` 中实际启用 `effective_floor = max(archive_floor, kind_subscribed_at || default_sub)` 过滤未见条目的 `published_at`，拦截订阅前发布（即使 14 天内）却在订阅后才迟到进入快照的内容，兼容缺 `kind_subscribed_at` 的旧记录并保留高版本更新投递 | [tests/test_announcement_feeds.py](../../tests/test_announcement_feeds.py) 含 14 天内订阅前迟到条目、多类型独立订阅时间与旧记录回退测试全过 |
| **P2-01 外部引擎版本固定基线 4 态可信度** | [integrations/nikke_calc/engine.py](../../integrations/nikke_calc/engine.py), [core/providers/toolbox.py](../../core/providers/toolbox.py) | `git_verified_pinned` / `self_reported_unverified` / `unverified` / `mismatch_or_dirty` 四态；生产默认 `require_git=True`，核验 `solo_raid_engine_names.json` 声明 `engine_commit` 与真实 `git rev-parse HEAD` / clean 状态 | [tests/test_solo_raid_engine.py](../../tests/test_solo_raid_engine.py) 全过；`serv` `67835ca` 标为 `Git 核验固定基线` |
| **实机 Defect 修复：已绑定名单补全 & 详情重试** | [application/commands/solo_raid.py](../../application/commands/solo_raid.py), [features/character/application.py](../../features/character/application.py) | 修复绑定账号 `GetUserCharacters` 缺 `burst`/`element`/`name_zh_cn` 导致 `1007(?)` 且未调用 `nikke-calc` 的缺陷；为 `GetUserCharacterDetails` Top-20 突发限流增加 `0.8s` 单次退避重试 | [tests/test_toolbox_commands.py](../../tests/test_toolbox_commands.py) 与 [tests/test_roster_option_summary.py](../../tests/test_roster_option_summary.py) 新增回归全过；`serv` 实号 5 队跑出 `1,813,859,815` |
| **P2-02 & 收尾 4 文档对齐与脱敏规范** | [CAPABILITY_MATRIX.md](./CAPABILITY_MATRIX.md), [DATA_SOURCE_REGISTRY.md](./DATA_SOURCE_REGISTRY.md), [REAL_ACCOUNT_ACCEPTANCE.md](../acceptance/REAL_ACCOUNT_ACCEPTANCE.md) | 修正 30 项总表口径为 **19 PASS / 5 DEGRADED / 2 BLOCKED / 4 NOT_TESTED**，区分完整真实业务/部分链路/Mock 三层验收，清除真实玩家昵称/联盟名/可关联个人细节与全部本机绝对路径，单列后续维护清单 | `docs/` 扫描 0 处本机路径或无关隐私残留 |
| **前序 ShiftyPad / 愿望单 / 校验器闭环** | [deploy/Caddyfile](../../deploy/Caddyfile), [wishlist_pool_eligibility.json](../../assets/data/wishlist_pool_eligibility.json), [validate_external_data.py](../../scripts/operations/validate_external_data.py) | `log_skip /shiftypad/*` & `/api/shiftypad/*`、`access_log=None`、`no-referrer`、171 SSR 准入 `fail-closed` 表及 5 类导入 Schema CLI 校验 | [tests/test_shiftypad_web.py](../../tests/test_shiftypad_web.py), [tests/test_wishlist_advisor.py](../../tests/test_wishlist_advisor.py), [tests/test_external_data_validator.py](../../tests/test_external_data_validator.py) 全过 |

---

## 三、外部阻塞、运维前提与后续事项

1. **`acct.shiftypad`（`BLOCKED`）**：维持 `enable_shiftypad_readonly=false` 默认关闭；未来部署上线前须先把 [`deploy/Caddyfile`](../../deploy/Caddyfile) 的 `log_skip /shiftypad/*` 同步至宿主机 `/opt/nikke-bot/caddy/Caddyfile`。
2. **`tool.counsel`（`BLOCKED`）**：未发现合法可再分发中文咨询题库，维持显式缺口提示。
3. **指定 UID `84522455` 核查结果**：对 `serv` 生产库全部 5 张表（含解密 Cookie/xcommon 键名与规范游戏身份键）及配置文件只读检索未定位到该 UID，其中第二条现有绑定记录已上游失效（`CookieExpired`），未擅自续期或换用他号继续线上测试。
4. **后续维护事项**：`char.roster` 突发并发限流策略优化、新主线/最新角色目录（`#5183–#5187`）同步、GitHub 冷素材预热及海外节点公告连接稳定性留待下一阶段迭代跟进。

---

## 四、合并顺序与回滚方案（本阶段停止门禁）

- **禁止直接先合并 PR #144 到 `main`**（含早期 CodeQL XSS 缺陷）。
- **推荐合入方式**：待人工审阅批准且 **PR #150（`integration/phase2-candidate`）** 最终 HEAD SHA 全部 12 项 CI 全绿后，合入 `main` 并关闭被其完全覆盖的栈式 PR（`#144`–`#149`）。
- **本阶段停止声明**：按门禁要求，本次**不合并 `main`**，**不开启 Phase 3–7（`/hall`、`/workspace`）开发**，等待人工批准合并 PR #150。
- **回滚方案**：若合入 `main` 后出现回归，执行 `git revert -m 1 <merge_sha>`（或 `git revert <squash_sha>`）退回 `origin/main` `71e664f`；运行期亦可通过保留的布尔配置开关即刻隔离高风险模块。
