# Campaign History 数值合同验收

基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 当前验证检查点

- 本地 Python 3.10.11：`python -m pytest -q` → 264 passed、2 warnings、50 subtests passed。
- Campaign History 定向测试：`tests/test_campaign_history.py` → 29 passed、7 subtests passed。
- `tid`、`lv`、`combat`、`slot` 的字符串值现在只接受 ASCII 十进制数字；首尾空白和显式正负号均返回结构错误。
- 响应 `code` 必须是非布尔 JSON 整数；`False`、浮点和数字字符串不会与 `code=0` 混淆。
- `node --test tests\\extension.test.cjs` → 3 passed；`compileall -q .` 与 `git diff --check` 通过。
- 本次代码修订前检查点为 `6a6a641`，对应 CI run `34134245113`；文档提交后的最终 head 与 CI 必须重新查询，不能在此处自引用未来提交。

## 本次变更

- `tid`、`lv`、`combat`、`slot` 只接受 JSON 整数或十进制整数字符串。
- 响应 `code` 只接受非布尔 JSON 整数，避免 Python 的布尔/浮点相等比较误入成功或特定错误分支。
- 拒绝布尔值、小数、负数和 `tid=0`。
- `slot` 必须为 1–5；原有五槽位去重/完整性校验仍保留。
- 合法数字字符串继续支持，避免改变已观察到的响应兼容性。
- `code=0` 时缺失或非列表 `data.list`、非映射响应和非五人列表统一返回 `ERROR`；只有明确空列表返回 `UNAVAILABLE`。
- 异常输入统一返回 `ERROR` 和“历史阵容数据结构异常，请稍后重试”，不生成带异常数值的卡片，也不为超长列表继续遍历。

## 验证

- `tests/test_campaign_history.py`：29 passed、7 subtests passed。
- 已实际生成并查看合成 NORMAL 46-40 卡片：1400×820；五个槽位、等级、单体战力、总战力和缺图占位均可见。当前预览文件为 `E:/DevCache/nikke-campaign-preview-20260907-v2/campaign-0bbcc10f83b54396b231d5c418ae38ec.png`。
- 预览使用合成数据和本地占位素材，不访问真实账号、不下载真实账号数据、不执行账号写操作。

## 未宣称

- 本变更不证明官方历史阵容接口的全部字段，也不证明真实账号联调。
- `combat`、`lv` 的业务上限未凭空设定；这里只拒绝明显违反类型/符号合同的值。
