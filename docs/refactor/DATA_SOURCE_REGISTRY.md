# DATA_SOURCE_REGISTRY.md — 数据源、许可审查与外部接口登记表

> **合规基线（2026-11-24，PR #150 @ `164d3b6`）**  
> 本仓对“游戏事实元数据 / 第三方整理内容 / 第三方计算代码”实施分层许可审查：未经明确再分发许可的第三方整理数据集不进公开仓，已接入的可选外部导入格式全部提供统一校验 CLI（[validate_external_data.py](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/scripts/operations/validate_external_data.py)）与使用文档（[EXTERNAL_DATA_IMPORT.md](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/docs/acceptance/EXTERNAL_DATA_IMPORT.md)）。

---

## 一、许可分层审查与仓库内置数据文件（`assets/data/`）

| 审查类别 | 文件名 | 用途 | 许可 / 来源边界 | 可用等级 |
|---|---|---|---|---|
| **仓库维护游戏事实/标识元数据** | `character_master.json`, `character_aliases.json`, `character_catalog.json`, `character_weapon_bases.json`, `costumes.json`, `equipment.json`, `cubes.json`, `favorite_items.json`, `overload_tiers.json`, `campaign_stages.json`, `tower_floors.json`, `face_anchors.json`, `spine_manifest.json`, `state_effects.json`, `raid_raid_list.json`, `voice_poke_map.json`, `remote_sources.json`, `registry_manifest.json` | 基础属性、别名、装扮/装备/魔方标识映射、官方便携超限档位（1–15 档）、主线/爬塔静态表、语音与视觉索引 | 仅包含标识符与静态游戏数值索引（见 `registry_manifest.json` 校验哈希），不再分发受版权保护的非授权二进制包 | **READY** |
| **规则核验元数据（新增）** | [wishlist_pool_eligibility.json](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/assets/data/wishlist_pool_eligibility.json) | 全部 171 名 `character_master.json` SSR 的普通招募愿望单准入表（`ordinary_recruit` / `pilgrim_overspec` / `limited` / `collab` / `free_welfare` / `unknown`） | 仓库基于官方愿望单机制整理并采取保守 **fail-closed** 默认拒绝未知角色策略；支持运营者在 `data/nikke/wishlist-pool-eligibility.json` 覆盖更新 | **READY** |
| **第三方计算代码衍生映射** | `solo_raid_engine_names.json` + `LICENSE-nikke-calc.txt` | 912 项角色与 MIT 引擎官方名映射 | **MIT** 开源衍生产物（源自 `Jgaram/nikke-calc@67835ca`） | **READY** |

---

## 二、未入公开仓的无许可数据集（`9968a50` 剔除项）与导入校验

以下源自 NikkeHub 的 4 份整理数据集未发现明确开源再分发授权，**永不恢复入仓，也不以伪造/模拟数据替代**：

| 缺失外部数据 | 消费模块 | 校验命令（`validate_external_data.py`） | 运行期状态与合法降级说明 |
|---|---|---|---|
| **同步器等级成本表**（原 `sync-level-costs.json`） | `features/sync/cost_table.py`, `calculator.py` | `validate_external_data.py sync_costs <path>` | **DEGRADED**：不推测未导入等级成本，提供「手工输入三项累计成本」模式 |
| **单人突袭赛季 Boss 资料**（原 `solo_raid_seasons.json`） | `features/solo_raid/seasons.py`, `builder.py` | `validate_external_data.py solo_raid_seasons <path>` | **DEGRADED**：未导入赛季表时显式提示缺口，五队编组与爆裂检验功能仍正常可用 |
| **超限词条推荐预设表**（原 `overload_recommendations.json`） | `features/overload_advice/advisor.py` | `validate_external_data.py overload_recommendations <path>` | **DEGRADED**：未导入预设时直接以用户输入目标词条 + 官方 `overload_tiers.json` 给出锁/洗建议与概率模拟 |
| **中文咨询答案题库**（原韩文 `counsel_bank.json`） | `features/counsel/bank.py` | `validate_external_data.py counsel_bank <path>` | **BLOCKED**：无合法中文授权题库前阻断查询并要求导入含 `license` + `source_url` + `checked_at` 的题库 |

---

## 三、外部网络服务、反代安全边界与第三方计算代码登记

| 接口 / 依赖 | 地址 / 上游仓库 | 使用模块 | 权限、日志保护与隔离边界 | 实测情况与当前状态 |
|---|---|---|---|---|
| **BlaBlaLink 业务接口** | `api.blablalink.com` / `www.blablalink.com` | `integrations/blablalink/client.py`, `session_renewal.py` | 仅完整绑定账号加密本人凭据；写操作（签到/日常/CDK/续期）均默认关闭并带独立授权 | 离线/CI 全过；真实写操作待授权账号复验（`DEGRADED`） |
| **BlaBlaLink & Nikke-DB CDN** | `sg-tools-cdn.blablalink.com`, `raw.githubusercontent.com/Nikke-db/...` | `core/asset_manager.py`, `integrations/nikke_db/provider.py` | 只读图片/Spine 下载 + 哈希/大小/类型校验与本地缓存 | Spine CI（Docker 4.0/4.1 Worker）实测通过（`READY`） |
| **ShiftyPad 公开档案接口** | `https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile` | `integrations/shiftypad/official.py`, `integrations/web/shiftypad_service.py`, [Caddyfile](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/deploy/Caddyfile) | **默认关闭**（`enable_shiftypad_readonly=false`）；一次性 token → HttpOnly Cookie + CSRF + Origin + `frame-ancestors 'none'` + `Referrer-Policy: no-referrer` + Caddy `log_skip /shiftypad/*` & `/api/shiftypad/*` + aiohttp `access_log=None` | Web 会话与零日志泄漏已实测；缺少授权测试账号验证上游契约（**BLOCKED**） |
| **第三方公开分享资料 API** | `https://nikke-api.pages.dev/api/user/<blablaid>`（`github.com/leegunwoooo/nikke-api`） | `integrations/nikke_api/share_profile.py`, `application/commands/shiftypad.py` | **默认关闭**（`enable_public_share_api=false`）；外传 `blablaid` 前向用户明确披露并要求 `确认` | 离线门禁全过；线上外网连通未测（`DEGRADED`） |
| **NIKKE 官方 YouTube Atom 源** | `https://www.youtube.com/feeds/videos.xml?channel_id=UCmmgZwsqQRD6PKeo87uq1bA` | `integrations/announcement/youtube_atom.py`, `features/announcement/feeds.py` | 无认证只读订阅；来源故障时保持既有 `baseline` 绝不被空结果覆写，移除无效 `reminder_hours` | 离线/并发/故障恢复测试全过（线上实网待测） |
| **外部 MIT 单人突袭估伤引擎** | `https://github.com/Jgaram/nikke-calc`（锁定 `67835ca3033a95482749ea2db35a8ee2a0856a92`，**MIT**） | [engine.py](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/integrations/nikke_calc/engine.py), [runtime.py](file:///C:/Users/September/.gemini/antigravity/worktrees/Nikke_Plugin/plugin_audit_refactor_plan/adapters/astrbot/runtime.py) | 独立 `asyncio.create_subprocess_exec` + `TaskGroup` + 信号量覆盖进程树强杀/回收、最小 env 白名单、`stdout`/`stderr` 运行期字节上限、`git rev-parse HEAD` /干净检查（`dirty` 或无核验拒标固定基线）、宿主机关闭自动 `aclose()` | 本机已克隆 `67835ca` 跑出真实数值 `2001618539`（`version_ok=True`），但部署机须自备干净克隆与映射（`DEGRADED`） |
