# 更新记录

本文件记录当前仓库基线的可核对变更。未合并的 Draft PR 不计入当前版本，也不代表已发布或已部署。

## 0.2.0（当前 main 基线）

- 全量支持 200 名可玩妮姬的语音角色设定与查询，支持简繁中文、英文、代码与 resource_id 解析。
- 正式接入已核验的 40 套官方服装切换，实施严格所有者匹配，拒绝未核验皮肤与跨角色借用。
- 官方语音统一采用日文（`ja`）作为产品默认语言，合法语言严格限制为 `ja`、`en`、`ko`，移除未登记的 `zh-cn`。
- 戳一戳互动接入 Lobby_Touch 1..3 多台词动态选取，全链路纯音频发送，彻底移除捏造文本台词兜底。
- 正式 Spine 4.0 与 4.1 生产级 headless worker 投产，角色立绘采用默认待机动作首帧（`t = 0.0`），隔离 setup pose。
- 完整接入 CharacterStatCalculator 与真实 Lv.526 静态面板零误差核验，OL 词条全面对齐 4×3 槽位与 1–15 阶展示。
- 修复过载装备百分比数值被 100 倍放大显示的问题（#73）。
- 新增 `custom_character_aliases` 配置项，支持用户配置自定义角色别名并与内置表无缝合并（#74）。

## 0.1.8

- 完成 Profile V2 仪表盘的已核验字段展示，并保持未知、空值与零值语义可区分。
- 提供横版角色练度卡、角色资料、公告/日程、联盟突袭当前响应摘要、战役静态映射、塔层静态速查和本地攻略索引。
- 绑定服务使用受限 Cookie、单次令牌、HTTPS 公网地址和来源校验；Cookie 以加密形式保存。
- 社区签到、公告推送和 CDK 真实兑换均由独立开关保护；真实账号写操作、QQ 实际语音播放和 Spine 生产运行时仍需现场验收。
- 数据库与 `secret.key` 必须一起备份；示例 Caddy 配置不等于已部署或已完成生产验证。

## 发布前核对

- 版本号以 `_version.py` 的 `PLUGIN_VERSION` 为源，并必须与 `metadata.yaml` 一致。
- 配置项以 `_conf_schema.json` 为合同，默认值和安全边界见 [配置合同](docs/CONFIGURATION_ACCEPTANCE.md)。
- 必须通过 CI 的 Python 3.12/3.13 测试矩阵、静态门禁（mypy 与架构指标）与 Node 检查；测试和合成预览不能替代真实账号、消息发送或部署证据。

## 2026-11-22 REFACTOR V2 系统性重构（PR-0 → PR-6C）

- 分支链 `refactor-v2/*`，基线 `ab610f5`（PR #128），尚待合并；合并前不代表已发布或已部署。逐 PR 提交、关闭的 AUD 项与四重核查清单见 [FINAL_DELIVERY.md](docs/refactor/FINAL_DELIVERY.md) 的「REFACTOR V2 交付记录」。
- 安全与数据：同一 QQ 仅在换绑到不同游戏身份时重置自动授权；绑定会话竞态与密钥原子创建修复；绑定页轮询、可信反代 CIDR、输入校验与日志脱敏加固；`SCHEMA_VERSION` 保持 3，无需迁移。
- 命令：统一尾参解析（多词角色名、空格/换行批量 CDK）；`#妮姬` / `#nikke` 改为插件级入口，不再修改宿主 `wake_prefix`；开放 `/妮姬 公告 语言|分类|搜索|诊断|深度刷新`；帮助首页、分类与详解共用单一数据源；全部既有 QQ 命令与 `/nikke` 平铺别名保持可用。
- 日常：执行租约按进程代次与 10 分钟超时安全回收；`UNKNOWN_AFTER_ACTION` 仍绝不自动解锁或重放，新增私聊两步 `/妮姬 日常 任务 确认恢复 [确认]`（审计留痕，只放行之后的新周期）；日常与汇总按社区日（UTC）调度。
- 日程与公告：月度/活动 Pass 精确分类、时间语义修正；管理员公告订阅只推官方公告，截止提醒归个人日程订阅；日程源只保留 BlaBlaLink（GameKee/官方公告日程源已删除），`schedule_events.json` 不再重复写入。
- 角色、突袭、竞技场与 UI：练度批量详情只读探针（未实测前保持逐角色）、魔方/珍藏缺记录 fail-closed、白银积分券更名；竞技场均衡搜索与私聊珍藏来源区分；Spine worker 环境白名单与进程组回收；T2I 对比度、字号下限与角色卡负载瘦身。
- 资产与运维：56 个重复图标去重；删除未用 NotoSansHans OTF 并补许可说明；塔罗牌面高保真 JPEG（逐张 PSNR ≥ 40.2 dB）；语音缺 ffmpeg/ffprobe 时告警提示；缓存清理加固并新增 `scripts/operations/prune_action_runs.py`。
- 结构：架构门禁跨层边 allowlist 清零；`main.py` 删除 36 个生产不可达的未注册遗留方法（252 行，门槛 700 → 300，新增公开成员白名单门禁）；删除 79 个非运维 `scripts/` 根兼容壳，根目录只保留 `backup_nikke_data`、`upgrade_preflight`、`cleanup_cache`、`diagnose_readonly` 与 `update_nikke_db.sh`，其余请改用 `scripts/<分类>/<工具>`（映射见 `docs/architecture/repository_organization_moves.json`）。
- 真实 QQ/NapCat 验收、远端 CI 与部署仍未执行。

## 2026-09-08 路线图收口补充

- PR #52/#53：正式 Spine 编排、官方 Spine 4.1 headless worker Docker 构建、受限 RGBA adapter、严格版本匹配和静态 FB/占位回退进入 main；服务器实构建、合法 bundle、生产许可和 benchmark 仍待现场证据。
- PR #54：Equipment/Cube/Favorite Item/Costume registry 统一来源、核验日期、SHA-256 和许可边界；`assets/costumes.json` 保持空表，不猜测服装映射。
- PR #55：Poke Voice 正式接入本地音频 → 精确证据映射的官方动态资源 → 文本回退；single-flight、4/5 秒预算、24 小时源缓存、ffprobe/ffmpeg 24kHz mono WAV 和生命周期回收已覆盖离线合同。
- 以上代码主题均已合并且当前无开放 PR；真实账号读取/写入、QQ Record 送达、生产部署、资源授权和服务器现场 runtime 仍未被离线证据替代。
