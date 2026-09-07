# Character Data V2 Increment A 合同

## 范围

本增量只整理当前仓库已经存在且可核验的三类静态资源标识：

- Equipment：`head`、`body`、`arm`、`leg` 资源槽位；`body` 在角色卡展示层对应 `torso`。
- Cube：Harmony Cube 标识。
- Favorite Item：Favorite Item 标识。

不在本增量中添加或推导角色 HP/ATK/DEF、技能、收藏品效果、OL 词条、Costume、角色属性或战斗公式。禁止从 combat 数值、ID 连续性或经验公式反推缺失字段。

## Registry 合同

`assets/registry_manifest.json` 对每类映射声明：

| 字段 | 约束 |
| --- | --- |
| `path` | 只允许指向预期的同目录 JSON |
| `source` / `source_ref` | 必填 provenance；当前明确为仓库维护的资源标识映射 |
| `checked_at` | 人工核验日期 |
| `sha256` | 对 JSON UTF-8 字节先将 CRLF 规范化为 LF，再做 SHA-256；避免跨平台 checkout 产生假损坏 |
| `license_boundary` | 只记录标识元数据，不表示游戏素材再分发授权 |

映射字段合同：

- ID 必须是十进制字符串；不做前导零补齐、模糊匹配或连续 ID 猜测。
- Equipment resource 必须符合 `icn_equipment_<head|body|arm|leg>_<attacker|defender|supporter>_t...`。
- Cube resource 必须符合 `harmony_cube_<id>`。
- Favorite Item resource 必须符合 `favorite_item_<id>`。

## 失败与 fallback

manifest 缺失、hash 不匹配、JSON 结构异常或资源标识非法时，该 registry 为空并记录校验错误；AssetManager 继续使用对应抽象占位图。未知 ID 返回 `None`，不将相近 ID 或远程 URL 当作已确认映射。

## 证据边界

这是静态标识 registry 的离线增量，不等同于完整 Character Data V2，不证明真实账号字段兼容、动态资源授权或远程素材可再分发。
