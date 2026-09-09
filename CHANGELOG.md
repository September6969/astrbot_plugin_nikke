# 更新记录

本文件记录当前仓库基线的可核对变更。未合并的 Draft PR 不计入当前版本，也不代表已发布或已部署。

## Unreleased — Spine-only Portrait & Card Calculation v2

- 角色官方立绘路径改为 canonical L2D/Spine；FB URL、FB cache 和 FB fallback 不再参与角色卡。
- Costume registry 升级为带来源字段的 Spine identity schema v2。
- 角色卡词条行增加 T1–T15 tier badge；HP/ATK/DEF 改由完整 verified 静态表计算器提供，缺输入时统一显示未知。

## 0.1.8（当前 main 基线）

- 完成 Profile V2 仪表盘的已核验字段展示，并保持未知、空值与零值语义可区分。
- 提供横版角色练度卡、角色资料、公告/日程、联盟突袭当前响应摘要、战役静态映射、塔层静态速查和本地攻略索引。
- 绑定服务使用受限 Cookie、单次令牌、HTTPS 公网地址和来源校验；Cookie 以加密形式保存。
- 社区签到、公告推送和 CDK 真实兑换均由独立开关保护；真实账号写操作、QQ 实际语音播放和 Spine 生产运行时仍需现场验收。
- 数据库与 `secret.key` 必须一起备份；示例 Caddy 配置不等于已部署或已完成生产验证。

## 发布前核对

- 版本号以 `_version.py` 的 `PLUGIN_VERSION` 为源，并必须与 `metadata.yaml` 一致。
- 配置项以 `_conf_schema.json` 为合同，默认值和安全边界见 [配置合同](docs/CONFIGURATION_ACCEPTANCE.md)。
- 必须通过 CI 的 Python 3.10/3.11/3.12 与 Node 检查；测试和合成预览不能替代真实账号、消息发送或部署证据。

## 2026-09-08 路线图收口补充

- PR #52/#53：正式 Spine 编排、官方 Spine 4.1 headless worker Docker 构建、受限 RGBA adapter、严格版本匹配和静态 FB/占位回退进入 main；服务器实构建、合法 bundle、生产许可和 benchmark 仍待现场证据。
- PR #54：Equipment/Cube/Favorite Item/Costume registry 统一来源、核验日期、SHA-256 和许可边界；`assets/costumes.json` 保持空表，不猜测服装映射。
- PR #55：Poke Voice 正式接入本地音频 → 精确证据映射的官方动态资源 → 文本回退；single-flight、4/5 秒预算、24 小时源缓存、ffprobe/ffmpeg 24kHz mono WAV 和生命周期回收已覆盖离线合同。
- 以上代码主题均已合并且当前无开放 PR；真实账号读取/写入、QQ Record 送达、生产部署、资源授权和服务器现场 runtime 仍未被离线证据替代。
