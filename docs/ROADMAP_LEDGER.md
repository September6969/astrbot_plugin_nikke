# NIKKE 长期路线台账

更新时间：2026-09-08。本文件是路线图状态摘要，不是运行时状态源；每次恢复前仍须重新 fetch、核验 GitHub PR/CI、工作树和未提交状态。

## 当前基线

本轮按依赖顺序推进独立 Draft PR。本次核验时 `origin/main` 为 `44266cad2cbc31f95b46ee7fb342c9c19c231f89`；恢复任务时仍须重新核验。

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
| Spine 正式编排基础 | 已合并 PR #52，merge `44266cad2cbc31f95b46ee7fb342c9c19c231f89`；正式 runtime 注入、bundle 白名单/缓存、严格版本匹配、队列和 PNG 回退进入主线 |

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
- P1 单角色练度卡最终版：`feat/character-card-final-v1`；完成非透明像素三色主题、企业低透明水印、属性弱 accent、Abnormal 深紫黑、装备图标放大和六张合成预览，状态 `READY_OFFLINE`，PR #48 CI 全绿。
- P1 卡片视觉：PR #48 已合并；P1 Item/Cube 完整性：PR #49 已合并；P2 Guide/Help 素材：PR #50 已合并；P4 Spine 隔离：PR #51 已并入当前 main。本轮正式 Spine backend 从最新 main 独立建立，不回退已合并隔离提交。
- Raid / Campaign / Tower 既有离线主题已在当前 main 基线中具备合同、fixture 和行为测试；真实 canonical identity、赛季范围和账号进度仍标为 `NEEDS_LIVE_EVIDENCE`，本轮未重复制造现场证据。
- 真实账号、QQ 发送与部署保持未授权/未执行。
## 六项 Guide / Help（已合并）

- `feat/guide-assets-v1` 从 `origin/main@c4f1755a` 独立建立；六类路由、16 个图片输出、红球白名单链接、哈希清单与授权 caption 已接入，状态 `READY_OFFLINE`，PR #50 已合并。
- 已逐张查看处理副本；真实 QQ 压缩、送达和部署仍为 `NEEDS_LIVE_EVIDENCE`，本主题未执行发送或部署。
## Favorite Item / Cube 完整性（已合并）

- `test/item-resource-integrity-v1` 从 `origin/main@c4f1755a` 独立建立；补齐未登记、404、超时、损坏缓存与解码失败行为证据，状态 `READY_OFFLINE`，PR #49 已合并。
- 未发现带来源证据的新映射，故没有扩充当前 4 个 Favorite Item / 8 个 Cube 清单；完整覆盖仍为 `NEEDS_LIVE_EVIDENCE`。
## Spine 正式后端（当前独立主题）

- `feat/spine-formal-backend-v1` 从 `origin/main@492e1f56` 独立建立；根目录实现正式依赖注入、版本匹配、bundle 白名单缓存、后台队列、版本化 PNG 与 FB/占位回退，`experimental/` 仅保留兼容导出层。
- 编排层与合成 adapter 测试状态 `READY_OFFLINE`；具体 runtime、真实 bundle/素材许可、Linux headless 和 benchmark 状态为 `NEEDS_LIVE_EVIDENCE`，不因缺少现场证据阻塞离线开发。
- 角色卡热路径只消费已有 L2D 索引，不为每个角色单独刷新索引；Spine cache miss 不同步等待，当前请求继续静态 FB/几何 fallback。

## Spine 4.1 headless worker / Costume（当前独立主题）

- `feat/spine-runtime-costume-v1` 从合并后的 `origin/main@44266cad2cbc31f95b46ee7fb342c9c19c231f89` 建立；没有复用旧 formal worktree。
- 新增 `runtime/spine_worker` 的 C++/SDL worker、Docker 构建文件和 Python 受限 CLI adapter。构建默认锁定官方 `spine-runtimes` 4.1 commit `77a5db0ec6d16331f5efbaa7662bba9355bd3424`；官方源码与二进制不入库。
- AstrBot 主入口已支持通过 `spine_worker_path`、`spine_runtime_version`、`spine_worker_timeout` 可选接线；配置为空或 worker 不存在时保持静态 FB/占位回退。共享 `data/nikke/cache/spine-bundles`，worker 无账号 header、仅 dummy/software SDL。
- `assets/costumes.json` 当前仍为空；没有可核验的 API costume ID → Nikke-DB asset ID 证据，因此不制造映射。default/known/unknown/invalid 状态隔离由现有 provider 与行为测试覆盖。
- Python adapter 离线测试已通过 12 项（worker RGBA 协议、路径越界、坏输出、超时、配置接线及 formal backend）；官方 Linux 编译、合法 bundle 实渲染、benchmark 和服务器恢复后的现场证据仍为 `NEEDS_LIVE_EVIDENCE`，不可由合成测试替代。
