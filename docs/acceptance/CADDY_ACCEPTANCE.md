# Caddy 反代示例验收记录

## 安全合同

- `deploy/Caddyfile` 只作为 Caddy 示例配置，不代表已在任何真实主机部署。
- `/bind/{token}` 使用一次性绑定令牌；示例默认不启用 HTTP access log，避免 URL 路径令牌进入反代日志。
- 反代目标是容器网络内的 `astrbot:6210`，宿主机不应发布 6210。
- 示例保留 HTTPS、HSTS、`nosniff`、禁止 iframe、无 referrer 和隐藏 Server 标头。
- `deploy/docker-compose.caddy.yml` 只发布 80/443（含 HTTP/3 UDP 443），Caddyfile 以只读方式挂载；Caddy 与 AstrBot 使用外部 `nikke-bot` 网络。
- 如果部署者需要访问日志，必须先完成令牌路径、查询参数和授权头的隐私过滤评审；本 PR 不声称该现场配置已经完成。

## 离线验证

`tests/test_deployment_config.py` 直接读取当前示例文件，验证访问日志关闭、安全头、反代目标、只读挂载和没有 6210 宿主机端口映射。测试不启动 Docker/Caddy，也不进行真实部署或公网访问。
