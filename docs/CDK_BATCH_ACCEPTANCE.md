# CDK 批量持久幂等验收记录

## 范围

用户命令：`/妮姬 兑换 批量 <CDK1> <CDK2> ...`。

本主题只核对批量路径的逐码持久执行合同，不执行真实兑换、不访问真实账号、不发送消息，也不修改默认关闭的 `enable_cdk_redemption` 配置。

## 当前实现合同

- 单次最多 10 个 code；批量串行执行，并与单条兑换共享账号锁。
- 主命令把同一个 `NikkeStore` 传入 `CdkService.redeem_batch()`。
- 每个 code 的持久键为 `cdk:{qq_id}:{game_uid}:{SHA256(code)}`；明文 code 不进入 `action_runs.detail`。
- `success`、`terminal`、`unknown` 是终态，不由重复批量隐式重放。
- `failed`、`expired` 仅允许原子重领；`running` 不抢占，超过 120 秒先转换为 `unknown`。
- `CookieExpired` 或频控会中止剩余 code；取消会保存 `unknown` 后继续传播取消信号。
- 服务层将小于 1 秒的 delay 钳制为 1 秒；这不是生产频控结论。

## 离线证据

在 Python 3.10.11、`E:\DevCache\nikke-test-venv` 环境，以 `origin/main@bada0b3` 为基线：

- `tests/test_cdk.py`、`tests/test_cdk_persistence.py`、`tests/test_cdk_stale_runs.py`、`tests/test_review_cancellation.py`：42 passed、12 subtests、2 warnings。
- 覆盖批量上限/最小间隔、跨调用复用 success、unknown 不重放、终态与可重试态矩阵、过期 running 隔离、跨 Store 原子转换、同账号锁和取消传播。
- `python -m compileall -q cdk_service.py cdk_models.py storage.py main.py`：通过。
- 完整 `pytest -q`：256 passed、43 subtests、2 warnings；Node extension test：3 passed；全量 compileall 和 `git diff --check`：通过。
- GitHub Actions CI 在提交后作为最终门禁；本记录不把离线结果冒充真实接口验收。

## 状态边界

- `READY_OFFLINE`：逐码 action_runs 幂等、unknown 防重放、失败/过期原子重领和批量停止语义已有代码与行为测试证据。
- `NEEDS_LIVE_EVIDENCE`：授权账号上的真实兑换响应、生产频控/间隔、历史包体字段和错误分布。
- `NEEDS_HUMAN_DECISION`：是否在真实账号契约验收后开启公开 CDK 写操作。
