# AEL 残留清理验收

## 状态

`READY_OFFLINE`：产品代码、README、NOTICE 和产品测试不再包含 AEL 计算或评分入口。

## 变更

- 删除 `BlaBlaClient.calculate_ael()`；该函数在当前产品链路中没有调用方，不能作为玩家数据或角色卡字段使用。
- 删除只验证该未接线公式的单元测试，并保留角色卡缺失字段的中性语义测试。
- README 功能与测试说明不再声称提供 AEL 数据或计算。
- NOTICE 不再声明移植 AEL 计算方法；其他 API 调用流程和异常恢复来源说明保持不变。
- `docs/DEVELOPMENT_PLAN.md` 中的历史路线记录保留，不作为当前产品入口或完成能力声明。

## 验证

- 在排除历史路线文档后，`rg -i "AEL|calculate_ael"` 不再命中产品代码、README、NOTICE 或测试。
- `tests/test_core.py` 与 `tests/test_character_card_renderer.py` 定向测试通过。
- 未修改数据库 schema、配置、账号凭据或远程服务器状态。
