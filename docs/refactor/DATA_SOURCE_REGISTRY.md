# DATA_SOURCE_REGISTRY.md — 数据源、资产许可与外部接口登记表

> **合规基线（2026-11-24，PR #144–#148）**  
> 所有未取得明确再分发开源许可的第三方抓取数据集一律**不进入公开仓库**；涉及向第三方服务发送玩家标识的能力一律默认关闭（`false`），并在调用前向用户明确披露外传范围与取得 `确认`。

---

## 一、仓库内置静态数据文件（`assets/data/`）

| 文件名 | 大小（bytes） | 用途 | 许可 / 来源边界 | 维护与消费方 |
|---|---:|---|---|---|
| `character_master.json` | 95,071 | 角色全量基础属性、企业、爆裂、武器、分类标识 | 仓库维护元数据（无游戏资产再分发） | `features/character/*`, `features/wishlist/*`, `features/favorite_grid/*` |
| `character_aliases.json` | 24,268 | 角色中/英/常用外号别名表 | 仓库维护索引 | `features/character/identity.py` |
| `character_catalog.json` | 40,824 | 角色视觉资源目录索引 | 仓库维护索引 | `features/character/visual_resolver.py` |
| `character_weapon_bases.json` | 149,354 | 武器基础模型数据 | 仓库维护数值索引 | `features/character/stat_calculator.py` |
| `costumes.json` | 271,983 | 时装与 `CharacterCostumeTable` / Nikke-DB L2D 映射 | 仓库维护标识元数据（见 `registry_manifest.json`） | `features/character/*`, `core/asset_manager.py` |
| `equipment.json` / `cubes.json` / `favorite_items.json` | 5,991 / 369 / 1,303 | 装备、魔方、珍藏品资源 ID 映射 | 仓库维护标识元数据（`registry_manifest.json` 登记 sha256） | `core/asset_manager.py` |
| `overload_tiers.json` | 7,865 | 官方超限词条档位数值表（1–15 档） | 静态数值表 | `features/overload_advice/advisor.py`, `features/character/*` |
| `solo_raid_engine_names.json` | 31,130 | 角色名称与 `nikke-calc` 引擎英文标识映射（`schema_version: 1`） | **MIT** 衍生映射，源自 `Jgaram/nikke-calc@67835ca`（附 `LICENSE-nikke-calc.txt`） | `integrations/nikke_calc/engine.py` |
| `campaign_stages.json` / `.source.json` | 91,593 / 473 | 主线战役关卡静态索引与来源记录 | 仓库维护索引 | `features/campaign/*` |
| `tower_floors.json` | 472,311 | 无限之塔/企业塔静态楼层资料 | 仓库维护静态数据 | `features/tower/*` |
| `face_anchors.json` / `spine_manifest.json` / `spine_manifest.schema.json` | 78,998 / 26,430 / 3,348 | 立绘脸部锚点与 Spine 清单校验 Schema | 仓库维护校验配置 | `features/character/*`, `integrations/spine/*` |
| `state_effects.json` / `raid_raid_list.json` / `voice_poke_map.json` / `remote_sources.json` | 77,967 / 2,461 / 1,074,341 / 774 | 技能状态说明、突袭季号列表、语音触发映射、远端 CDN 模板 | 仓库维护索引 | 对应功能模块 & `core/asset_manager.py` |

> 注：本机 Windows worktree 采用 sparse-checkout，大型资源目录（`assets/blablalink`、`assets/fonts`、`assets/tarot`、`assets/icons`、`assets/mappings` 等）在完整检出与 GitHub Actions CI 中提供。

---

## 二、明确剔除（不随公开仓分发）的无许可数据

源自本地备份 `9968a50` 的下列 4 份 NikkeHub 抓取数据因缺乏公开再分发授权，**已严格禁止推入公开仓**，仅保留运行时的导入器、Schema 校验与缺失显式提示：

| 原文件路径 | 原规模 | 未入仓原因 | 替代运行机制 |
|---|---:|---|---|
| `assets/data/counsel_bank.json` | 24,611 行 | 来源 NikkeHub 无开源再分发许可，且原抓取 794 条均为韩文（中文=0） | 运行时缺省为空/未导入（`tool.counsel` 为 `BLOCKED`），支持通过合规 `schema_version=1` + `license` 标注的本地文件导入 |
| `assets/data/sync-level-costs.json` | 4,809 行 | 来源 NikkeHub 无再分发许可 | 运行时支持合规成本表导入，或使用 `/妮姬 同步器 计算 手工 ...` 直接输入三项累计成本；更新器校验往返 Schema |
| `assets/data/overload_recommendations.json` | 146 行 | 来源 NikkeHub 无再分发许可 | `features/overload_advice/advisor.py` 允许无外部推荐表时使用用户输入目标词条与官方 `overload_tiers.json` 运行 |
| `assets/data/solo_raid_seasons.json` | — | 来源 NikkeHub 无再分发许可 | `features/solo_raid/seasons.py` 运行时加载用户/管理员本地导入赛季表；未导入时提示先导入赛季 JSON |

---

## 三、外部网络接口与第三方依赖登记

| 接口 / 依赖 | 地址 / 仓库 | 使用模块 | 权限 / 门禁与外传数据范围 | 状态 |
|---|---|---|---|---|
| **BlaBlaLink 业务接口** | `api.blablalink.com` / `www.blablalink.com` | `integrations/blablalink/client.py`, `session_renewal.py` | 仅完整绑定账号通过加密存储的本人 Cookie/上下文访问；写操作（签到/日常/CDK/续期）受默认关闭开关与独立写授权保护 | 已运行核心功能（写操作待实号复验） |
| **BlaBlaLink 静态资源 CDN** | `https://sg-tools-cdn.blablalink.com/{path_hash}.{webp,png}` | `core/asset_manager.py` (`assets/data/remote_sources.json`) | 只读拉取并经格式/尺寸/体积校验后缓存本地 | 离线已验缓存与降级 |
| **Nikke-DB L2D 静态索引镜像** | `https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/images` | `assets/data/remote_sources.json` | 只读远端图床基址配置 | 索引引用 |
| **BlaBlaLink ShiftyPad 公开档案接口** | `https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetUserProfile` | `integrations/shiftypad/official.py` | **默认关闭**（`enable_shiftypad_readonly=false`）；声明 `CONTRACT = "official_public_profile_unverified_2026-11-23"`，只读尝试，无鉴权写入能力 | **BLOCKED（待实号只读实测）** |
| **第三方公开分享资料 API** | `https://nikke-api.pages.dev/api/user/<blablaid>`（来源 `github.com/leegunwoooo/nikke-api`） | `integrations/nikke_api/share_profile.py`, `application/commands/shiftypad.py` | **默认关闭**（`enable_public_share_api=false`）；仅发送用户主动提供的公开分享 ID（`blablaid`），首次查询提示外传目标域并要求命令携带 `确认` | 离线开关与披露门禁已验 |
| **NIKKE 官方 YouTube Atom 源** | `https://www.youtube.com/feeds/videos.xml?channel_id=UCmmgZwsqQRD6PKeo87uq1bA` | `integrations/announcement/youtube_atom.py` | 无认证只读订阅官方频道标题与链接；异常时保留既有状态不丢失基准 | 离线测试通过，线上实网待验 |
| **外部单人突袭估伤引擎** | `https://github.com/Jgaram/nikke-calc`（固定 `PINNED_COMMIT = 67835ca3033a95482749ea2db35a8ee2a0856a92`，**MIT**） | `integrations/nikke_calc/engine.py` | 本地独立子进程调用；禁止透传宿主机完整 `os.environ`；信号量限并发、进程组强杀、`MAX_OUTPUT_BYTES`、批次超时、强制校验 `git rev-parse HEAD` 与干净工作区（禁静默回填版本号） | 离线 Fake Runner 验证通过；真实仓库克隆待部署机实测 |
