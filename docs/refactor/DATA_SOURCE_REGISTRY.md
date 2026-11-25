# DATA_SOURCE_REGISTRY.md — 数据源、许可审查与外部接口登记表

> **合规基线（2026-11-25，PR #150 @ `integration/phase2-candidate`）**  
> 本仓对“游戏事实元数据 / 第三方整理内容 / 第三方计算代码”实施分层许可审查：未经明确再分发许可的第三方整理数据集不进公开仓，已接入的可选外部导入格式全部提供统一校验 CLI（[validate_external_data.py](../../scripts/operations/validate_external_data.py)）与使用文档（[EXTERNAL_DATA_IMPORT.md](../acceptance/EXTERNAL_DATA_IMPORT.md)）。

---

## 一、许可分层审查与仓库内置数据文件（`assets/data/`）

| 审查类别 | 文件名 | 用途 | 许可 / 来源边界 | 可用等级 |
|---|---|---|---|---|
| **仓库维护游戏事实/标识元数据** | `character_master.json`, `character_aliases.json`, `character_catalog.json`, `character_weapon_bases.json`, `costumes.json`, `equipment.json`, `cubes.json`, `favorite_items.json`, `overload_tiers.json`, `campaign_stages.json`, `tower_floors.json`, `face_anchors.json`, `spine_manifest.json`, `state_effects.json`, `raid_raid_list.json`, `voice_poke_map.json`, `remote_sources.json`, `registry_manifest.json` | 基础属性、别名、装扮/装备/魔方标识映射、官方便携超限档位（1–15 档）、主线/爬塔静态表、语音与视觉索引 | 仅包含标识符与静态游戏数值索引（见 `registry_manifest.json` 校验哈希），不再分发受版权保护的非授权二进制包 | **READY** |
| **规则核验元数据（新增）** | [wishlist_pool_eligibility.json](../../assets/data/wishlist_pool_eligibility.json) | 全部 171 名 `character_master.json` SSR 的普通招募愿望单准入表（`ordinary_recruit` / `pilgrim_overspec` / `limited` / `collab` / `free_welfare` / `unknown`） | 仓库基于官方愿望单机制整理并采取保守 **fail-closed** 默认拒绝未知角色策略；支持运营者在 `data/nikke/wishlist-pool-eligibility.json` 覆盖更新 | **READY** |
| **第三方计算代码衍生映射** | `solo_raid_engine_names.json` + `LICENSE-nikke-calc.txt` | 912 项角色与 MIT 引擎官方名映射（绑定校验 `engine_commit`） | **MIT** 开源衍生产物（源自 `Jgaram/nikke-calc@67835ca`） | **READY** |

---

## 二、未入公开仓的无许可数据集（`9968a50` 剔除项）与导入校验

以下源自 NikkeHub 的 4 份整理数据集未发现明确开源再分发授权，**永不恢复入仓，也不以伪造/模拟数据替代**：

| 缺失外部数据 | 消费模块 | 校验命令（`validate_external_data.py`） | 运行期状态与合法降级说明 |
|---|---|---|---|
| **同步器等级成本表**（原 `sync-level-costs.json`） | `features/sync/cost_table.py`, `calculator.py` | `validate_external_data.py sync_costs <path>` | **DEGRADED**：不推测未导入等级成本，提供「手工输入三项累计成本」模式（已在 `serv` 实测通过） |
| **单人突袭赛季 Boss 资料**（原 `solo_raid_seasons.json`） | `features/solo_raid/seasons.py`, `builder.py` | `validate_external_data.py solo_raid_seasons <path>` | **DEGRADED**：未导入赛季表时显式提示缺口，五队编组与爆裂检验功能仍正常可用（已在 `serv` 实号 186 人完成验证） |
| **超限词条推荐预设表**（原 `overload_recommendations.json`） | `features/overload_advice/advisor.py` | `validate_external_data.py overload_recommendations <path>` | **DEGRADED**：未导入预设时直接以用户输入目标词条 + 官方 `overload_tiers.json` 给出锁/洗建议与概率模拟（已在 `serv` 小红帽实装 OL 上验证） |
| **中文咨询答案题库**（原韩文 `counsel_bank.json`） | `features/counsel/bank.py` | `validate_external_data.py counsel_bank <path>` | **BLOCKED**：无合法中文授权题库前阻断查询并要求导入含 `license` + `source_url` + `checked_at` 的题库 |

---

## 三、外部网络服务、反代安全边界与第三方计算代码登记

| 接口 / 依赖 | 地址 / 上游仓库 | 使用模块 | 权限、日志保护与隔离边界 | 实测情况与当前状态 |
|---|---|---|---|---|
| **BlaBlaLink 业务接口** | `api.blablalink.com` / `www.blablalink.com` | `integrations/blablalink/client.py`, `session_renewal.py` | 仅完整绑定账号加密本人凭据；写操作（签到/日常/CDK/续期）均默认关闭并带独立授权 | `serv` `***9910` 全量只读接口、`CookieExpired` 识别与突发详情限流单次重试已实测通过；写操作保持默认关闭 |
| **BlaBlaLink & Nikke-DB CDN** | `sg-tools-cdn.blablalink.com`, `raw.githubusercontent.com/Nikke-db/...` | `core/asset_manager.py`, `integrations/nikke_db/provider.py` | 只读图片/Spine 下载 + 哈希/大小/类型校验与本地缓存 | Spine CI（Docker 4.0/4.1 Worker）与 `serv` 6s 硬预算冷拉降级兜底均已实测通过 |
| **ShiftyPad 公开档案接口** | `https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile` | `integrations/shiftypad/official.py`, `integrations/web/shiftypad_service.py`, [Caddyfile](../../deploy/Caddyfile) | **默认关闭**（`enable_shiftypad_readonly=false`）；一次性 token → HttpOnly Cookie + CSRF + Origin + `frame-ancestors 'none'` + `Referrer-Policy: no-referrer` + Caddy `log_skip /shiftypad/*` & `/api/shiftypad/*` + aiohttp `access_log=None` | Web 会话与零日志泄漏已自测通过；缺授权测试账号验证上游契约（**BLOCKED**）；上线开此功能前宿主机须同步 `Caddyfile` |
| **第三方公开分享资料 API** | `https://nikke-api.pages.dev/api/user/<blablaid>`（`github.com/leegunwoooo/nikke-api`） | `integrations/nikke_api/share_profile.py`, `application/commands/shiftypad.py` | **默认关闭**（`enable_public_share_api=false`）；外传 `blablaid` 前向用户明确披露并要求 `确认` | 离线门禁全过；默认关闭未实网开启 |
| **NIKKE 官方 YouTube Atom 源** | `https://www.youtube.com/feeds/videos.xml?channel_id=UCmmgZwsqQRD6PKeo87uq1bA` | `integrations/announcement/youtube_atom.py`, `features/announcement/feeds.py` | 无认证只读订阅；按类型状态机保护（`uninitialized` / `initialized` / `initialized_unavailable`），来源不可用恢复时不重推历史 | 离线/并发/跨渠道单测全过；`serv` 上 `ConnectError` 时实测安全建基线提示 |
| **外部 MIT 单人突袭估伤引擎** | `https://github.com/Jgaram/nikke-calc`（锁定 `67835ca3033a95482749ea2db35a8ee2a0856a92`，**MIT**） | [engine.py](../../integrations/nikke_calc/engine.py), [runtime.py](../../adapters/astrbot/runtime.py) | 独立 `asyncio.create_subprocess_exec` + `TaskGroup` + 信号量覆盖进程树强杀（Win32 Job Object / POSIX `killpg` + `/proc` 僵尸过滤）与短排空超时、最小 env 白名单、`stdout`/`stderr` 运行期字节上限、`git rev-parse HEAD`/clean 与 `mapping_commit` 4 态核验、`aclose()` 安全收尾 | `serv` 实号 5 队计算得 **`1,813,859,815`**（`Git 核验固定基线`），且 0.4s 超时故障注入零残留；需部署机自备干净克隆 |
