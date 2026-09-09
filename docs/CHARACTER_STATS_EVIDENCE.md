# CharacterDetails HP / ATK / DEF 证据登记

状态：`NEEDS_LIVE_EVIDENCE`。本文件只记录字段合同核验结果，不把脱敏 fixture、公开实现或模拟属性当作真实账号值。

## 已核对来源

| 来源 | 观察 | 结论 |
| --- | --- | --- |
| 本仓库 `tests/fixtures/character_details_sanitized.json` | 角色详情包含等级、战力、装备和技能字段；没有可确认的 `hp`、`attack`、`defense` 账号字段 | 不能从 fixture 补造字段 |
| `card_builder.py` | 只接受明确的 `detail["hp"]`、`detail["attack"]`、`detail["defense"]`，坏值转为缺失 | 保留 `—` fallback |
| [ExiaInvasion README](https://github.com/ExiaProject/ExiaInvasion/blob/main/README.en.md) | `simulated_hp` / `simulated_atk` / `simulated_def` 是可选的模拟属性，且可按 400 级开关计算 | 不能作为账号 CharacterDetails 值接入 |
| [monster NIKKE mapping refresher](https://github.com/monster1389/astrbot_plugin_nikke_news/blob/master/player/player_mapping_refresher.py) | 公开实现从 Bla CDN `equip_table` 提取角色名、resource_id、state-effect option 元数据；未提供 HP/ATK/DEF 账号字段合同 | 可作为后续 StateEffect registry 的结构参考，不作为 HP/ATK/DEF 证据 |

## 脱敏诊断

`character_detail_diagnostic.py` 与 `scripts/diagnose_character_details.py` 只输出：

- 字段名；
- JSON 类型；
- 是否非空（合法 `0` 保持非空）；
- 整数/小数形状、位数、符号范围。

不输出原始数值、Cookie、token、openid 或其他敏感字段。对多个 `character_details` 输入保持稳定顺序，但不写入角色名或账号标识。

## 最小现场动作

在获得明确授权的测试账号后导出一次脱敏的 `GetUserCharacterDetails` 响应，运行：

```text
python scripts/diagnose_character_details.py sanitized_character_details.json
```

只将字段名/类型/形状登记到证据文件；只有当 Bla CharacterDetails 明确确认 HP/ATK/DEF 字段语义后，才允许更新 builder。若响应没有这些字段，角色卡继续显示 `—`，不从 combat、等级或 simulated stats 反推。

