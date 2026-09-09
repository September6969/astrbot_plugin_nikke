# StateEffectRegistry 验收记录

状态：`READY_OFFLINE`（合同与接线）；具体 Bla CDN metadata、精确 OL 1–15 阶表和资源来源 hash 仍为 `NEEDS_LIVE_EVIDENCE`。

## 合同

每条有来源的 registry 记录必须同时包含：

- `option_id`、可选 `state_effect_id` / `group_id`、`function_type`；
- 本地化 `label`、`locale`；
- `value_kind`：`percent`、`flat`、`seconds`、`count`、`multiplier` 或 `unknown`；
- 可选且来源明确的 `value_divisor`；
- 无凭据 HTTPS `source_url`、64 位 `source_sha256` 和 `checked_at`。

没有来源 hash、重复键、含凭据 URL、非法单位或模糊 ID 的记录全部不进入 registry。当前提交的 `assets/state_effects.json` 为空并标记 `NEEDS_LIVE_EVIDENCE`，不会制造映射。

## 接线

`CharacterCardBuilder` 默认加载该 registry。命中证据记录时使用其 label/formatter；未命中时保留既有安全 mapping，未知单位仍显示待确认且不进入确认单位汇总。动态数值只来自 `CharacterDetails.state_effects`，不从 option 相邻 ID 或角色顺序推导。

## 验证

- 有来源记录可将 `StatChargeDamage` 的原始值按显式 divisor 转成 percent；
- 缺失来源或非唯一 function_type 不解析；
- 空 registry 保持有效但无 entries；
- 真实 CDN metadata、完整 function_type 覆盖、准确 1–15 tier table 和现场角色卡仍需后续证据。

