# OL 1--15 注册表验收

## 已完成

- 从实时公开 BlaBlaLink CDN 取得 StateEffect 分组 JSON，并保存来源 URL、SHA-256 和核验日期。
- 精确登记 9 个 OL 分组、27 条来源记录和 135 个 `state_effect_id`，每个分组覆盖等级 1--15。
- 按当前公开前端的 `record.id % 10` 与分组列表位置计算等级；不按相邻 ID、角色顺序或名称推断。
- `CharacterCardBuilder` 在 option 自带等级缺失时使用已核验的 OL 等级；未知 function type 仍显示“未识别词条”，不猜单位或数值。
- 上游同一响应中的 3 条通用 `931xxxx` 记录保持排除，不伪装为 OL。

## 证据边界

本主题闭合的是 OL 分组、标签和 1--15 阶级语义，不是每个账号的动态数值表。动态 `function_value` 只有在 function type、value type 和来源 registry 同时确认时才进入汇总；未知值继续显示安全 fallback。

现场来源：[overload_tier_registry_live_20260909.json](evidence/overload_tier_registry_live_20260909.json)。

## 测试

- `tests/test_overload_tier_registry.py`：3 passed。
- `tests/test_card_builder.py` 与注册表定向组合：19 passed。
