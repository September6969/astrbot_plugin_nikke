# 配置合同与安全边界

配置 schema 位于 `_conf_schema.json`。下表与 schema 的 15 个键保持一致；默认值由 AstrBot 配置层提供，插件代码只在缺失时使用相同回退值。

| 配置键 | 默认值 | 作用与边界 |
| --- | --- | --- |
| `public_base_url` | `https://nikke.irises777.xyz` | 绑定公网 HTTPS 地址；必须是无账号、路径、查询参数的站点地址。 |
| `web_host` | `0.0.0.0` | 容器内监听地址；不代表应将端口直接暴露到公网。 |
| `web_port` | `6210` | 绑定服务容器端口；公网访问应经过 HTTPS 反向代理。 |
| `binding_api_key` | 空字符串 | 创建绑定会话的 Bearer 密钥；为空时禁用该接口，不应提交到 Git。 |
| `allow_group_bind` | `false` | 是否允许群聊生成绑定链接；公开群开启会增加链接被抢用风险。 |
| `daily_hour` | `8` | 北京时间每日任务小时。 |
| `daily_minute` | `10` | 每日任务分钟。 |
| `summary_hour` | `8` | 北京时间每日汇总小时。 |
| `summary_minute` | `30` | 每日汇总分钟。 |
| `request_timeout` | `20` | BlaBlaLink 请求超时秒数。 |
| `spine_worker_path` | 空字符串 | 可选的官方 Spine 4.1 headless worker 绝对路径；为空时只使用静态 FB 回退。 |
| `spine_runtime_version` | `4.1` | worker 严格匹配的 Spine major.minor；未知或不匹配 bundle 不执行。 |
| `spine_worker_timeout` | `4` | 单次 worker 最大秒数，配置范围 1–5。 |
| `voice_dynamic_enabled` | `true` | 仅启用 `assets/voice_poke_map.json` 中有来源证据的官方动态语音；空映射或关闭时回退本地音频/文本。 |
| `max_concurrency` | `2` | 每日账号任务最大并发数；应按上游频控和部署容量调整。 |
| `enable_daily_actions` | `false` | 社区签到/领奖写操作开关；未完成真实授权验收前保持关闭。 |
| `enable_announcement_push` | `false` | 公告推送总开关；开启也不代表已完成真实消息发送验收。 |
| `enable_cdk_redemption` | `false` | 国际服 CDK 真实兑换开关；群聊会公开兑换码，必须由管理员明确开启。 |

## 迁移与发布边界

- 修改 `public_base_url` 后必须重启插件并重新安装对应绑定扩展；不能把默认站点 ZIP 当作任意自定义域名授权。
- `data/nikke/nikke.sqlite3` 与 `data/nikke/secret.key` 必须一起备份；不能通过配置迁移替代离线备份。
- 本文档只核对本地 schema 和代码默认值，不声称配置已在真实部署或账号上联调。
