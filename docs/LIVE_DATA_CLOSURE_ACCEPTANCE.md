# Live data closure acceptance

## 已完成

- 使用一个已绑定且获授权的真实账号完成只读 roster 与批量 `GetUserCharacterDetails`：177 个角色、一次 `name_codes` 批量请求、177 条详情。
- 将现场观察到的 109 条 OL option/function 精确映射接入 `assets/state_effects.json`；每条都保留公开分组来源、现场响应内容 SHA-256 和核验日期。
- `Percent` 使用已查前端语义 divisor 100；`Integer` 只保留标签和 function type，单位为 unknown，不进入确认汇总。
- 角色卡继续由严格 registry 处理异常值；未知 function、缺失值和未知单位不会借用相邻 option 或静默反推。
- 真实详情、个人资料接口均未提供 HP/ATK/DEF 字段或公式来源；没有把 combat/team_combat 反推成三项属性。
- 在现场已授权范围内完成一次 Signin：前态为 found=true/completed=false，写入尝试 1 次，后态 completed=true；未自动重发，证据见 `docs/evidence/signin_live_20260909.json`。

## 证据边界

这是一个账号当前持有角色集合的现场闭环，不声称覆盖未出现的 option ID，也不把账号动态数值当作公共静态表。现场原始响应只在内存中使用，仓库仅保存结构、计数、来源和哈希。

证据：

- [live_character_stats_20260909.json](evidence/live_character_stats_20260909.json)
- [state_effect_function_inventory_live_20260909.json](evidence/state_effect_function_inventory_live_20260909.json)

## 验收测试

- state-effect registry + card builder 定向测试：21 passed。
