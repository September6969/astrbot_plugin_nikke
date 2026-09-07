# Daily Evidence P1 验收记录

## 范围

- 分支：`feat/daily-evidence-p1`
- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 实现提交：`920f938`；当前验收 head：`37cab4c`（Draft PR #18）
- 本增量只加固现有每日签到路径的状态闭环，不猜测 Like/Browse 的未核实端点、字段或任务完成语义。

## 行为合同

- 启用签到写操作时，先持久化 `daily` 与 `signin` intent，再进行 profile/task 读取；不会先读后记 intent。
- 新的签到 action 仍由客户端执行“写前读取 → 单次 POST → 写后读取”；异常结果不自动重发。
- 重启后遇到 `daily` 或 `signin` 的 `running`/`unknown` 记录，只允许只读核验：已完成则收敛为 `success`，仍未完成则收敛为 `unknown`。
- 只读核验遇到 Cookie 失效时，相关 intent 收敛为 `expired`；不遗留可被误认为可重放的 `running`。
- 该增量不改变 CDK 的显式重试合同，也没有访问真实账号或执行真实写操作。

## 行为验证

```text
pytest tests/test_daily_recovery.py tests/test_daily_safety.py \
  tests/test_core.py::ClientTests::test_daily_signin_checks_before_and_after_write \
  tests/test_core.py::ClientTests::test_daily_signin_skips_completed_task \
  tests/test_core.py::ClientTests::test_1300015_retries_are_bounded
9 passed
```

新增 4 个恢复/顺序行为测试覆盖：intent 先于读取、running daily 只读恢复、running signin 未确认时进入 unknown、Cookie 失效收敛。另有 `compileall`、Node extension contract tests（3 passed）和 `git diff --check` 通过。

GitHub Actions final-head CI：run `34098386067`，Node、Python 3.10、3.11、3.12 全部通过。

本机全量 pytest 结果为 `240 passed, 32 failed, 31 subtests passed`；失败均集中在 Windows `TemporaryDirectory` 清理 `nikke.sqlite3` 时的 `WinError 32` 文件占用，目标增量测试和相关签到测试均通过。最终全量回归仍以 Draft PR 的隔离 CI 为准。

## 未覆盖与证据边界

- 未实现 Like/Browse 写入闭环；公开 SDK/端点存在不等于已确认 DailyTask 语义。
- 未执行真实账号访问、真实签到、消息发送、公开资源下载、部署或生产 DB 操作。
- 未把模拟 client、离线状态恢复或本机合成测试宣称为 live evidence。
