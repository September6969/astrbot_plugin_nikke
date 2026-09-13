# BlaBla 静态资源盘点与分级体积报告

本报告基于已抓取并校验的 BlaBlaLink 权威 Manifest 快照，对各业务资产分类进行全量盘点与体积预估。

## 1. 资产分级盘点总览

| 资产分类 | 资源描述 | 规格 / 格式 | 文件总数 | 预估单图体积 | 预估总大小 | 建议策略 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `portraits_si_default` | NIKKE 默认紧凑小头像 | 128x128 RGBA WebP | **200** | 5.5 KB | **1.07 MB** | **必须镜像 (Priority 1)** |
| `portraits_si_costumes` | Costume 皮肤紧凑小头像 | 128x128 RGBA WebP | **178** | 5.5 KB | **0.96 MB** | **必须镜像 (Priority 1)** |
| `common_icons` | UI通用图标 (属性/武器/企业/Burst/品级) | 63~400px WebP/PNG | **31** | 3~15 KB | **0.22 MB** | **必须镜像 (Priority 1)** |
| `equipment` | 装备图标 (ItemEquipTable) | 128x128 WebP | **72** | 12 KB | **0.84 MB** | **按需镜像 (Priority 2)** |
| `guild_emblem` | 公会徽章 (Guild Emblem) | 128x128 WebP | **78** | 8 KB | **0.61 MB** | **按需镜像 (Priority 2)** |
| `portraits_mi_default` | 默认角色半身立绘卡片 | 256x512 RGBA WebP | **200** | 28 KB | **5.47 MB** | 第二阶段/按需 |
| `portraits_mi_costumes` | 皮肤角色半身立绘卡片 | 256x512 RGBA WebP | **178** | 28 KB | **4.87 MB** | 第二阶段/按需 |
| `portraits_full_default` | 默认角色全身大立绘 | 2048x2048 RGBA WebP | **200** | 150 KB | **29.30 MB** | 第二阶段/按需 |

## 2. 关键决策与容量预算

- **Phase 1 核心镜像集 (Lineup Portraits + UI Icons)**：
  - 包含：200 默认 NIKKE 小头像 + 178 皮肤小头像 + 28 项核心 UI 图标；
  - 文件总数：**409 项**；
  - 磁盘预估占用：**约 2.25 MB**（极小，可直接全量持久化在本地 `data/nikke/blabla-assets/` 或直接交付，杜绝热路径任何网络请求）；
- **Phase 2 扩展镜像集 (Equipment + Guild + Cubes + Favorites)**：
  - 包含：124 装备 + 78 公会徽章 + 14 魔方 + 33 珍藏品；
  - 文件总数：**249 项**；
  - 磁盘预估占用：**约 2.7 MB**；
- **Medium / Full 大立绘评估**：
  - 378 款 `mi` 半身像需约 10.5 MB；
  - 378 款 `full` 全身大图需约 56.7 MB；
  - 目前 AstrBot 角色卡主立绘由 Spine 预渲染器负责，不占用此空间；`mi`/`full` 可作为静态立绘候选方案按需拉取。

## 3. 权威 Manifest 校验表

| Manifest 路径 | 记录总数 | 关键实体 | 校验状态 |
| :--- | :--- | :--- | :--- |
| `character/zh-tw/nikke_list_zh-TW_v2.json` | 200 角色 | 200 基础角色，178 款皮肤 | 已固化快照，哈希匹配 |
| `character/character_avatar_map.json` | 381 头像 | 381 个头像映射项 | 已固化快照，哈希匹配 |
| `character/character_id_map.json` | 1950 条目 | 1950 个突破/品阶对应条目 | 已固化快照，哈希匹配 |
| `equip/ItemEquipTable-zh-tw.json` | 124 装备 | 124 件装备基础信息 | 已固化快照，哈希匹配 |
| `guild/guild_emblem.json` | 78 徽章 | 78 款公会战/徽章图标 | 已固化快照，哈希匹配 |
| `raid/raid_list.json` | 10 赛季 | 10 个已记录赛季时间窗口 | 已固化快照，哈希匹配 |
