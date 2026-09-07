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
2 passed, 2 warnings
```

专项回归结果为 `14 passed, 3 failed`；3 个失败均在测试清理 `NikkeStore` 临时目录时触发 Windows `WinError 32`，属于基线 SQLite 文件句柄问题（该问题由独立 PR #19 修复，本分支未吸收未合并提交），不是本主题配置行为失败。Linux CI 将作为最终跨版本证据。

本主题仅修改配置读取和调度边界，没有 UI/图片输出，因此无合成预览要求；未访问真实账号、未发送消息、未部署。
