# NIKKE 长期路线台账

更新时间：2026-09-08。本文件是路线图状态摘要，不是运行时状态源；每次恢复前仍须重新 fetch、核验 GitHub PR/CI、工作树和未提交状态。

## 当前基线

本轮按依赖顺序将已授权的待合并 PR 收口到 `main`。当前最终 SHA、PR 状态与 CI 以 GitHub 实时查询为准；本文件中的 SHA 仅是本次提交生成前的记录，不得替代下一次核验。

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

## 证据边界

- `READY_OFFLINE` 只表示本地合同、行为测试、合成输出或离线预览已验证。
- `NEEDS_LIVE_EVIDENCE` 仍包括真实账号 Profile/Raid 字段兼容、Daily 写入后的真实状态、Voice 实际播放送达、Spine 生产运行时/许可、真实远端素材负载和部署环境图片。
- 未接线模块、mock/fixture、合成 PNG、公开只读访问和静态代码检查不得冒充产品完成、真实联调、消息发送或资源授权。
- 本轮没有访问真实账号、执行账号写入、发送消息、部署、修改 main 工作树、force push、删除分支或修改 ruleset。

## 后续工作

下一主题必须从届时最新 `origin/main` 建立独立 worktree、branch 和 Draft PR，并先写清字段合同、请求预算、异常语义、测试和证据缺口。已合并主题不得通过旧 overnight 分支恢复；需要现场动作时，只记录最小授权动作并等待明确授权。
