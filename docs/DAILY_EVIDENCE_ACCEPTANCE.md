# Daily Evidence P1 验收记录

## 范围

- 分支：`feat/daily-evidence-p1`
- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 实现提交：本次状态修正后的 PR #18 final head；以对应 CI 为准（Draft PR #18）
- 本增量只加固现有每日签到路径的状态闭环，不猜测 Like/Browse 的未核实端点、字段或任务完成语义。

## 行为合同

- 启用签到写操作时，先持久化 `daily` 与 `signin` intent，再进行 profile/task 读取；不会先读后记 intent。
- 新的签到 action 仍由客户端执行“写前读取 → 单次 POST → 写后读取”；异常结果不自动重发。
- 重启后遇到 `daily` 或 `signin` 的 `running`/`unknown` 记录，只允许只读核验：已完成则收敛为 `success`，仍未完成则收敛为 `unknown`。
- `signin` 已是终态 `success`/`expired`/其它终态时不进入恢复读取、不重发写请求，也不把终态改写成 `unknown`；缺失的 `daily` 记录只继承已持久化结果。
- 只读核验遇到 Cookie 失效时，相关 intent 收敛为 `expired`；不遗留可被误认为可重放的 `running`。
- 执行中的 `CancelledError` 将已持有的 `daily`/`signin` intent 收敛为 `unknown` 后继续传播取消信号；不会把取消当作成功，也不会在重启后自动重发。
- 该增量不改变 CDK 的显式重试合同，也没有访问真实账号或执行真实写操作。

## 行为验证

```text
pytest tests/test_daily_recovery.py tests/test_daily_safety.py \
  tests/test_core.py::ClientTests::test_daily_signin_checks_before_and_after_write \
  tests/test_core.py::ClientTests::test_daily_signin_skips_completed_task \
  tests/test_core.py::ClientTests::test_1300015_retries_are_bounded
11 passed
```

新增 6 个恢复/顺序行为测试覆盖：intent 先于读取、running daily 只读恢复、running signin 未确认时进入 unknown、终态 success 保持不被恢复读取改写、Cookie 失效收敛、取消收敛为 unknown 并继续传播。另有 `compileall`、Node extension contract tests（3 passed）和 `git diff --check` 通过。

本机 Python 3.10.11 全量 pytest 结果为 `262 passed, 2 warnings, 43 subtests`；按本文件命令执行的专项签到与恢复测试为 `11 passed, 2 warnings`；Node extension tests（3 passed）、compileall 与 `git diff --check` 通过。

本次代码修正 push 后不复用旧 head 的绿灯；最终以 Draft PR #18 新 head 对应 CI 为准。

本文件不预写本次 docs-only 提交产生的新 SHA；push 后以 PR #18 的实时 `headSha` 与对应 CI 检查作为最终交接证据。

## 未覆盖与证据边界

- 未实现 Like/Browse 写入闭环；公开 SDK/端点存在不等于已确认 DailyTask 语义。
- 未执行真实账号访问、真实签到、消息发送、公开资源下载、部署或生产 DB 操作。
- 未把模拟 client、离线状态恢复或本机合成测试宣称为 live evidence。
