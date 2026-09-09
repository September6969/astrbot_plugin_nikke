# CharacterCard 数值语义验收记录

状态：`READY_OFFLINE`；真实账号 HP/ATK/DEF 字段、单位和服务端公式仍为 `NEEDS_LIVE_EVIDENCE`。

## 合同

- CharacterDetails 的整数形状只接受 JSON 整数或十进制整数字符串；bool、浮点、空白/非法字符串、NaN、Infinity 和非标量不作为整数。
- HP、ATK、DEF 只接受非负整数。缺失、负数或异常统一保留未知，由 renderer 显示 `—`。
- level、combat、skill、grade、core 的异常输入使用安全零值，避免 malformed response 让整张卡构建失败；不从其他字段反推。
- `function_value` 必须是有限标量；缺失、非有限或无法解析时显示“未识别词条”、单位为 `unknown`，且不进入 option totals。

## 验证

- `tests/test_card_builder.py` 覆盖字符串整数、bool、浮点截断、负数、NaN、Infinity、非法字符串和异常词条值。
- 角色卡既有渲染合同保持不变：HP/ATK/DEF 的 `None` 输出 `—`，未知词条不进入汇总。
- 完整测试、compileall、Node 扩展和 diff check 必须在 PR 中记录；本文件不把 fixture 或合成图描述为真实账号数值证据。

## 边界

本主题没有执行账号读取、账号写入、QQ/NapCat 消息、部署或任何数值公式猜测。后续现场动作仅记录真实字段存在性、类型和最小单位证据，不保存原始响应。
