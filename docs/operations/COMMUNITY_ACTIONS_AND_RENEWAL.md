# 社区浏览、点赞与实验性会话续期

核实日期：2026-10-22。基线为远端主分支 `e99b22f`。本轮只请求官方公开静态脚本、匿名任务目录和匿名帖子列表；没有读取真实绑定账号、浏览帖子详情、点赞、续期、签到、领奖或发送消息。所有写路径使用模拟网关或 HTTP MockTransport 验证。

## 范围与授权

新增浏览、点赞及实验性续期；不包含积分消费、月度兑换、自动关注、评论、发帖或游戏内操作。原 `/妮姬 签到`、`/妮姬 日常`、原自动偏好保持签到及原免费领奖语义。

新命令均私聊使用，处理账号所有者本人当前绑定：

| 命令 | 行为 |
| --- | --- |
| `/妮姬 日常 任务 状态` | 只读任务进度、完成状态、奖励未知状态及最近结果 |
| `/妮姬 日常 任务 执行` | 手动执行当前尚缺浏览及点赞；不会附带签到或领奖 |
| `/妮姬 日常 任务 自动 开/关` | 新授权，只控制浏览及点赞，默认关 |
| `/妮姬 账号 续期` | 手动尝试一次实验性续期 |
| `/妮姬 账号 续期 状态` | 只读查看续期最近结果及独立开关 |
| `/妮姬 账号 自动续期 开/关` | 独立实验性授权，默认关 |

`enable_daily_actions=false` 阻断所有新写路径，包括手动和后台；新授权可以预先保存，但不会绕过总开关。偏好绑定已核实的稳定社区身份和绑定代次，重新绑定后须重新授权；正常续期不改变绑定代次。通知路由仅由本人私聊事件登记，绑定代次变化后失效。成功静默，异常每账号、UTC周期及能力最多通知一次；通知自身未知也不重发。无路由保存状态，不猜 QQ 路由，不发送到群。

## 官方证据

证据使用当前官方脚本及匿名响应，参考项目只作调查线索，未复制代码或成功判断。

| 来源 | 核实内容 |
| --- | --- |
| [官方首页](https://www.blablalink.com/) | 当前入口 `index-aR_eg_5w.js` |
| [官方入口脚本](https://www.blablalink.com/assets/nikke/version/default/assets/index-aR_eg_5w.js) | `useApiLogin`、正常 SDK 登录入参、`useApiCheckLogin`、`GetUserInfoNew`、任务列表与 UGC 请求封装；SHA256 `e99a1279c4009340721e71f52d7b732052575d816361fb29bc366061961885db` |
| [官方接口常量](https://www.blablalink.com/assets/nikke/version/default/assets/v4-DaeRWrZK.js) | 任务、Login、CheckLogin、GetGameLoginInfo、UGC 分区、列表、详情和点赞的路径 |
| [官方任务目录](https://api.blablalink.com/api/lip/direct/lipass/Points/GetTaskListV2?get_top=false&intl_game_id=3) | 匿名 GET 返回浏览 `task_type=13/task_id=72`、点赞 `task_type=14/task_id=73`；`cyclical_type=1`、`periodicity_type=1`；目标 `reward_infos.need_completed_times`，当前目录目标各5；匿名进度不是账号进度 |
| [任务进度及刷新组件](https://www.blablalink.com/assets/nikke/version/default/assets/refresh-tag-CgrTy1wd.js) | `completed_times / need_completed_times`、`is_completed`；`utc().startOf(day).local()` 对应 UTC00:00（北京时间08:00）；SHA256 `318b459786dbf0883d73cae99c37786dbac08faf19b246f91db043bbc71502a0` |
| [当前详情逻辑](https://www.blablalink.com/assets/nikke/version/default/assets/use-pc-nav-post-plate-highlight-BZKZUjPV.js) | `GetPost` 的 `browse_post`：`browseCounts=true` 对应正常详情1，`browseCounts=false` 对应不计浏览的交互刷新2；`PostStar` 切换 `my_upvote.is_star`，相同类型再次点击会取消 |
| [当前列表逻辑](https://www.blablalink.com/assets/nikke/version/default/assets/tabevent-C0_Gxqfx.js) | 推荐分区按运行时 ID 选择；`GetPostListNew` 的参数与 `post_uuid` 身份 |
| [点赞类型](https://www.blablalink.com/assets/nikke/version/default/assets/stance-CPVmnCHD.js) | 普通点赞 `type=1, like_type=1`，不调用其他表情、评论或关注 |
| [参考项目](https://github.com/1204244136/BlablalinkTasker/tree/a2bc84566b19722eb6b6b9af6da88edd1fb27d23) | 仅用于定位任务与 Login 线索；其默认字段、29天期限及成功判断没有沿用 |

完整匿名目录及脚本摘要保存在仓库外证据目录，仓库只保留任务字段提取样本与来源清单，不保存完整官方脚本或账号数据。

账号进度使用已存在 GET `/api/lip/proxy/lipass/Points/GetTaskListWithStatusV2`，参数 `get_top=false`、实际账号上下文中的 `intl_game_id`。固定支持核实过的类型和 ID 组合；任务换 ID、周期字段变化、多奖励阶段或进度字段类型不明确时对应任务不可用，不按名称、顺序或默认5次猜测。

候选来源是 POST `/api/ugc/direct/standalonesite/Dynamics/GetPlateList` 与 `GetPostListNew`；首批最多10篇，不无限翻页。按实际 `recommend` 分区 ID 查询，以稳定 `post_uuid` 去重。匿名列表已确认该 ID 字段是字符串；登录后的 `my_upvote.is_star` 必须明确为布尔 false 才可点赞，缺失、true、数值或字符串状态都跳过。候选不足不放宽条件。

浏览 POST 同 direct 路径 `GetPost`，参数 `{post_uuid,browse_post:1,original_content:0}`，**它是有记账副作用的写操作**。查询点赞状态使用官方交互刷新参数 `browse_post:2`。点赞 POST `/api/ugc/proxy/standalonesite/Dynamics/PostStar`，参数 `{post_uuid,type:1,like_type:1}`，提交前两次明确检查未点赞，避免排队期间状态变化。官方没有条件点赞的原子比较接口证据，用户同时在官网操作仍可能发生竞态；检测到进度变化即停止，不作成功归因。

奖励任务 UI 对这两类任务没有独立领取分支，显示进度和积分值。尚未用真实账号证明积分自动到账时序，也未核实独立领取合同；实现不增加任何领取请求，展示「任务完成」与「奖励未核实到账」两项不同状态。不得将任务完成直接记作奖励已领取。

## 动作状态、预算和恢复

流程：只读核对稳定身份 → 读取任务状态 → 计算缺额 → 有限候选 → 串行等待 → 再次检查授权、周期、目标和未点赞 → 原子保存提交意图 → 单次请求 → 最多三次只读进度核验 → 汇总。两次复核之间2秒，不重试写请求。

配置 `community_run_action_budget=5`、`community_cycle_action_budget=10` 是每种动作各自的安全预算，不是官方目标。周期预算最多为来源目标；进度复核与补做共享预算，跨手动、自动、多绑定、重绑和重启累计。`community_action_interval_seconds=5`，允许2–60秒；官方没有公开固定安全限流值，因此不宣称该间隔保证不限流。任何登录、限流、验证、身份或合同异常停止；不绕过风控。

复用日常稳定游戏身份锁、现有隔离 HTTP 客户端及 `action_runs`。额外以已核实的社区 openid 摘要建立数据库执行占用，确保同一社区账号更换游戏区服也共享预算，并保护多进程在读取与提交之间的竞争。进程崩溃留下占用时仅允许查询，需先核实旧执行及所有未决动作，不能自动超时解锁。数据库事务同时检查作用域预算、已有帖子记录和未决动作，再写入 `DISPATCH_INTENT`。执行记录含稳定账号摘要、官方 UTC 周期、动作类型、帖子 ID、提交前进度和目标。请求接受记作 `DISPATCHED`，恰好增加1次进度后才记作 `VERIFIED`；没有实际浏览器页面或点击操作，不声称“页面打开/点击成功”。单纯返回200或接受请求不是进度证明。

超时、断线、取消、记录更新失败或进度未增加保留 `UNKNOWN_AFTER_ACTION`；重启后的 `DISPATCH_INTENT` 也视作未决。之后只读查询，不重发同一帖子，也不改换帖子盲目补做。聚合进度不能归因到单篇帖子；无法排除未决影响时暂停对应动作，跨周期及重绑也不清除此保护。已核实动作在新官方周期可以再次选择同一帖子，避免把去重错误地变成永久去重。

恢复步骤：关闭该自动能力 → 查看任务状态及脱敏执行记录 → 在官网核实真实进度、请求时间和影响周期 → 根据充分证据人工处理未决状态，再明确恢复授权。当前不提供强制重发、清空预算或猜测恢复命令；证据不足保持暂停。不要删除数据库或运行记录来解锁。

## 实验性续期合同与限制

官方正常 Login POST `/api/user/Login` 使用 SDK 返回的 `game_openid`、`game_channelid`、`game_token`、`game_id`、`game_expire_time`，以及可用时的 `game_uid`、用户名、地区和成人状态。`game_expire_time` 来自 SDK 的真实 `token_expire_time`，不是当前时间加29天。官网正常登录合同不等于已证明“重复 Login 能长期续期”。

扩展0.3.0默认不读取请求体。只有本人额外勾选保留续期材料，才监听**精确官方 Login URL**，过滤到上述白名单；不收集密码，不保存其他请求。绑定时一并加密保存 Cookie 属性和可选原始字段，提交后清理扩展临时数据。与 Cookie 身份不匹配的捕获材料不提交。该选项不是自动续期授权。

旧绑定只有请求 Cookie 字符串，不能恢复真实 SDK 有效期。缺材料、字段为空、数值不合法、令牌已过期、身份字段与当前 Cookie 不一致，均不提交 Login；提示重新官网登录绑定。不为 `game_id`、渠道、身份或成人状态填默认值。

续期前用 CheckLogin 和 GetUserInfoNew 核对稳定账号；Login 最多请求一次，Cookie 响应不会进入共享客户端容器。逐条解析 Set-Cookie，保留 Domain、Path、Secure、HttpOnly、SameSite、Max-Age/Expires、session和删除语义，不把会话 Cookie 转成固定未来日期。候选作用域必须覆盖登录检查及既有账号接口，否则拒绝保存；不扩大服务器返回的作用域。

候选 Cookie 再做同样的只读登录及身份检查，须与续期前和绑定身份一致。验证通过后在事务中比较绑定代次及旧密文指纹，再加密替换。并发重绑、加密失败、数据库失败或验证失败保留原凭证；保存后仅清理该稳定游戏账号相关短缓存及未决查询，不清理其他账号。缓存清理失败会区分“已保存但缓存处理失败”，不会谎称旧凭证仍保留。

请求未知不循环重试；错误区分无新Cookie、响应不完整、候选验证失败、身份变化、存储失败、限流/拒绝与结果未知。同一凭证的已有尝试不自动重试，多绑定共享每24小时一次上限。自动续期仅在真实已知的令牌及 Cookie 有效期进入48小时窗口时尝试；缺到期信息不高频试探。

**验证通过只表示本次取得的 Cookie 对同一账号有效，尚未证明绝对有效期延长。** 上游是否存在30天硬上限、重复 Login 是否延长服务器会话、真实账号是否返回完整可用 Set-Cookie，均未做真实验收。令牌已过期时仍需重新登录。服务器若更换 token 后与已捕获 SDK 原字段不再一致，下一次预检会停止，不能凭新 Cookie 自行推导新的 SDK 有效期。

## 测试与真实验收边界

离线回归覆盖任务缺额、完成、状态缺失/变更、点赞去重、候选不足、延迟记账、不记账、预算、超时、取消、并发、多绑定、重绑、重启未决、跨周期、旧偏好、新开关、私聊通知和宿主四词命令解析；续期覆盖有效候选、错误账号、缺字段、无Cookie、验证失败、硬过期、未知结果、加密/存储/CAS失败、缓存隔离、Cookie属性及默认不采集请求体。

测试结果与提交/CI状态见 [本轮交付报告](COMMUNITY_ACTIONS_DELIVERY.md)。这些测试是模拟服务验收，不是官方真实账号成功证据。真实浏览、点赞和续期验收需用户另行明确指定账号与环境，本轮没有操作；不自动合并或部署。
