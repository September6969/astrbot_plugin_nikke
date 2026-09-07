# Healthz Readiness 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/healthz-readiness-v1`
- 主题：让 `/healthz` 反映绑定服务本地存储是否就绪。
- 就绪条件：SQLite 数据库文件和 `secret.key` 都是普通文件。
- 不涉及：读取密钥、执行 SQL、网络账号、部署、生产数据、消息发送和自动修复。

## 合同

```text
存储就绪 -> HTTP 200, {"ok": true, "storage": "ready"}
存储缺失或不是普通文件 -> HTTP 503, {"ok": false, "storage": "unavailable"}
```

响应只包含服务名、版本和聚合状态，不包含绝对路径、Cookie、QQ 或密钥内容；该端点可供 Caddy/容器健康检查使用。

## TDD 与验证

```text
pytest -q tests/test_healthz_readiness.py
4 passed
```

测试使用临时合成文件，覆盖就绪、缺失密钥、目录冒充文件和符号链接不跟随；没有现场部署或真实账号证据。
