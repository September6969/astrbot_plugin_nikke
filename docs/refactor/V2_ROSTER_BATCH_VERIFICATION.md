# 练度查询批量详情验证（REFACTOR_PLAN_V2 PR-4A 前置步骤）

计划要求先做只读接口验证，再决定请求策略，不预设"必须降为 2 次请求"。本 PR **没有**改变请求策略：Top 20 仍然逐个请求单角色详情。这里只消除了一处已确认的重复请求，并补上了验证工具。

## 本 PR 已完成的部分（不依赖实测）

| 项 | 变化 |
| --- | --- |
| 重复拉取名单 | 之前每个单角色详情都会再调用 `get_roster(False)`（缓存键与已有的 `("roster", True)` 不同，所以缓存不命中）。现在先复用 30 秒内的完整名单缓存。Top 20 场景的请求数从约 23 次 POST 降到 22 次（1 次名单 + 1 次批量技能 + 20 次单角色） |
| 延迟反馈 | 练度总览开始时先发"正在读取练度与词条详情" |
| 基准记录 | `features/character/application.py` 在 debug 级别记录角色数、详情数和耗时 |
| 并发上限 | `BlaBlaClient` 对上游的并发请求数上限为 6 |

## 需要在真实只读账号上执行的验证

```bash
python scripts/operations/verify_character_details_batch.py \
  --live-readonly --data-dir /实际路径/AstrBot/data/nikke --top 20 --delay 1
```

- 脚本要求数据目录里恰好只有一个绑定账号；
- 只发只读请求：1 次名单、1 次全量批量、1 次 Top 20 批量，再加 20 次单角色请求，单角色请求之间间隔至少 0.5 秒；
- 输出不含 Cookie、OpenID 或任何数值，只有 name_code、不一致的字段名和计数。

离线复核：把两份脱敏响应保存下来后执行

```bash
python scripts/operations/verify_character_details_batch.py --batch batch.json --singles singles.json
```

## 根据结论选择落地方案

| 结论 | 后续做法 |
| --- | --- |
| `full_batch_vs_single.all_consistent = true` | 直接复用 `get_roster(True)` 那次全量批量响应里的装备、词条和 `state_effects`，Top 20 不再逐个请求（总共约 2 次 POST） |
| 只有 `top_batch_vs_single.all_consistent = true` | 把 Top 20 合并成 1–4 批请求 |
| 两项都有缺失或截断 | 保持逐个请求，另外用实测找出安全的批大小 |

验证结果出来之前，代码保持逐个请求的实现，确保数据 100% 一致。
