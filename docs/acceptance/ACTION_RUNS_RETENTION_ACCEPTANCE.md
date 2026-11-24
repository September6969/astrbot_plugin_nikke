# action_runs 保留清理验收记录（PR-6B G7-misc-dead-f2）

## 范围与安全边界

`scripts/operations/prune_action_runs.py` 是离线、默认只读的运维工具，不修改 `core/storage.py`，也不新增 `NikkeStore` 删除接口（红线 2：高危存储改动不混入结构清理 PR）。

只有同时满足下列条件的记录才会进入计划：

1. `action` 属于白名单，且 `status` 属于该动作的终态：
   - `daily` / `signin`：`success`、`failed`、`expired`、`unavailable`；
   - `daily_notice`：`success`、`failed`；
   - `community_action`：`VERIFIED`、`NOT_SENT`；
   - `community_automation_notice`：`SENT`、`FAILED`。
2. `run_key` 完整匹配该动作的**当前**格式；旧版北京时间或 QQ 作用域键、无法解析的键一律保留。
3. 运行键中的 UTC 周期日期早于“今天 − N 天”（默认 N=30，最少 7），且 `created_at` 同样早于 N 天（`transition_run(refresh_created_at=True)` 会刷新它，因此周期日期是主门槛）。
4. 同一账号作用域、同一周期内不存在任何受保护记录；否则该周期的终态记录也保留，供人工核实。

永不删除：`DISPATCH_INTENT`、`DISPATCHED`、`UNKNOWN_AFTER_ACTION`、`ACKNOWLEDGED_UNKNOWN`、旧版 `running` / `unknown`、`pending`、`precheck_expired`、`precheck_failed`；以及整个 `community_account_lease`（执行租约）、`cdk`、`session_renewal`、`session_renewal_window`、`community_reward`（永久幂等守卫）动作。

计划阶段以 SQLite `mode=ro` 打开；输出只含按 action/status 汇总的计数，不含运行键、QQ 号或 detail。`--apply` 在单个 `BEGIN IMMEDIATE` 事务中按 `(run_key, action, status, created_at)` 条件删除，计划后状态变化的记录跳过。

## 运维步骤

1. 停止插件；
2. 运行 `scripts/operations/upgrade_preflight.py` 并用 `scripts/operations/backup_nikke_data.py` 生成 `nikke.sqlite3` + `secret.key` 成对备份（见 UPGRADE_ROLLBACK_PREFLIGHT_ACCEPTANCE.md）；
3. `python scripts/operations/prune_action_runs.py --data-dir data/nikke` 预览计划；
4. 审阅计数后追加 `--apply`（可用 `--older-than-days N` 调整，N ≥ 7）。

本 PR 未在真实 `data/nikke` 运行 `--apply`；`tests/test_action_runs_retention.py` 使用合成数据库覆盖白名单、全部受保护类别、旧格式键、近期记录、周期上下文保留、计划与应用间状态变化、当前周期预算不变及 CLI 默认只预览。

## 待所有者决定

- `session_renewal_window` 记录永久停留在 `DISPATCH_INTENT`（24 小时频率标记），按红线保留，每账号每天至多 1 行；是否作为文档化例外清理需另行批准。
- `pending`、`precheck_*` 与 CDK/社区奖励终态记录 v1 一律保留。
