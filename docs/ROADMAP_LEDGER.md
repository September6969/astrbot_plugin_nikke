# NIKKE 长期路线台账

更新时间：2026-09-08。本文件是路线图状态摘要，不是运行时状态源；每次恢复前仍须重新 fetch、核验 GitHub PR/CI、工作树和未提交状态。

## 当前基线

本轮按依赖顺序推进独立 Draft PR。本次核验时 `origin/main` 为 `c4f1755a50903f7d47ac8904715b61c880c4605b`；恢复任务时仍须重新核验。

## 本轮已合并主题

| 主题 | 结果 |
| --- | --- |
| Post-Merge Sync / Profile V2 | 已合并；Profile 命令离线闭环、字段语义、分区去重和合成预览均有记录；真实账号与部署证据仍未执行 |
| Registration / storage / migration / runtime / shutdown | 已合并；注册 API、连接生命周期、事务迁移、配置边界和幂等回收按依赖顺序落地 |
| Health / backup / cache / deployment preflight | 已合并；健康诊断、备份、清理、Caddy 示例、升级前置检查与发布元数据保持只读/离线边界 |
| Raid / campaign / tower / CDK | 已合并；数值与响应合同、快照和批次幂等语义有行为测试；不宣称真实账号联调 |
| Announcement / daily / voice / character / spine | 已合并；字段合同、状态语义、动态资源边界与日志证据已进入主线；公开资源和合成数据不等于授权或生产证据 |
| Asset lifecycle | 已合并；同键 single-flight、跨实例远端下载槽位、有限预取和 campaign 共享 manager 已组合验证，未宣称真实远端负载或全链路生产 N+1 证据 |
| Log privacy / evidence docs | 已合并；异常、Cookie 上下文和动态日志净化，并保留现场证据登记、需求矩阵与 Profile 状态边界 |
| v4 F1/F2 CDK success contract / no replay | 已合并 PR #41，merge `553b8731668b588fdf8d54a87b083156dc5f30fc`；严格成功字段、持久 claim、unknown-after-action 与单条/批量共享原语均有行为测试 |
| v4 F3/F4 Daily identity / migration-safe recovery | 已合并 PR #42，merge `2a2df3587c9c437437f94483a2f55defabda7151`；按稳定游戏身份分区，旧 QQ 记录保守阻断，缺失任务可安全重试；未执行真实签到 |
| v4 F5 costume-aware cache | 已合并 PR #43，merge `d35bbef94e8c955011608509f17586c185ec3fd0`；default/known/unknown/invalid 分离，远端与本地缓存键保持 costume 语义；未验证真实资源负载 |
| v4 F6 recoverable backup | 已合并 PR #44，merge `9d35655f9f73ba3517d0c9e9a20ac5128794b504`；只读密钥/数据库校验、SQLite backup API、隔离暂存、完整性与加密字段恢复验证已由 CI 覆盖 |
| Offline Raid “我的” | 已合并 PR #45，merge `7b1b07cd89b1b5dbac20bf03f2f162b0b22b65c1`；使用绑定 `game_openid` 精确筛选当前响应、无 N+1、保留完整赛季与 canonical identity 现场缺口 |

## 证据边界

- `READY_OFFLINE` 只表示本地合同、行为测试、合成输出或离线预览已验证。
- `NEEDS_LIVE_EVIDENCE` 仍包括真实账号 Profile/Raid 字段兼容、Daily 写入后的真实状态、Voice 实际播放送达、Spine 生产运行时/许可、真实远端素材负载和部署环境图片。
- Raid “我的”目前只证明了离线的精确 `game_openid` 筛选和当前响应文案；尚未证明响应 `openid` 与绑定身份的现场 canonical 关联，也不把返回条数当作真实出刀次数。
- 未接线模块、mock/fixture、合成 PNG、公开只读访问和静态代码检查不得冒充产品完成、真实联调、消息发送或资源授权。
- 本轮没有访问真实账号、执行账号写入、发送消息、部署、修改 main 工作树、删除分支或修改 ruleset。P4 分支曾因修正已推送提交的 EOF 使用一次 `--force-with-lease`，未触及 main 或其他分支；随后已改为普通提交并保持线性历史。

## 后续工作

下一主题必须从届时最新 `origin/main` 建立独立 worktree、branch 和 Draft PR，并先写清字段合同、请求预算、异常语义、测试和证据缺口。已合并主题不得通过旧 overnight 分支恢复；需要现场动作时，只记录最小授权动作并等待明确授权。当前 v4 离线主题已收口，后续先重新核验状态再选择下一个独立主题。

## FB 静态立绘路线（进行中）

- P0 静态 FB / Costume 主链：`feat/fb-static-mainline-v1`，从 `origin/main@c4f1755a50903f7d47ac8904715b61c880c4605b` 建立；已补 costume 字段贯通、严格空映射清单和普通路径零 Spine 合同，状态 `READY_OFFLINE`，PR #47 CI 全绿。
- Costume 实际映射及完整角色目录覆盖：`NEEDS_LIVE_EVIDENCE`；没有制造映射，也没有把可构造 URL 当作远端存在性证据。
- P1 卡片视觉：PR #48 CI 全绿；P1 Item/Cube 完整性：PR #49 CI 全绿；P2 Guide/Help 素材：PR #50 CI 全绿；P4 Spine 隔离：PR #51 CI 全绿；均保持 Draft、以 `main` 为基线，按 #47 → #48 → #49/#50 → #51 评审/合并。
- Raid / Campaign / Tower 既有离线主题已在当前 main 基线中具备合同、fixture 和行为测试；真实 canonical identity、赛季范围和账号进度仍标为 `NEEDS_LIVE_EVIDENCE`，本轮未重复制造现场证据。
- 真实账号、QQ 发送与部署保持未授权/未执行。
