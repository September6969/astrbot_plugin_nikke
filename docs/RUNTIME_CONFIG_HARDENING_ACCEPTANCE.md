# Runtime Config Hardening 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/runtime-config-hardening`
- 主题：配置数值与持久化调度时间的边界保护
- 用户可见变化：非法或损坏的数值配置回退到安全默认值；单个损坏的调度字段不再让调度循环退出。
- 不涉及：默认写开关、网络请求合同、真实账号、消息发送、部署、数据库迁移和 UI 渲染。

## 合同

| 字段 | 合法范围 | 非法语义 |
| --- | --- | --- |
| `request_timeout` | 1–300 秒整数 | 回退 `20` |
| `web_port` | 1–65535 整数 | 回退 `6210` |
| `daily_hour` / `summary_hour` | 0–23 整数 | 分别回退 8 |
| `daily_minute` / `summary_minute` | 0–59 整数 | 分别回退 10 / 30 |
| `max_concurrency` | 1–32 整数 | 回退 `2` |

布尔值、浮点值、容器、空字符串、坏字符串和越界整数均视为非法；未涉及的配置键保持原值。持久化调度值按字段独立回退，不将损坏值静默解释为 0。

## 行为证据

先行红测：

```text
pytest -q tests/test_runtime_config.py
1 failed, 1 passed（集成测试复现 ValueError: invalid literal for int()）
```

实现后：

```text
pytest -q tests/test_runtime_config.py
3 passed, 2 warnings
```

持久化字段读取本身抛出 `TypeError` / `ValueError`（例如损坏 JSON）时，配置边界层只回退该字段；同一时钟的另一个字段仍按其独立合同解析。

本轮针对最终 head 的本地回归：Python 3.10.11 专项 `3 passed`、全量 `259 passed`、43 subtests、2 warnings；Python 3.13.13 专项 `3 passed`、1 warning。Python 3.13 全量仍会触发既有的 33 个 Windows `WinError 32` 临时 SQLite 清理失败（PR #19 尚未合并），不属于本主题配置行为失败。

## 远端验收证据

- 功能实现提交 `e0ac0c823c9b10274ee91edecfe22cf01ff33178` 的 CI run `34101656392`：四个 job 全部 `SUCCESS`。
- 后续验收记录提交 `639aa38102a8ca43fc9f1b68d9a6736f94ce65b5` 的 CI run `34102014940`：四个 job 全部 `SUCCESS`。
- 当前分支最终 head、对应 CI run 和 Draft PR 状态以 `docs/ROADMAP_LEDGER.md` 与 PR #20 checks 为权威来源，避免在本记录中复制会过期的快照。

专项回归结果为 `14 passed, 3 failed`；3 个失败均在测试清理 `NikkeStore` 临时目录时触发 Windows `WinError 32`，属于基线 SQLite 文件句柄问题（该问题由独立 PR #19 修复，本分支未吸收未合并提交），不是本主题配置行为失败。Linux CI 将作为最终跨版本证据。

本主题仅修改配置读取和调度边界，没有 UI/图片输出，因此无合成预览要求；未访问真实账号、未发送消息、未部署。
