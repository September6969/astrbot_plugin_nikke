# Issue #82 重新对齐与基线审计报告 (2026-09)

> **基线说明**
> - **当前实际合并基线 (HEAD)**：17e56c2ddf61bc3283c632595e1f489df6c1bcb9 (PR #84: eat: integrate recent NIKKE plugin work)
> - **状态声明**：issue #82 original baseline is stale（原 Issue #82 记录的 610 tests、1800×1000 横版卡面及早期分支假设均已失效）。

---

## 一、当前真实基线构成

PR #84 整合了近期全部正式主线演进：
1. **Replica 单角色练度卡 (1600×2400)**：经过像素级校准（Typography 统一、OL 阶数徽章、装备角标及透明安全框裁切归一化）。
2. **Spine Face Anchor 离线元数据**：建立面部语义定位，运行时纯本地只读计算，8/8 典型身材与皮肤无溢出、无截断。
3. **Calendar v0.5 & GameKee 抓取**：结构化活动日程、原子化持久化缓存、宣传图 KV 缓存。
4. **NIKKE Tarot 完整后端**：78 张完整标准牌义、大阿尔卡那 22 张 + 小阿尔卡那 56 张高清卡面资产、原子牌池激活与物理 180° 逆位旋转。
5. **Phase 1-3 视觉资源层**：统一视觉资产多级 Resolver，骨骼与 Alpha Bounds 辅助定位。
6. **联盟突袭 (Union Raid)**：休赛期与结算期历史赛季数据回显与命令精简。
7. **Profile 个人信息卡**：TODAY 企业塔名称规范化解析、货币紧凑格式化 (K/M/B)。

---

## 二、Phase 0 仓库基准审计指标

| 审计指标 | 统计值 | 详细说明 |
| :--- | :--- | :--- |
| **Commit Baseline** | 17e56c2 | main 分支最新提交 |
| **根目录 Python 文件数** | **92** | 包含服务、模型、构建器、各类解析器及兼容模块 |
| **main.py 源码行数** | **2,291** | 包含生命周期、配置、调度器、各项命令注册与响应 |
| **docs 文件数** | **139** | 包含架构设计、验收报告、证据文件等 |
| **tests 文件数** | **543** | 包含单元测试、契约测试、前后端集成测试及快照等 |
| **assets 文件数** | **438** | 涵盖各类游戏静态资源与映射配置 |
| **Pytest 测试结果** | **915 passed, 2 skipped, 505 subtests passed** | 0 failed, 1 warning (Python 3.14 deprecation warning) |

### Assets 分类统计清单 (438 文件)
- ssets/skills: 238 files (技能图标 WebP / PNG)
- ssets/tarot: 79 files (大阿尔卡那 22 张 + 小阿尔卡那 56 张 + tarot_cards.json)
- ssets/favorite: 33 files (珍藏品与收藏品图标)
- ssets/guides: 18 files (攻略长图与登记清单)
- ssets/cube: 14 files (魔方图标)
- ssets/mappings: 11 files (L2D 清单、技能映射、骨骼语义与 Spine 元数据)
- ssets/currency: 9 files (货币与资源图标)
- ssets/spine-rendered: 8 files (验证预览资产)
- ssets/fallback: 6 files (通用缺省图)
- 根目录数据表: 14 json/schema/markdown 文件 (如 character_master.json, costumes.json, campaign_stages.json 等)

---

## 三、Issue #82 七阶段演进计划 (No Big-Bang)

为保证业务与契约 100% 稳定，严格遵守原子化、渐进式迁移原则，按 7 个独立 PR 实施：

`
main (17e56c2)
 ├── PR 1: refactor/issue-82-docs (Docs 结构化)
 ├── PR 2: refactor/issue-82-ui (UI 层收敛)
 ├── PR 3: refactor/issue-82-features (Features 领域化)
 ├── PR 4: refactor/issue-82-core-integrations (Core / Integrations 分离)
 ├── PR 5: refactor/issue-82-assets (Assets 规范化与多级 Fallback)
 ├── PR 6: refactor/issue-82-main (main.py 瘦身与依赖解耦)
 └── PR 7: refactor/issue-82-tests (Tests 结构化、CI 增强与历史分支清理)
`

每个 PR 均遵循：
- 基于最新 main 创建
- 保持向后兼容（根目录保留 shim）
- 业务行为、命令契约与 UI 视觉 100% 不变
- 独立 CI 全绿并合并
- 在 Issue #82 发表阶段进度追踪评论
