# Union Raid “我的”离线验收

## 范围

本增量只接线 `/妮姬 联盟突袭 我的` 的保守当前响应筛选，不声称完整赛季、分页、历史或真实出刀次数。

- 账号身份只取绑定记录中已有的 `game_openid`，并与响应中的 `openid` 做精确匹配。
- 缺少稳定身份、攻击列表不是数组、记录身份为空或记录结构异常时拒绝生成结果。
- 输出只包含当前账号的聚合结果，不输出 `openid`；空结果说明“当前响应未返回此账号的攻击记录”。
- 复用已有 `GetUnionRaidData` 单次请求，不增加成员详情或逐记录请求，因此没有 N+1 请求路径。

## 离线证据

- `tests/test_raid_participants.py`：精确身份筛选、跨成员隔离、空结果和畸形记录拒绝。
- `tests/test_union_raid.py`：中文命令 `/妮姬 联盟突袭 我的` 路由到个人范围处理器。
- `python -m compileall -q .`、`git diff --check` 和 Node 扩展测试在本工作树通过；完整 Python 矩阵以 PR CI 为准。

## 未宣称事项

本次没有访问真实账号、发送消息、部署或新增现场请求。仍需明确授权的最小现场动作是：读取一次脱敏的 `GetUnionRaidData` 响应，核对请求使用的 `game_openid` 与返回 `openid` 是否为同一 canonical identity，并确认返回范围与次数字段语义。合成 fixture、离线测试和当前响应文案不能替代该证据。
