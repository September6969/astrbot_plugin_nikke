# NIKKE 综合助手

面向 AstrBot + NapCat/OneBot 的 BlaBlaLink 账号练度查询插件。当前版本是早期测试版，建议由具备 Docker 和反向代理经验的机器人维护者部署。

## 功能状态

已实现：

- Chrome/Edge MV3 扩展辅助绑定，密码和验证码只提交给 BlaBlaLink 官网。
- Cookie 加密存储、十分钟单次绑定令牌和每个 QQ 独立会话。
- 指挥官资料、等级、部队战力、注册时间、同步器、前哨、主线/部落塔、模拟室超频、战术学院、回收室研究及收藏计数查询。
- 技能等级、突破、核心、装备词条和 AEL 数据整理。
- NIKKE 风格图片卡、每日账号健康检查与群汇总框架。
- 中文精简指令、英文旧指令兼容，以及受独立开关保护的国际服 CDK 兑换。
- 单角色练度使用 1800×1000 横版角色海报，展示立绘、核心属性、模块化养成、四件装备卡和完整词条汇总；只请求目标角色详情。
- 公告/日程查询接入官网 InformationFeeds（默认英文 NEWS 最近 10 条），支持全文读取、磁盘缓存降级和独立内容/日程版本；日期解析仍为启发式。
- 联盟突袭总览及当前响应内伤害排名；主线通关史查询使用官网静态关卡 ID，覆盖 3,572 项普通/困难关卡。
- 无需绑定账号的塔层静态速查，覆盖 7,350 个公开塔层；不是玩家进度或通关保证。
- 批量 CDK 逐码持久化、同账号互斥和不确定结果保护；动态后台任务在关闭时统一回收。
- 本地授权攻略索引，以及默认关闭的 OneBot 戳一戳语音框架（实际 QQ 播放尚待验收）。

尚未完成或默认禁用：

- 社区签到和奖励领取尚未通过真实写接口验收，写操作默认关闭。
- CDK 兑换已接入官方 BlaBlaLink 接口，但公开配置默认关闭，必须使用授权账号验收后开启。
- 面谈、完整魔方/收藏品查询、图片和 JSON 导出未完成；塔层仅提供静态数据。
- 不宣称完整赛季排名、成员身份关联、最近一刀或剩余次数已验证。公告自动推送已接线，默认关闭，真实消息发送尚未验收。
- Spine 仍为实验框架，真实渲染与 Linux 基准未完成，需要运行时许可确认。
- Prydwen、NIKKE.gg 等未明确授权的攻略正文不会复制到本项目。

## 安全边界

- 插件和扩展不保存账号密码。
- 扩展仅能访问 `*.blablalink.com` 与配置的绑定域名。
- 服务端只接受 BlaBlaLink 域 Cookie，并限制名称、数量、单项和总长度。
- 诊断日志只记录 Cookie 名称、接口名、业务码和响应字段，不记录 Cookie 值。
- 默认只能在私聊中生成绑定链接，避免群成员抢先使用链接提交账号。
- 自动点赞、关注、浏览和资料修改均未实现。
- 社区签到和领奖属于写操作，默认关闭；在真实账号契约测试完成前只检查登录状态。
- CDK 不写入日志或数据库；仅保存不可逆摘要和脱敏结果。群聊发送兑换命令仍会向群成员公开原始兑换码。

## 最小部署

要求：AstrBot `>=4.24,<5`、Python 3.10+、可访问 BlaBlaLink 的网络，以及 HTTPS 域名。

1. 将目录放入 `AstrBot/data/plugins/astrbot_plugin_nikke`。
2. 安装 `requirements.txt` 中的依赖并重启 AstrBot。
3. 持久化 AstrBot 的 `data/nikke` 目录；其中包含数据库和 `secret.key`，两者必须一起备份。
4. 将插件配置 `public_base_url` 改为自己的 HTTPS 域名。
   自建域名请从自己站点的 `/download` 下载扩展；该 ZIP 会按 `public_base_url` 生成站点权限。修改域名后重启插件并重新安装扩展，GitHub 通用发布包仍对应默认站点。
5. 使用 Caddy/Nginx 将公网 HTTPS 反代到 AstrBot 容器网络中的 `6210` 端口。
6. **不要**把 `6210`、AstrBot 后台或 NapCat 后台直接映射到公网。
7. 在 QQ 中发送 `/妮姬 帮助`，再私聊发送 `/妮姬 账号 绑定` 完成绑定。

若绑定域名在本地代理下出现 `SSL_connect error 5`，可从 [GitHub Releases](https://github.com/September6969/astrbot_plugin_nikke/releases) 下载同一扩展包；不要关闭浏览器证书校验。

仓库中的 `deploy/Caddyfile` 和 `deploy/docker-compose.caddy.yml` 是示例。Caddy 与 AstrBot 必须加入同一个 Docker 网络；这种布局下插件在容器内监听 `0.0.0.0:6210`，但宿主机不发布该端口。

最小 Caddy 配置：

```caddyfile
nikke.example.com {
    reverse_proxy astrbot:6210
}
```

## 常用命令

夜间开发新增入口：

- `/妮姬 公告`、`/妮姬 日程`：公开公告及可解析日程。
- `/妮姬 公告 订阅`、`/妮姬 公告 取消订阅`：仅机器人管理员管理当前会话。需另外开启 `enable_announcement_push`，默认不会发送；失败退避 5 分钟，截止提醒为 24/6/1 小时。
- `/妮姬 攻略 练度 2`：按本地授权索引分页，每页最多 3 项。
- `/妮姬 联盟突袭 排名`：当前响应范围内排名。
- `/妮姬 战役 46-14A-1`：指定已映射关卡通关史。
- `/妮姬 塔层 极乐净土 1`：静态层数据，不访问账号。
- `/妮姬 语音 开` 或 `关`；`/妮姬 语音 语言 en`；`/妮姬 语音 角色 rapi`。
  语音默认为关，`assets/voices/registry.json` 默认为空；只使用管理员有权使用的本地音频。

研究来源和限制见 [证据记录](docs/evidence/overnight.md)，阶段结果与诊断方式见 [夜间开发报告](docs/OVERNIGHT_REPORT.md)。

- `/妮姬 帮助 [账号|查询|日常]`：查看精简菜单。
- `/妮姬 账号 [绑定|状态|解绑|汇总 开|关]`：管理自己的账号。
- `/妮姬 我的`：查看指挥官资料、同步器、前哨和主线进度。
- `/妮姬 查询 练度 [角色名]`：查看练度总表或单个角色练度。
- `/妮姬 查询 资料 <角色名>`：查看角色基础资料。
- `/妮姬 签到`：执行签到；`/妮姬 签到 状态` 只读查询。
- `/妮姬 兑换 <CDK>`：使用当前绑定账号真实兑换国际服 CDK。

旧版 `/nikke bind`、`status`、`me`、`roster`、`character`、`info`、`daily`、`claim`、`cdk`、`push` 和管理员指令继续兼容。管理员中文入口为 `/妮姬 管理`。

签到由 `enable_daily_actions` 控制，CDK 兑换由独立的 `enable_cdk_redemption` 控制；两项公开默认值均为 `false`。

如确实需要在可信群中生成链接，可将 `allow_group_bind` 设为 `true`；不建议对公开群开启。

## 常见故障

### `MetaData no user account`

先确认官网个人页可以看到 NIKKE 等级和战役数据，再重新安装最新版绑定扩展并创建新链接。扩展只读取浏览器实际会发送给 BlaBlaLink 子域的 Cookie，且只观察请求头，不读取密码、请求体或响应内容。扩展会优先捕获官网请求中的 `x-common-params`；新版官网若暂未发出该请求，则使用 `game_openid/game_gameid` 生成最小只读上下文。

管理员可检查 AstrBot 日志中的 `[NIKKE诊断]` 行。日志只包含接口名、业务码、响应字段和 Cookie 名称；不要要求用户发送 Cookie 值或 Cookie-Editor 导出文件。

### HTTPS 或扩展请求失败

- 确认 DNS 指向服务器，云安全组开放 TCP 80/443。
- 确认 Caddy 与 AstrBot 位于同一 Docker 网络。
- 访问 `https://你的域名/healthz`，应返回 `ok: true`。
- 扩展跨域请求只允许来自 Chrome/Edge 扩展页，不再使用 `Access-Control-Allow-Origin: *`。

### 容器迁移后无法解密

必须同时迁移 `data/nikke/nikke.sqlite3` 和 `data/nikke/secret.key`。密钥应保持 `600` 权限，丢失后旧 Cookie 无法恢复，只能让用户重新绑定。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖令牌超时与单次消费、Cookie 加密、来源过滤、跨站 CORS、账号隔离基础行为、`game_openid`/正式 `intl_openid` 恢复、AEL 计算、单角色定向查询、四槽装备词条解析、1800×1000 单角色卡、资源缓存和缺图回退，以及 25 人汇总卡。模拟测试不能替代授权账号的真实端到端验收。

单角色卡的图片缓存位于 `data/nikke/cache/`，自定义图片与来源配置见 [素材说明](assets/README.md)。首次查询可能需要下载立绘；下载失败仍生成占位卡。总览与“我的”卡片沿用原模板。

在插件父目录运行 `python -m astrbot_plugin_nikke.scripts.preview_character_cards --output <预览目录> --remote`，可用脱敏样例生成爱丽丝、小红帽和缺图预览，不访问真实账号。

## 许可证与来源

本项目采用 GPL-3.0-or-later。部分 API 适配和算法基于
[ExiaProject/ExiaInvasion](https://github.com/ExiaProject/ExiaInvasion) 移植，详见 `NOTICE`。
