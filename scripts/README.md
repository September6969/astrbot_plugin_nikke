# 开发工具

实现按用途分类；根 `scripts/<文件名>` 保留薄兼容入口。仓库内调用和当前文档采用分类后的路径。Python 入口在同一进程转发，Shell 使用 `exec`，不复制实现。直接从其他工作目录执行时仍由脚本自身位置定位插件资源，显式参数路径保持原有含义。

| 分类 | 用途 | 输入 | 默认输出 |
| --- | --- | --- | --- |
| `assets/` | 素材、清单同步与字体工具 | 公开源、规范清单、本地原始资源 | `assets/` 内置素材或显式路径 |
| `spine/` | Spine 解析、渲染、锚点、候选审查 | bundle、清单、固定快照 | `output/`、显式外部目录；同步素材按参数写入 |
| `preview/` | 页面预览与离线回放 | 合成 DTO、脱敏夹具、指定资源 | 显式输出目录，或 `output/` |
| `audit/` | 架构、资源、性能与只读检查 | 源码、内置资源、固定快照 | 标准输出、`output/` 或显式路径 |
| `operations/` | 备份、升级、维护、只读采样 | 显式宿主数据或账号配置 | 显式路径或工具帮助所列宿主路径 |
| `shared/` | 多工具复用的样本和辅助模块 | 调用者传入 | 返回值或调用者指定路径 |

## 主要入口

```text
python scripts/audit/architecture_metrics.py --check --output <仓库外文件>
python scripts/assets/mirror_blablalink_assets.py --audit-only
python scripts/preview/preview_calendar_experience.py --output <输出目录>
python scripts/preview/preview_roster.py --output-dir <输出目录>
python scripts/spine/audit_spine_resource_coverage.py --output <仓库外文件>
python scripts/operations/backup_nikke_data.py --help
```

`--output`、`--output-dir`、`--out-dir`、`--target-dir` 等显式参数保持有效，具体以工具帮助为准。素材生产工具允许更新受控内置资源；报告、接触表、预览等临时文件使用 `output/`。候选批次工具要求全新的仓库外输出目录，继续防止覆盖旧审查材料。

`capture_*` 和诊断工具可能读取账号凭据并向上游发起只读请求；备份、恢复、清理、升级工具会修改本地文件，不能通过实际执行来探测用法。本次整理只验证帮助、导入、合成和模拟路径，不执行真实账号签到、领奖、绑定、兑换或消息发送。公开资源同步虽不涉及账号，仍可能联网并写入文件。

## 完整工具索引

“可能联网”包含公开资源下载、账号只读请求、外部渲染服务或生成 HTML 加载外部资源；离线模式是否生效以参数及实现为准。

| 实现入口 | 用途 | 网络或账号 |
| --- | --- | --- |
| [assets/build_character_visual_catalog.py](assets/build_character_visual_catalog.py) | 自动构建角色与皮肤全量视觉资源 Catalog (costume_visual_assets.json)。 | 本地处理，无账号操作 |
| [assets/build_costume_catalog.py](assets/build_costume_catalog.py) | 自动构建角色服装映射 assets/mappings/costume_assets.json。 | 本地处理，无账号操作 |
| [assets/build_item_catalogs.py](assets/build_item_catalogs.py) | 自动构建魔方与珍藏品/收藏品映射 assets/mappings/cube_icons.json 和 favorite_item_icons.json。 | 本地处理，无账号操作 |
| [assets/build_replica_font_subset.py](assets/build_replica_font_subset.py) | 为 NIKKE Character Card 构建专用 Noto Sans SC WOFF2 子集字体。 | 可能联网，无账号操作 |
| [assets/build_skill_icon_catalog.py](assets/build_skill_icon_catalog.py) | 自动构建角色技能图标静态映射 assets/mappings/skill_icons.json。 | 本地处理，无账号操作 |
| [assets/fetch_costume_identity_snapshot.py](assets/fetch_costume_identity_snapshot.py) | 维护期抓取 Canned Jar 明示的 Costume 名称与站立资产绑定。 | 可能联网，无账号操作 |
| [assets/fetch_manifest_snapshots.py](assets/fetch_manifest_snapshots.py) | 抓取并固化 BlaBlaLink 权威 Manifest 快照。 | 可能联网，无账号操作 |
| [assets/fetch_open_fonts.ps1](assets/fetch_open_fonts.ps1) | 字体下载 | 可能联网，无账号操作 |
| [assets/fetch_open_fonts.py](assets/fetch_open_fonts.py) | 从官方源拉取开源字体（Noto Sans SC, Barlow Condensed, Rajdhani）。 | 可能联网，无账号操作 |
| [assets/fetch_open_fonts.sh](assets/fetch_open_fonts.sh) | 字体下载 | 可能联网，无账号操作 |
| [assets/generate_fallback_assets.py](assets/generate_fallback_assets.py) | 生成 assets/fallback/ 下的语义兜底 PNG 素材。 | 本地处理，无账号操作 |
| [assets/import_campaign_stages.py](assets/import_campaign_stages.py) | 从已下载的官网静态表提取关卡映射；不推导 ID，不访问账号。 | 本地处理，无账号操作 |
| [assets/import_walkthrough_assets.py](assets/import_walkthrough_assets.py) | 将用户授权的攻略原件复制/分段到仓库，并生成可审计 manifest。 | 本地处理，无账号操作 |
| [assets/mirror_blablalink_assets.py](assets/mirror_blablalink_assets.py) | BlaBlaLink 静态资源本地镜像工具。 | 可能联网，无账号操作 |
| [assets/prepare_replica_resources.py](assets/prepare_replica_resources.py) | 从官网公开资源生成带来源哈希的武器基础值和技能图标；不读取账号。 | 可能联网，无账号操作 |
| [audit/architecture_metrics.py](audit/architecture_metrics.py) | 采集整仓重构的静态结构指标，并提供可重复的架构门禁输入。 | 本地处理，无账号操作 |
| [audit/audit_all_official_costumes.py](audit/audit_all_official_costumes.py) | 以固定 178 official inventory 生成最终 Costume 支持状态机。 | 本地处理，无账号操作 |
| [audit/audit_assets.py](audit/audit_assets.py) | 全量资源层审计与缺失检测工具，生成 reports/asset_audit.json。 | 本地处理，无账号操作 |
| [audit/audit_fonts.py](audit/audit_fonts.py) | 针对当前生产模板与真实 Golden Sample（拉毗：小红帽）进行运行态字体审计。 | 本地处理，无账号操作 |
| [audit/benchmark_measurements.py](audit/benchmark_measurements.py) | 独立基准测试脚本：统计真实微基准指标（中位数、P95、样本数）。 | 本地处理，无账号操作 |
| [audit/build_asset_contact_sheet.py](audit/build_asset_contact_sheet.py) | 独立调试工具：拼装技能、魔方与珍藏品图标 Contact Sheet，严禁借此修改练度卡卡面。 | 本地处理，无账号操作 |
| [audit/build_character_asset_contact_sheet.py](audit/build_character_asset_contact_sheet.py) | 生成角色视觉资源接触图 (Contact Sheet)，用于人工视觉比对与审计。 | 本地处理，无账号操作 |
| [audit/build_costume_identity_contact_sheets.py](audit/build_costume_identity_contact_sheets.py) | 按 owner 对齐实名 Costume poster 与真实 Spine 渲染，供人工身份核验。 | 本地处理，无账号操作 |
| [audit/build_inventory_and_size_report.py](audit/build_inventory_and_size_report.py) | 解析权威 Manifest 并生成完整静态资产清单与体积预估报告。 | 本地处理，无账号操作 |
| [audit/generate_asset_contact_sheets.py](audit/generate_asset_contact_sheets.py) | 生成阵容小头像与 Boss 静态资产联系表 (Contact Sheet) 及覆盖率报告。 | 可能联网，无账号操作 |
| [operations/backup_nikke_data.py](operations/backup_nikke_data.py) | 创建可离线恢复的 NIKKE 数据目录备份。 | 本地处理，无账号操作；涉及本地运维 |
| [operations/capture_campaign_history.py](operations/capture_campaign_history.py) | 只读抓取 NORMAL/HARD 战役历史阵容，并生成脱敏静态快照。 | 账号只读，可能联网 |
| [operations/capture_profile_fixtures.py](operations/capture_profile_fixtures.py) | 用已授权账号抓取并完全脱敏 Profile/Outpost 响应结构。 | 账号只读，可能联网 |
| [operations/capture_union_raid_fixtures.py](operations/capture_union_raid_fixtures.py) | 从官网已确认 endpoint 抓取并完全脱敏联盟突袭响应结构。 | 账号只读，可能联网 |
| [operations/cleanup_cache.py](operations/cleanup_cache.py) | 安全清理 NIKKE 本地缓存；默认只生成清理计划，不删除文件。 | 本地处理，无账号操作；涉及本地运维 |
| [operations/diagnose_character_details.py](operations/diagnose_character_details.py) | 从脱敏 CharacterDetails JSON 输出字段结构诊断，不输出原始账号值。 | 账号只读，可能联网 |
| [operations/diagnose_readonly.py](operations/diagnose_readonly.py) | 一次性只读诊断：默认离线，显式 --live-readonly 才读取本机绑定账号。 | 账号只读，可能联网 |
| [operations/update_nikke_db.sh](operations/update_nikke_db.sh) | 维护工具 | 可能联网，无账号操作；涉及本地运维 |
| [operations/upgrade_preflight.py](operations/upgrade_preflight.py) | 执行 NIKKE 数据升级/回滚前的只读前置检查。 | 本地处理，无账号操作；涉及本地运维 |
| [preview/generate_live_regression_calendar_evidence.py](preview/generate_live_regression_calendar_evidence.py) | 用当前公开源和已观察生产记录生成 Calendar 去重证据。 | 本地处理，无账号操作 |
| [preview/generate_live_regression_character_evidence.py](preview/generate_live_regression_character_evidence.py) | 生成 c401/c581 生产锚点修复前后完整角色卡证据。 | 本地处理，无账号操作 |
| [preview/preview_calendar_candidates.py](preview/preview_calendar_candidates.py) | 按固定时间和本地素材生成日程 UI 回归样例与截图。 | 本地处理，无账号操作 |
| [preview/preview_calendar_experience.py](preview/preview_calendar_experience.py) | 通过生产模板生成固定日程样本的整图和手机预览。 | 本地处理，无账号操作 |
| [preview/preview_campaign_ui.py](preview/preview_campaign_ui.py) | 通过正式战役 T2I payload 对比五槽卡和五行版。 | 本地处理，无账号操作 |
| [preview/preview_character_design_audit.py](preview/preview_character_design_audit.py) | 通过正式角色 DTO、payload 和模板生成本地构图审查图。 | 本地处理，无账号操作 |
| [preview/preview_profile_experience.py](preview/preview_profile_experience.py) | 用人工固定样本回放个人资料模板，输出整图、手机缩图与布局检查。 | 本地处理，无账号操作 |
| [preview/preview_profile_renderers.py](preview/preview_profile_renderers.py) | 用正式 DTO 与两条图片路径生成个人资料审查样例。 | 本地处理，无账号操作 |
| [preview/preview_raid_experience.py](preview/preview_raid_experience.py) | 用人工固定样本回放正式突袭模板，输出整图、手机缩图与布局检查。 | 本地处理，无账号操作 |
| [preview/preview_replica.py](preview/preview_replica.py) | 使用实际生产模板和本地浏览器生成案例对照；不访问真实账号。 | 本地处理，无账号操作 |
| [preview/preview_roster.py](preview/preview_roster.py) | 用正式总表 DTO、T2I loader 与原 Pillow renderer 生成审查预览。 | 本地处理，无账号操作 |
| [preview/preview_t2i_frontend.py](preview/preview_t2i_frontend.py) | 通过生产 renderer 与 AstrBot 原生接口输出各页合成预览。 | 可能联网，无账号操作 |
| [preview/preview_t2i_ui.py](preview/preview_t2i_ui.py) | 用生产适配器和 AstrBot 原生接口生成合成数据预览，不启动插件服务。 | 可能联网，无账号操作 |
| [shared/phase3_output_guard.py](shared/phase3_output_guard.py) | 为 Phase 3 维护工具约束外部输出路径，避免写入仓库或覆盖已有 evidence。 | 本地处理，无账号操作 |
| [shared/raid_evidence.py](shared/raid_evidence.py) | 仅保留已知结构的突袭证据转换，不读取账号、不发起网络请求。 | 本地处理，无账号操作 |
| [shared/t2i_preview_fixtures.py](shared/t2i_preview_fixtures.py) | 供预览和离线测试共用的合成 DTO；不包含真实账号资料。 | 本地处理，无账号操作 |
| [spine/analyze_spine_visuals.py](spine/analyze_spine_visuals.py) | 审计已渲染 Spine PNG 的可见结构并生成全量 contact sheet。 | 本地处理，无账号操作 |
| [spine/audit_all_spine_runtime_resolution.py](spine/audit_all_spine_runtime_resolution.py) | 全量 Spine 运行时解析与生产资产审计脚本。 | 本地处理，无账号操作 |
| [spine/audit_costume_spine_coverage.py](spine/audit_costume_spine_coverage.py) | 审计官方 Costume 清单与本地已验证 Spine 预渲染覆盖。 | 本地处理，无账号操作 |
| [spine/audit_spine_resource_coverage.py](spine/audit_spine_resource_coverage.py) | 离线审计 canonical Character、Nikke-db Spine、manifest、PNG 与 framing 元数据。 | 可能联网，无账号操作 |
| [spine/audit_spine_runtime.py](spine/audit_spine_runtime.py) | 重新全量审计默认角色 (200) 与 Costume (178) 的 Spine 实际覆盖率与运行时状态。 | 本地处理，无账号操作 |
| [spine/batch_prepare_samples.py](spine/batch_prepare_samples.py) | Batch pipeline to extract authentic Spine face anchors and render high-res idle portraits. | 可能联网，无账号操作 |
| [spine/benchmark_spine_placement.py](spine/benchmark_spine_placement.py) | Spine 实时加载、渲染与定位元数据读取性能基准测试。 | 本地处理，无账号操作 |
| [spine/build_character_placement_meta.py](spine/build_character_placement_meta.py) | 构建角色定位元数据 (character_placement_meta.json) 与定位审计报告 (placement_audit.json)。 | 本地处理，无账号操作 |
| [spine/build_costume_spine_candidate_matrix.py](spine/build_costume_spine_candidate_matrix.py) | 把官方 178 Costume 与明示名称资产、Nikke-db index、verified registry 交叉。 | 本地处理，无账号操作 |
| [spine/build_spine_candidate_batch.py](spine/build_spine_candidate_batch.py) | 从离线 coverage audit 中稳定选择默认角色 Spine 候选批次。 | 本地处理，无账号操作 |
| [spine/build_spine_metadata.py](spine/build_spine_metadata.py) | 自动构建角色与皮肤 Spine 元数据 (spine_metadata.json)。 | 本地处理，无账号操作 |
| [spine/build_spine_semantics.py](spine/build_spine_semantics.py) | 自动构建全量骨骼语义映射表 (spine_bone_semantics.json)。 | 本地处理，无账号操作 |
| [spine/check_spine_candidate_promotion.py](spine/check_spine_candidate_promotion.py) | 只读检查候选资源是否具备人工审批后的 manifest 晋升前置条件。 | 本地处理，无账号操作 |
| [spine/debug_spine_placement.py](spine/debug_spine_placement.py) | 生成角色骨骼与锚点调试标注图，用于人工质检与验证。 | 本地处理，无账号操作 |
| [spine/evaluate_centering_policies.py](spine/evaluate_centering_policies.py) | Evaluate Card-space Correction Policies offline across 36 authentic samples. | 本地处理，无账号操作 |
| [spine/extract_spine_face_anchor.mjs](spine/extract_spine_face_anchor.mjs) | ES 模块辅助 | 本地处理，无账号操作 |
| [spine/fetch_spine_candidate_bundles.py](spine/fetch_spine_candidate_bundles.py) | 按固定 Nikke-db commit 只取指定默认角色的 Spine bundle 与 atlas 纹理页。 | 本地处理，无账号操作 |
| [spine/finalize_costume_identity_validation.py](spine/finalize_costume_identity_validation.py) | 把已实际查看的 owner contact sheets 固化为逐 Costume 身份证据。 | 本地处理，无账号操作 |
| [spine/generate_centering_evidence.py](spine/generate_centering_evidence.py) | Generate face-guided body centering A/B comparisons and metrics for real NIKKE art. | 本地处理，无账号操作 |
| [spine/generate_pair_blind_package.py](spine/generate_pair_blind_package.py) | Generate Pair-based Blind Review Package for face-guided body centering. | 本地处理，无账号操作 |
| [spine/generate_y_offset_comparison.py](spine/generate_y_offset_comparison.py) | Generate Before/After (+16px Y) comparison cards for c016 and c191. | 本地处理，无账号操作 |
| [spine/inspect_spine_bundle.py](spine/inspect_spine_bundle.py) | 无运行时的 Spine 本地预检查；不加载动画、不下载或执行外部代码。 | 本地处理，无账号操作 |
| [spine/prepare_face_anchors.py](spine/prepare_face_anchors.py) | 离线构建角色／皮肤锚点，绑定原始 PNG、骨架、atlas 及 idle 帧。 | 可能联网，无账号操作 |
| [spine/rebuild_spine_render_manifest.py](spine/rebuild_spine_render_manifest.py) | Spine 预渲染静态资产 Manifest 维护与重构脚本。 | 本地处理，无账号操作 |
| [spine/render_spine_candidate_batch.sh](spine/render_spine_candidate_batch.sh) | 维护工具 | 可能联网，无账号操作 |
| [spine/render_spine_candidate_cards.py](spine/render_spine_candidate_cards.py) | 使用当前 CharacterT2IPayloadBuilder 与 character.html 生成 dry-run 白卡。 | 本地处理，无账号操作 |
| [spine/render_spine_preview.py](spine/render_spine_preview.py) | 离线用匹配版本的官方 WebGL runtime 输出高分辨率 idle PNG。 | 可能联网，无账号操作 |
| [spine/reorder_csv.py](spine/reorder_csv.py) | 辅助工具 | 本地处理，无账号操作 |
| [spine/resolve_all_official_costumes.py](spine/resolve_all_official_costumes.py) | 原子化提升 178 条已交叉验证 Costume 映射到 schema v3 registry。 | 本地处理，无账号操作 |
| [spine/spine_attachment_candidates.mjs](spine/spine_attachment_candidates.mjs) | ES 模块辅助 | 本地处理，无账号操作 |
| [spine/spine_batch_review.py](spine/spine_batch_review.py) | 校验 Spine 候选批次、生成待人工复核清单与新版白卡 contact sheet。 | 本地处理，无账号操作 |
| [spine/spine_batch_validation.py](spine/spine_batch_validation.py) | Spine 候选批次的本地完整性检查与可解释视觉指标。 | 本地处理，无账号操作 |
| [spine/spine_surface_semantics.mjs](spine/spine_surface_semantics.mjs) | ES 模块辅助 | 本地处理，无账号操作 |
| [spine/spine_worker_docker_bridge.py](spine/spine_worker_docker_bridge.py) | 将现有维护 renderer 的 worker 参数安全转接给已构建的官方 Docker worker。 | 本地处理，无账号操作 |
| [spine/sync_spine_assets.py](spine/sync_spine_assets.py) | 从本地 Nikke-db checkout 维护 Spine idle@t=0 PNG 与 manifest v2。 | 本地处理，无账号操作 |
