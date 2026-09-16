# NIKKE 插件文档索引 (Documentation Index)

本目录收录 NIKKE AstrBot 插件的完整技术设计、契约定义、验收报告、视觉规范与审计证据。

---

## 目录组织结构 (Documentation Structure)

`
docs/
├── README.md              # 文档总目录与导航（当前文件）
├── architecture/          # 系统架构设计、演进规划与工作基线记录
├── contracts/             # 各子系统数据契约与接口规格定义
├── acceptance/            # 历史与现行功能验收标准、测试报告与发布签署
├── ui/                    # T2I 渲染链路、视觉卡面规范、Handoff 与验收切片
├── operations/            # 运维清单、发布审计、多平台运行状态与路线台账
├── research/              # 前期逆向分析、资产探查与探索性研究成果
├── archive/               # 归档的历史临时文档与老旧变更记录
└── evidence/              # 线上真实环境抓包证据、面板对照与快照数据
`

---

## 分类说明与核心文档导引

### 1. 架构与规划 [rchitecture/](architecture/)
- [ISSUE_82_REBASE_2026_09.md](architecture\ISSUE_82_REBASE_2026_09.md): Issue #82 重新对齐与真实基线审计 (2026-09)
- [CALENDAR_V04_ARCHITECTURE.md](architecture\CALENDAR_V04_ARCHITECTURE.md): 结构化日历活动系统架构设计
- [DEVELOPMENT_PLAN.md](architecture\DEVELOPMENT_PLAN.md): 插件核心演进计划
- [ROADMAP_LEDGER.md](architecture\ROADMAP_LEDGER.md): 功能路线演进台账
- [WORKTREE_INDEX.md](architecture\WORKTREE_INDEX.md): 工作区索引与基线映射

### 2. 数据与接口契约 [contracts/](contracts/)
- [ANNOUNCEMENT_V2_CONTRACT.md](contracts\ANNOUNCEMENT_V2_CONTRACT.md): 官方公告 V2 接口与模型契约
- [CHARACTER_DATA_V2_CONTRACT.md](contracts\CHARACTER_DATA_V2_CONTRACT.md): 角色数据契约 V2
- [DYNAMIC_VOICE_V2_CONTRACT.md](contracts\DYNAMIC_VOICE_V2_CONTRACT.md): 动态语音管线契约
- [SPINE_SPIKE_CONTRACT.md](contracts\SPINE_SPIKE_CONTRACT.md): Spine 渲染探测接口契约
- [TOWER_SNAPSHOT_CONTRACT.md](contracts\TOWER_SNAPSHOT_CONTRACT.md): 企业塔快照契约

### 3. 功能验收报告 [cceptance/](acceptance/)
- 收录各特性阶段验收报告（包含 CI 测试覆盖率、边界验证与回归结果），如：
  - [CHARACTER_CARD_FINAL_ACCEPTANCE.md](acceptance\CHARACTER_CARD_FINAL_ACCEPTANCE.md)
  - [REPLICA_CALENDAR_V05_REPORT.md](ui\REPLICA_CALENDAR_V05_REPORT.md)
  - [STATE_EFFECT_REGISTRY_ACCEPTANCE.md](acceptance\STATE_EFFECT_REGISTRY_ACCEPTANCE.md)
  - [UNION_RAID_INCREMENT_A_ACCEPTANCE.md](acceptance\UNION_RAID_INCREMENT_A_ACCEPTANCE.md)

### 4. UI 与 T2I 表现层 [ui/](ui/)
- [REPLICA_CALENDAR_V05_REPORT.md](ui\REPLICA_CALENDAR_V05_REPORT.md): Replica 单角色练度卡与 Calendar v0.5 落地报告
- [UI_AUDIT_V03.md](ui\UI_AUDIT_V03.md): UI v0.3 全量视觉审计
- [T2I_FRONTEND_HANDOFF.md](ui\T2I_FRONTEND_HANDOFF.md): T2I 渲染前端交接文档
- [T2I_CAMPAIGN_PHASE1.md](ui\T2I_CAMPAIGN_PHASE1.md): 战役推图阵容可视化

### 5. 运维与运行保障 [operations/](operations/)
- [RELEASE_CHECKLIST.md](operations\RELEASE_CHECKLIST.md): 正式发布上线检查清单
- [LIVE_EVIDENCE_REGISTER.md](operations\LIVE_EVIDENCE_REGISTER.md): 现场证据登记簿
- [REQUIREMENT_EVIDENCE_MATRIX.md](operations\REQUIREMENT_EVIDENCE_MATRIX.md): 需求与证据矩阵

### 6. 技术预研与调研 [
esearch/](research/)
- [BLA_STATIC_ASSET_EXISTING_AUDIT.md](research\BLA_STATIC_ASSET_EXISTING_AUDIT.md): 静态资源全量审计
- [SPINE_RENDERED_ASSET_AUDIT.md](research\SPINE_RENDERED_ASSET_AUDIT.md): Spine 渲染资产审计报告
- [VOICE_MAPPING_RESEARCH.md](research\VOICE_MAPPING_RESEARCH.md): 角色语音映射分析

### 7. 现场证据资产 [evidence/](evidence/)
- 保存 55 项正式受控的真实抓包数据、面板对照与现场验证 JSON 快照（保留原始路径）。
