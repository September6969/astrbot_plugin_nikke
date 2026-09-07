# Character Data V2 Increment A 验收

## 当前验证检查点

- 本地 Python 3.10.11：全量 `pytest -q` → 261 passed、2 warnings、49 subtests passed。
- Character Data V2 定向测试 → 26 passed、6 subtests passed。
- `node --test tests\\extension.test.cjs` → 3 passed；`compileall -q .` 与 `git diff --check` 通过。
- 本次文档修订前代码检查点为 `2e77ad2`，对应 CI run `34124685883`；文档提交后的最终 head 与 CI 必须重新查询，不能在此处自引用未来提交。
- 本次重新生成并实际查看的合成预览：`E:/DevCache/nikke-character-preview-20260907-cd11-v2/red-hood.png`、`alice.png`、`fallback.png`；未读取真实账号或远端资源。

## 本地行为验证

定向测试：

```text
python -m pytest -q tests/test_static_registry.py tests/test_asset_manager.py tests/test_card_builder.py tests/test_character_card_renderer.py
```

结果：`26 passed`、`6 subtests passed`。

覆盖点：

- 三类 registry 的 metadata、精确 ID 查找、重复键拒绝与资源标识合同；
- 未知 ID 不归一化、不猜测；布尔、浮点、带空白或符号的 ID 被拒绝；
- 单个 JSON hash 损坏或存在重复键时只禁用对应 registry，其余 registry 仍可用；
- AssetManager 使用 registry，并在未知/缺失资源时继续返回占位图，即使同名本地缓存或 `sources.json` 项存在也不显示或请求它；
- 角色卡四个装备槽、词条单位、缺失数值和合成卡渲染原有行为保持通过。

## 状态分层

| 维度 | 状态 |
| --- | --- |
| 代码状态 | DONE：三类静态标识纳入 manifest + hash + strict parser |
| 测试状态 | DONE：全量 Python `261 passed, 2 warnings, 49 subtests passed`；Node `3 passed`；compileall 与 diff-check 通过。当前 Windows 依赖环境会在 pytest 输出中打印 native-trace，但进程退出码为 0，不能以该输出替代行为测试证据 |
| 合成预览 | DONE_FOR_OFFLINE：预览脚本现可从仓库根目录直接执行；已生成并实际查看 `E:/DevCache/nikke-character-preview-19c087983ff44e7d940fdc50fe4dcb2b/red-hood.png`、`alice.png`、`fallback.png`，不读取真实账号或远端资源 |
| 现场证据 | NEEDS_LIVE_EVIDENCE：真实账号字段、最新官方数据、远程资源许可 |
| 产品状态 | PARTIAL：不是完整 Character Data V2，不添加动态角色属性/技能/OL/Costume 映射 |

预览观察：四个装备槽均可见，缺失立绘使用抽象占位图；未知 registry ID 即使存在同名本地缓存也不会显示其图标；合成 fixture 仍报告 `StatChargeDamage` 的 integer/percent 类型不匹配并降为 unknown，这是既有字段语义证据，不在本 registry 增量中猜测修正。

## 最小现场动作

如未来获得明确只读范围，应分别记录源响应字段、获取日期和许可边界，再生成新的 manifest/hash；不得用现场动作自动写入账号、发送消息或消费 CDK。本增量不执行这些动作。
