# StateEffectRegistry 验收记录

状态：`PARTIAL_LIVE_VERIFIED`（四条公开/现场交叉核验子集）/ `READY_OFFLINE`（合同与接线）。证据见 `docs/evidence/arcana_live_20260909.json` 与 `docs/evidence/state_effect_registry_live_20260909.json`。

## 合同

每条有来源的 registry 记录必须同时包含：

- `option_id`、可选 `state_effect_id` / `group_id`、`function_type`；
- 本地化 `label`、`locale`；
- `value_kind`：`percent`、`flat`、`seconds`、`count`、`multiplier` 或 `unknown`；
- 可选且来源明确的 `value_divisor`；
- 无凭据 HTTPS `source_url`、64 位 `source_sha256` 和 `checked_at`。
- 若 divisor 来自独立展示规则，还要登记成对的 `value_source_url` / `value_source_sha256`。

没有来源 hash、重复键、含凭据 URL、非法单位或模糊 ID 的记录全部不进入 registry。当前提交的 `assets/state_effects.json` 登记四条 exact 子集并标记 `PARTIAL_LIVE_VERIFIED`；没有把单账号样本冒充全量映射。

## 接线

`CharacterCardBuilder` 默认加载该 registry。命中证据记录时使用其 label/formatter；未命中时保留既有安全 mapping，未知单位仍显示待确认且不进入确认单位汇总。动态数值只来自 `CharacterDetails.state_effects`，不从 option 相邻 ID 或角色顺序推导。registry 不再以 function_type 单独回退，避免不同 option 共享类型时误显示。

## 验证

- 有来源记录可将 `StatChargeDamage` 的原始值按显式 divisor 转成 percent；
- 缺失来源或 option_id 不精确匹配不解析；
- 四条记录的公开标签、group ID、现场 function type/value type 和 `/100` 展示规则有来源哈希；
- 真实 CDN metadata、完整 function_type 覆盖、准确 1–15 tier table、HP/ATK/DEF 公式和现场角色卡仍需后续证据；
- 当前四条记录是部分闭环，不声称完整数据库。

