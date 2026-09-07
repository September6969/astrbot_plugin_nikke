# 每账号自动签到开关验收记录

## 范围

本主题为现有签到链新增本地 `accounts.auto_daily_enabled` 偏好。账号默认关闭；只有定时批处理和因遗漏触发的汇总补跑，才会同时筛选 `push_enabled=1` 与 `auto_daily_enabled=1`。

用户可通过 `/妮姬 日常 自动 开|关` 管理自己的偏好。该命令仅更新 SQLite；手动 `/妮姬 签到` 及管理员明确的批处理保持既有选择语义。

## 离线行为合同

| 场景 | 预期 |
| --- | --- |
| 旧账号或新账号 | `auto_daily_enabled=0`，不会因升级自动加入定时写操作 |
| 设置“自动 开/关” | 仅变更本地字段；全局写开关关闭时明确提示不会提交 |
| 定时签到 | 同时要求账号每日汇总与自动签到均开启 |
| 汇总补跑 | 使用与定时签到相同的自动筛选，不能绕过账号偏好 |
| 手动签到/管理员执行 | 不由自动偏好阻止；仍受既有全局写开关、幂等和安全合同约束 |

## 证据边界

- 定向回归：`tests/test_daily_auto.py`、`tests/test_daily_safety.py` 与 `tests/test_core.py` 为 48 passed、4 subtests、2 warnings。
- 完整 Python：263 passed、43 subtests、2 warnings；Node extension：3 passed；compileall 与 `git diff --check`：通过。
- `SYNTHETIC_VERIFIED`：SQLite 升级默认值、账号筛选、命令路由、全局关闭时的无提交提示、定时与汇总筛选。
- `NEEDS_LIVE_EVIDENCE`：授权账号在真实调度时间下的可见行为与真实签到响应；本主题没有访问账号、执行签到、发送消息或部署。
- Like/Browse 没有接入，也不因该偏好字段宣称可自动执行。
