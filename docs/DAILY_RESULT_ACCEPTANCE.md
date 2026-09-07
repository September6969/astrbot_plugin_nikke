# DailyTaskResult 状态合同验收记录

## 范围

本主题覆盖现有 `/妮姬 签到` 与 `/妮姬 签到 状态` 的签到结果建模，不新增点赞、浏览或其它社区写接口。

真实写操作仍受 `enable_daily_actions` 保护；本主题不访问真实账号、不执行签到、不发送消息、不部署。

## 状态合同

`DailyTaskResult` 使用以下结构化状态：

| 状态 | 语义 |
| --- | --- |
| `SUCCESS` | 写入后得到确认，或任务查询/汇总流程正常完成 |
| `ALREADY_DONE` | 今日已完成，或当前日任务运行已被同日幂等键领取 |
| `PENDING` | 任务存在但自动签到未启用，或只读查询确认待签到 |
| `FAILED` | 请求或本地流程失败，但不是已知限流、Cookie 失效或写后未知 |
| `RATE_LIMITED` | 响应明确表示频控/请求过频 |
| `COOKIE_EXPIRED` | 登录 Cookie 已失效，并同步标记本地账号状态 |
| `UNKNOWN_AFTER_ACTION` | 写操作结果未确认；不自动再次写入 |
| `UNAVAILABLE` | 当前响应没有可用签到任务 |

每日汇总持久化为 JSON-safe 的 `account_name/status/detail` 记录；旧的 tuple 或损坏记录不会被静默当作成功，而会触发重新读取。同日已有 `running/unknown/failed` 记录时，命令不会把它报告为“今日已执行”或自动重写；`pending/unavailable` 只表示读取未完成或任务暂缺，下一次调用可原子重检，不会伪装成成功。

## 离线证据

基于 `origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`：

- `tests/test_daily_result_contract.py`、`tests/test_daily_safety.py` 与 Daily 相关 core 回归：10 passed、2 warnings。
- 覆盖严格存储 round-trip、损坏记录拒绝、pending/unavailable 的状态保存与重检、unknown-after-action、rate-limited、CookieExpired 和不重复调用写接口。
- 完整 Python：264 passed、43 subtests、2 warnings；Node extension：3 passed；compileall 和 `git diff --check`：通过。

## 证据边界

- `READY_OFFLINE`：本地状态合同、现有签到主链映射、写后未知不重放和合成行为测试。
- `NEEDS_LIVE_EVIDENCE`：授权账号上的真实签到响应、真实写后状态变化、生产限流语义，以及点赞/浏览状态变化。
- 本主题不宣称社区日常产品整体完成。
