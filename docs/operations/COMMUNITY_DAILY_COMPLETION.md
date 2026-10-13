# 社区日常补全与接口证据

核实日期：2026-10-13。以官方公开网页代码为接口合同证据；没有调用真实账号签到、领奖，没有部署或实际发送通知。

## 用户入口

- `/妮姬 日常`：签到后查询并领取已达成的免费新手任务奖励，逐项报告。
- `/妮姬 日常 状态`：只读查看签到、奖励状态及最近执行结果。
- `/妮姬 日常 自动 开|关`：本人选择自动执行；开表示签到加免费领奖。请在私聊使用日常命令登记通知路由。
- `/妮姬 签到 [状态]`：保留仅签到语义。

全局 `enable_daily_actions` 仍默认关闭。旧自动偏好只签到，重新开启后才升级；范围绑定到当前游戏身份。群汇总开关不控制自动执行，新版社区日常成功静默，不进入旧签到群汇总。异常按账号、UTC日期及类别私聊一次，没有已确认私聊路由时只保留可查询结果。

## 已确认的官方合同

1. 任务列表：GET `/api/lip/proxy/lipass/Points/GetTaskListWithStatusV2`，参数 `get_top=false`、`intl_game_id`，响应 `data.tasks`。
2. 签到：任务类型 `task_type=1`，POST `/api/lip/proxy/lipass/Points/DailyCheckIn`，请求 `task_id`。官方页面使用奖励条目的 `is_completed` 显示签到完成；本实现严格检查所有奖励，不接受字符串布尔值或相互矛盾的状态。签到不额外调用积分兑换。
3. 免费新手任务列表：POST `/api/game/proxy/Game/HasFinishOnboardingMissionList`，请求空对象，响应 `data.mission_done_list`。`tag_id` 1～5 对应登录、社区绑定、游戏绑定、添加桌面、关注。`mission_status` 0=未完成、1=完成待领、2=已领取。
4. 领取：POST `/api/game/proxy/Game/OnboardingMissionGiftCollection`，请求 `{tag_id}`，随后重新查询对应状态确认。只对状态1提交；不调用 `AddFinishOnboardingMission` 或关注接口。
5. 周期：官方刷新提示组件使用 `utc().startOf(day).local()`，即 UTC00:00、北京时间08:00。签到使用 UTC 日期；新手奖励为一次性 `onboarding-v1` 周期，不按天重复。

官方脚本证据：
- [index-CGPU0lk3.js](https://www.blablalink.com/assets/nikke/version/default/assets/index-CGPU0lk3.js)：SHA-256 `6d484428def17e0f16003782928bb3086e0366fcbcacb7f2b79b83ad5dddab4e`。
- [v4-DaeRWrZK.js](https://www.blablalink.com/assets/nikke/version/default/assets/v4-DaeRWrZK.js)：SHA-256 `1c62cf5b6f63d2383bee6b444eddc98cb6d9b8da1ec4239befcc7baf7f8b69b5`。
- [refresh-tag-CgrTy1wd.js](https://www.blablalink.com/assets/nikke/version/default/assets/refresh-tag-CgrTy1wd.js)：SHA-256 `318b459786dbf0883d73cae99c37786dbac08faf19b246f91db043bbc71502a0`。

参考 [BlablalinkTasker](https://github.com/1204244136/BlablalinkTasker) 的行为说明与源代码。本次独立实现，没有复制其代码。该项目的月度兑换消耗代币，点赞／浏览也属于额外操作，均未接入。

## 状态与兼容

签到与领奖共享稳定游戏身份锁；每个奖励持久化提交意图。超时、取消或核验失败保留未知状态，之后只查不重发。再次执行仍检查新增可领奖励。一次性奖励的已完成记录不会因重启或跨日消失。已成功的项目和失败项目分别保留。

自动任务错过设定时刻后可补跑，运行前重新检查账号绑定和本人开关。签到使用 community-utc 周期命名空间；旧北京时间成功记录需重新查询，不直接当作新周期成功；同一社区周期可能覆盖的旧日期若有未知写入，只读恢复，不重发。旧签到执行记录继续保留，不能代表全部免费奖励已经领取。群汇总只读已有结果，不能因为缺失摘要再触发写操作。

## 验收边界

新增离线测试覆盖多奖励、严格状态解析、签到后领奖、同日新增奖励、跨日与重启去重、未知结果、取消、并发、旧自动范围、私聊路由及绑定变化。完整测试结果随交付报告记录。

历史文档 `LIVE_EVIDENCE_REGISTER.md` 与 `signin_live_20260909.json` 曾记录一次真实签到成功；这不等于本轮版本或新增领奖已做真实验收。新增领奖仅有官方前端证据与模拟合同测试。

当前免费领奖覆盖官方新手任务列表。普通日常任务的积分由网站完成流程处理，未发现可复用的通用逐项领取合同；其他活动奖励没有接口证据时不自动接入。不会将未返回奖励称作已领取，也不猜测数量或价值。积分商城和月度兑换不在本轮范围。
