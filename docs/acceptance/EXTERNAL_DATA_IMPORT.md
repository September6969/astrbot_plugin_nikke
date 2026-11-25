# EXTERNAL_DATA_IMPORT.md — 可选外部数据导入 Schema、校验工具与运行期降级说明

> **许可与合规边界**：  
> 本插件公开仓库仅随附拥有明确开源/元数据许可的数据文件；同步器升级成本、单人突袭赛季 Boss 资料、超限词条推荐表与中文咨询题库由于缺乏合法可再分发开源授权，不内置未经许可的抓取数据，运营者可通过经授权来源按以下契约自行导入离线 JSON。

---

## 一、五类外部可导入 / 核验数据契约

| 数据类型 | 推荐放置路径（优先 `data_dir`） | 插件配置项（`_conf_schema.json`） | 核心校验入口 | 缺失时状态与运行时行为 |
|---|---|---|---|---|
| **同步器升级成本** (`sync_costs`) | `data/nikke/sync-level-costs.json` | `sync_level_cost_table_path` | `SyncCostTable.from_file()` | **DEGRADED**：不推测未知等级消耗；支持 `/妮姬 同步器 计算 手工 <当前> <目标> <库存3> <日产3> <累计成本3>` 直接计算 |
| **单人突袭赛季** (`solo_raid_seasons`) | `data/nikke/solo-raid-seasons.json` | `solo_raid_season_path` | `SeasonCatalog.from_file()` | **DEGRADED**：五队编组、互斥与爆裂链检验仍全功能可用；未导入赛季表时明确提示先导入赛季 JSON |
| **超限词条推荐** (`overload_recommendations`) | `data/nikke/overload-recommendations.json` | `overload_recommendations_path` | `load_recommendations()` + `load_character_targets()` + `load_default_line_counts()` | **DEGRADED**：缺失时仍可根据玩家命令行指定目标词条与官方 `assets/data/overload_tiers.json` 给出锁/洗建议与概率模拟 |
| **咨询答案题库** (`counsel_bank`) | `data/nikke/counsel-bank.json` | `counsel_bank_path` | `CounselBank.from_file()` | **BLOCKED**：当前未内置合法中文题库，缺失时明确提示「尚未导入合法授权题库」，绝不伪造答案 |
| **愿望单卡池准入覆盖** (`wishlist_eligibility`) | `data/nikke/wishlist-pool-eligibility.json` | 自动叠加 `assets/data/wishlist_pool_eligibility.json` | `load_pool_eligibility()` | **READY（内置基线）/ FAIL-CLOSED**：准入状态未知角色默认拒绝推荐；覆盖表无效时回退基线且拒绝越界放行 |

---

## 二、统一离线校验 CLI

使用仓库提供的校验脚本验证任何待导入文件（必须包含 `schema_version`、`checked_at` / `source_url` 或 `license`  provenance 字段）：

```bash
python scripts/operations/validate_external_data.py sync_costs path/to/sync-level-costs.json
python scripts/operations/validate_external_data.py solo_raid_seasons path/to/solo-raid-seasons.json
python scripts/operations/validate_external_data.py overload_recommendations path/to/overload-recommendations.json
python scripts/operations/validate_external_data.py counsel_bank path/to/counsel-bank.json
python scripts/operations/validate_external_data.py wishlist_eligibility path/to/wishlist-pool-eligibility.json
```

退出码：
- `0`：Schema 与业务不变式校验通过；输出 JSON 摘要（类型、条数、覆盖范围 / `checked_at`）。
- `1` / `2`：文件不存在、JSON 解析失败或违反合同，输出中文原因并拒绝导入。

---

## 三、各文件最小 Schema 示例

### 3.1 `sync-level-costs.json` (`sync_costs`)
```json
{
  "schema_version": 1,
  "source_url": "https://example.invalid/sync-costs.json",
  "checked_at": "2026-11-24",
  "levels": [
    {"level": 200, "core_dust": 10000, "credits": 500000, "battle_data": 200000},
    {"level": 201, "core_dust": 10000, "credits": 520000, "battle_data": 210000}
  ]
}
```

### 3.2 `counsel-bank.json` (`counsel_bank`)
```json
{
  "schema_version": 1,
  "source_url": "https://example.invalid/counsel-zh.json",
  "license": "CC-BY-4.0 / authorized-maintainer",
  "checked_at": "2026-11-24",
  "entries": [
    {
      "id": "q-001",
      "nikke": "拉毗",
      "aliases": ["Rapi"],
      "question": "作战时应优先采用哪种策略？",
      "keywords": ["作战", "策略"],
      "options": [{"id": "a", "label": "稳步推进"}, {"id": "b", "label": "盲目突击"}],
      "answer_id": "a",
      "source_url": "https://example.invalid/counsel-zh.json"
    }
  ]
}
```
