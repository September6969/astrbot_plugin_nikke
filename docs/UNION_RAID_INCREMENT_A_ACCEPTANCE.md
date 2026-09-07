# Union Raid Increment A 验收记录

## 范围与基线

- 起始 base：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 工作树：`E:\DevCache\nikke-union-raid-v2\astrbot_plugin_nikke`
- 分支：`feat/union-raid-v2`
- 实现提交：`f93b5410bff6ec3e2e874b1b51c40806ddc1e585`（`fix: reject invalid raid ranking identifiers`）。
- PR：[#8 Feat: harden Union Raid response semantics](https://github.com/September6969/astrbot_plugin_nikke/pull/8)（`OPEN` / `DRAFT`，不自动合并）。
- 已核验 branch checkpoint：`f93b5410bff6ec3e2e874b1b51c40806ddc1e585`。
- 已核验 CI：[34113574455](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34113574455) `SUCCESS`，其 `headSha = f93b5410bff6ec3e2e874b1b51c40806ddc1e585`，与 checkpoint 相同。

本增量只加固已有 `/妮姬 联盟突袭` overview 和 `/妮姬 联盟突袭 排名` 的当前响应语义；不接线历史赛季或“我的战斗”，不访问真实账号，也不新增网络 endpoint。

## 字段与范围合同

| 项目 | 本增量合同 |
| --- | --- |
| `level_info` | 只有恰好一个字典项时才读取难度、等级和 Boss；多项、空项或非列表不取首项，标记 `UNKNOWN_COVERAGE`。 |
| Boss ID | 仅接受非空文本或明确整数；布尔值、浮点、容器和空值视为坏 ID，保留返回记录但使覆盖未知并隐藏聚合，不任意删除记录或假装完整。 |
| HP | 仅接受 `int` 或十进制整数字符串；`bool`、浮点、坏字符串、容器值为未知。既有负整数归零 clamp 语义保留。 |
| 聚合 | 仅对一个无部分记录且 HP 完整的响应计算“已返回 Boss 加权进度”；从不称完整赛季或当前阶段总进度。 |
| 排名 | 按当前响应内已返回记录的伤害字段聚合；显示“条返回记录”，不称真实攻击次数或“刀数”；空白身份、空/非标 Boss ID 或角色 ID 拒绝聚合。 |

## 实际接线

`NikkePlugin.union_raid` → `BlaBlaClient.get_union_raid_overview` → `UnionRaidBuilder` → `UnionRaidRenderer`。

`NikkePlugin.union_raid_ranking` → `BlaBlaClient.get_union_raid_data` → `build_ranking` / `format_ranking`。

本次没有添加 `GetUserCharacterDetails`、历史赛季或任何额外请求；builder、renderer 和排名格式化也没有循环内 client 调用，未引入 N+1 请求。

## 本地验收与预览

- Raid A 定向回归（`tests/test_raid_increment_a.py tests/test_raid_participants.py tests/test_union_raid.py`）：`24 passed, 2 warnings, 16 subtests passed`；额外覆盖坏 Boss ID 的保守解析，不把容器或浮点转换成伪 ID。
- 当前源码全量回归：`python -m pytest -q` → `267 passed, 2 warnings, 59 subtests passed in 16.70s`。
- 当前静态/扩展回归：`python -m compileall -q .` → exit 0；`node --test tests/extension.test.cjs` → 3 passed；`git diff --check` → exit 0。
- 本次恢复后的 PATH Python 为 `C:\Python314\python.exe`，不含 `pytest`；这是临时测试运行器缺少 CI 依赖，不等同于产品测试失败。PR 的 Python 3.10/3.11/3.12 CI 是最终独立验证。
- 合成 PNG（未提交源码）：`E:\DevCache\nikke-card-preview\raid-increment-a-20260906\`。
  - 完整单项响应：范围文案显示“本次响应范围（非完整赛季）”，卡片无截断。
  - 多阶段项：不选数组首项，不展示 Boss 或聚合。
  - 重复 Boss：保留返回项，显示覆盖未知且不显示聚合。

所有预览均为离线合成输入，实际查看过 PNG；不能视为真实账号联调或资源授权。

## 证据缺口与后续

- `GetUnionRaidLevelInfo` 的多项排序、分页、重复原因与完整范围尚未由授权现场响应证实。
- 历史赛季与 canonical identity 属于后续独立增量，不能由本次离线语义推断。
- 最小现场动作是一次明确授权的真实账号只读采样、脱敏后与本合同比较；未执行。
- 下一独立主题：Announcement V2；从最新 `origin/main` 创建工作树，不把其提交接到本 PR 上。
