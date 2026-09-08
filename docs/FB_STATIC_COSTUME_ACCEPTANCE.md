# 静态 FB / Costume 主链验收

状态：`READY_OFFLINE`（2026-09-08）。本记录只证明离线合同和合成测试，不代表真实账号、QQ 送达、部署或上游素材授权。

## 字段与资源合同

- `resource_id` 仅接受非负整数、纯数字字符串或安全的 Nikke-DB 标识；默认地址为 `images/FB/cXXX_00.png`。
- `costume_id` 保留在 `CharacterDetails → builder → CharacterCardData → AssetManager` 链路中。
- `assets/costumes.json` 只允许安全的 API costume ID 到 `c...` Nikke-DB asset ID。当前没有可核实的实际 costume 对照，因此正式清单为空；测试映射只存在于临时 fixture。
- default、known、unknown、invalid 四种状态互不复用。unknown/invalid 直接使用几何 fallback，不伪装成默认服装。
- 读取顺序为：默认服装本地明确 override → costume-aware 本地缓存 → Nikke-DB 静态 FB → 几何 fallback。

## 普通出卡边界

普通 `get_character_portrait()` 和 `resolve_character_assets()` 不导入、不构造、不探测 Spine，也不下载 skel/atlas 或投递队列。Spine 仅保留为显式 `enqueue_experimental_spine()` 实验入口，等待 P4 隔离。

同一静态缓存键继续使用 single-flight；角色卡预取固定为一项 portrait 任务，不按角色字段循环请求。

## 覆盖审计

仓库当前没有可声称完整的角色静态 registry。对已提交 fixture/测试中真实出现的 `resource_id` 审计如下：

| 原始 ID | 规范 ID | 默认 FB 路径 | 结论 |
| --- | --- | --- | --- |
| `470` | `c470` | `images/FB/c470_00.png` | 可解析，未声称远端存在性 |
| `c101`–`c105` | 原值 | `images/FB/c101_00.png`–`c105_00.png` | 可解析，未声称远端存在性 |
| 缺失/非法 | `missing` | 无 | 几何 fallback |

没有按名称、数组顺序或发布日期推导 ID。完整角色覆盖率仍为 `NEEDS_LIVE_EVIDENCE`，需要一份获准读取且带 `resource_id` 的当前角色目录后重新生成。

## 验证

- `tests/test_nikke_db_provider.py`：ID 规范化、严格 costume 文件、四状态隔离、静态 FB URL。
- `tests/test_asset_manager.py`：known costume 独立缓存、unknown/invalid fallback、single-flight、请求上限、普通路径零 Spine、costume 字段传递。
- `tests/test_card_builder.py`：`costume_id` 字段不丢失。

现场最小动作：只读获取当前角色目录并保存来源、时间与哈希；不需要玩家 Cookie，也不得把 URL 可构造等同于资源存在或授权。
