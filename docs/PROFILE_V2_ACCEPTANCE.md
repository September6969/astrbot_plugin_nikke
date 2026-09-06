# Profile V2 验收记录

## 主题与目标命令

- 用户能力：`/妮姬 我的`
- 起始 base：`origin/main@a812b7247e997e87886d9c076459bb2463123b15`
- 工作树：`E:/DevCache/nikke-profile-v2/astrbot_plugin_nikke`
- 分支：`feat/profile-v2`
- 实现提交：`59f0f59 feat: harden profile v2 dashboard semantics`
- 本记录和当前最终 HEAD 由交接时的 Git 状态补充确认；不在文档中预写未来 SHA。

## 用户可见变化

`/妮姬 我的` 继续沿用既有 `client → ProfileBuilder → ProfileCardRenderer` 链路：

- BASIC、CAMPAIGN、OUTPOST、ROSTER、COLLECTION、RESEARCH、MORE 分区按固定顺序输出。
- Normal/Hard 主线独立为 CAMPAIGN；研究、收藏和点唱机不再在 OUTPOST 重复显示。
- 可选资料失败时保留 basic 的可靠角色数/时装数，并显示失败状态；不制造空集合或虚构零值。
- 合法 `0` 保留；缺失、非法、接口失败、已知空数组和局部损坏分开表达。
- 研究/收藏部分损坏时保留可靠条目并标记“部分”，不显示由局部条目求出的完整合计；未知研究/收藏类型使用中性序号名称。
- 长昵称、长主线、大数字和超过 30 条的结构化列表有省略或“其余项目”提示。

## 字段合同与状态

| 输入 | 合同与处理 | 显示归属 |
| --- | --- | --- |
| `basic.nickname`、账户回退名称 | 标量文本；空白、容器和控制字符安全降级；不显示内部账户标识 | 页头 |
| `account.area_id` | 标量区域值；不可用时留空，不猜服务器名称 | BASIC |
| `basic.lv`、`team_combat`、`character_count`、`character_costume_count` | 非负整数或已确认的十进制整数字符串；`bool`、浮点、坏字符串、非有限值、负数和超长整数为未知；不静默截断 | BASIC / ROSTER |
| `progress_normal_campaign`、`progress_hard_campaign` | 只使用现有字段及兼容字段；安全文本显示，不推导新进度 | CAMPAIGN |
| `outpost.synchro_level`、`outpost_battle_level` | 同上非负整数语义；合法 `0` 保留 | OUTPOST |
| `infra_core_level`、战术学院字段 | 只作安全标量显示，不把一个字段拼成另一个字段的完整进度 | OUTPOST |
| `roster`、`roster[].lv/combat` | 完整且每条可解析时才计算数量/最大值；有坏条目则保留 basic 计数、隐藏不可靠最大值并标记局部结果；`[]` 可表达已知空列表 | ROSTER |
| `recycle_room_researches` | 保留列表位置和可靠等级/EXP；未知 `tid` 只用本地 registry 或中性序号；部分列表不计算等级合计 | RESEARCH |
| `memorial_counts` | 保留可靠计数；分类不做未经证实的映射，不求独立收藏总量；坏计数标记部分 | COLLECTION |
| `jukebox_count` | 作为独立已证明计数，只显示一次 | COLLECTION |
| optional endpoint 状态 | `outpost_available` / `roster_available` 区分失败与成功空结果；`CancelledError` 和 `CookieExpired` 不降级吞掉 | OUTPOST / ROSTER |

## 已完成接线与请求预算

- `client.get_profile_dashboard` 并发调用 basic、outpost、roster 各一次。
- basic 响应结构异常仍按必需数据失败处理；outpost/roster 普通错误保留局部 dashboard。
- optional `CookieExpired` 和取消信号继续抛出，由 `me` 的既有身份/反馈路径处理。
- `NikkePlugin.me` 把 optional 状态传入真实 ProfileBuilder；renderer 不发网络请求。
- synthetic command-chain 测试断言 `GetUserProfileBasicInfo`、`GetUserProfileOutpostInfo`、`GetUserCharacters` 各一次，未调用 `GetUserCharacterDetails`。
- 未访问真实账号、未发送真实请求、未执行账号写操作或消息发送。

## 测试结果

在 Python 3.10.11、复用 `E:/DevCache/nikke-test-venv` 环境执行：

```text
python -m compileall -q .                    PASS
PYTHONPATH=E:/DevCache/nikke-profile-v2 python -m pytest -q
256 passed, 2 warnings, 43 subtests passed
node --test tests/extension.test.cjs          3 passed
```

新增 synthetic 行为测试覆盖：坏数值、`bool`/浮点/NaN、合法零值、空数组、坏列表和局部统计、未知研究/收藏类别、optional endpoint 失败与 CookieExpired、真实 Builder/Renderer 出图、真实 `me` 命令链和请求次数。

## 合成预览与实际查看

预览仅保存在源码树外的临时目录，不提交 Git：

| 样例 | 文件 | 实际查看结果 |
| --- | --- | --- |
| full | `E:/DevCache/nikke-card-preview/profile-v2-20260906/profile-55a876f374014ab1ae2bfd0639626254.png` | 七个区块顺序正确；收藏/研究只在各自区块出现；页脚与末行不重叠 |
| sparse | `E:/DevCache/nikke-card-preview/profile-v2-20260906/profile-b60ac174f9a94cbca79cca1450734273.png` | 角色数/时装数保留；前哨和花名册分别显示获取失败；没有假的 `0` 或空研究/收藏面板 |
| stress | `E:/DevCache/nikke-card-preview/profile-v2-20260906/profile-a4107481a2ef4d2794cb553517933b77.png` | 长昵称/主线省略；大数字不越界；研究和收藏各显示 30 条并提示剩余 5/6 项；页脚无遮挡 |

当前 Profile renderer 只有默认主题，没有第二套已支持的 Profile 主题可供比较；本次没有新增主题。三张 PNG 均可读取，渲染后使用 `Image.open` 检查格式/尺寸并关闭句柄。

## 状态与证据缺口

- **READY**：离线命令到 PNG 闭环、字段异常语义、分区去重、三请求预算、行为测试和默认主题预览。
- **RESEARCHABLE**：后续可继续补充已确认字段，但本 PR 不猜 Favorite Item、Attractive Level 或未证明的属性公式。
- **NEEDS_LIVE_EVIDENCE**：授权账号上的真实响应兼容性、真实 `/妮姬 我的` 网络联调和部署环境图片；本次按边界不执行。
- **NEEDS_HUMAN_DECISION**：无；本 PR 不涉及许可采用、部署或消息发送。
- **HARD_BLOCKED**：无已确认永久技术阻塞。

## 交接

本分支基于最新 `origin/main` 独立开发，不包含 A 的未合并提交。后续动作是补充实际最终 HEAD、push `feat/profile-v2` 并创建 base=`main` 的 Draft PR；PR 描述应保留上述离线验证与真实证据缺口的区分。
