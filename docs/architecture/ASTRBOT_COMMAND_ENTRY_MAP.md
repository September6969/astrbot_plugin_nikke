# AstrBot 命令入口对照

R20 将宿主装配与框架注册保留在 `main.py`，命令解析/分发迁入 `adapters/astrbot/command_runtime.py`。此表对照当前真实装饰器与路由代码，防止收缩插件外壳时静默删除旧入口。

## 宿主注册入口

| 注册入口 | 宿主事件 | 处理流程 |
| --- | --- | --- |
| `/妮姬`；别名 `nikke`、`#妮姬`、`#nikke` | AstrBot 命令事件；统一由 `NikkePlugin.nikke` 接收 | 薄委托到 `NikkeCommandRuntime.nikke`，解析中文/英文命令、参数和兼容分支 |
| `NikkePlugin.on_nikke_poke` | `EventMessageType.ALL` | 薄委托到 `NikkeCommandRuntime.on_nikke_poke`，再由唯一 `AstrBotVoiceAdapter.on_poke` 判断并处理戳一戳事件 |

所有命令子项均经统一根命令注册；下表列出每个分支与最终 handler/application 归属。`#妮姬` / `#nikke` 前缀先规范化为 `/妮姬` / `/nikke`。

## 中文与现代英文子命令

| 根命令 | 别名/参数分支 | 最终委托 |
| --- | --- | --- |
| 空、`帮助` | `help` | `nikke_help`：生成分类帮助；管理员可见管理区 |
| `账号` | `account` | `AccountCommandHandler` 的 `account` operation |
| `我的` | `me`、`progress` | `ProfileCommandHandler`，平台层保留延迟反馈、Cookie 失效标记与图片结果适配 |
| `查询` | `query` | `query` 再分派至练度/角色、公开资料、战役、攻略或联盟突袭 |
| `塔层` | `tower` | `TowerCommandHandler`，参数 `tower` / `floor` |
| `塔罗` | `tarot` | `TarotCommandHandler`，参数 `action` / `value` |
| `语音` | `voice` | `AstrBotVoiceAdapter.voice_settings` |
| `签到` | `daily`、`claim`、`日常`、`routine` | `DailyCommandHandler`，参数 `action` / `value` |
| `兑换` | `cdk`；普通码 | `CdkCommandHandler` 的 `single` operation |
| `兑换 批量` | `batch` | `CdkCommandHandler` 的 `batch` operation；缺少码时由入口给出用法提示 |
| `兑换 可用` | `available` | `CdkCommandHandler` 的只读 `available` operation |
| `兑换 历史` | `history` | `CdkCommandHandler` 的只读 `history` operation |
| `战役` | `campaign`、`关卡`、`stage` | 按当前事件构造 `CampaignCommandHandler`，再经 `AstrBotCommandAdapter` 分派 |
| `日程` | `schedule`；`schedule HH:MM` 且发送者为管理员 | `CalendarCommandHandler`；管理员设置时间时转 `AccountCommandHandler.schedule` |
| `公告` | `news`、`announcement`；无参数 | `AnnouncementCommandHandler` 的 `view` operation |
| `公告 订阅` | `取消订阅` | `AnnouncementCommandHandler` 的 `subscribe` / `unsubscribe` operation，目标为当前 `unified_msg_origin` |
| `公告 <其他参数>` | 包括当前未支持的参数组合 | `AnnouncementCommandHandler` 的 `unsupported` operation，不执行未知操作 |
| `攻略` | `guide`、`guides` | `GuideCommandHandler`，默认页为 `1` |
| `突袭` | `联盟突袭`、`raid`、`union_raid`；无参数 | 联盟突袭 overview；延迟反馈、渲染和错误提示在平台命令 runtime |
| `突袭 排名` | `联盟突袭 ranking` | 当前响应范围排名；不宣称完整赛季 |
| `突袭 我的` | `联盟突袭 my` | 稳定 openid 精确匹配当前账号记录 |
| `管理` | `admin` | `AccountCommandHandler` 的 `admin` operation；授权检查在 handler/application |
| 未识别子命令 | 任意其他值 | 保持“未知指令”提示并指向帮助入口 |

`查询` 的二级映射：`练度` / `roster` / `character` → 无角色名时 roster、有角色名时角色卡；`资料` / `info` → 公开角色资料；`战役` / `关卡` / `campaign` / `stage` → campaign；`攻略` / `guide` → guide；`突袭` / `联盟突袭` / `raid` / `union_raid` → raid overview。空缺参数仍返回既有用法提示。

## 旧版英文平铺兼容入口

这些名称没有独立 AstrBot 装饰器，仍可作为 `/妮姬 <name>` / `/nikke <name>` 子命令调用：

| 旧入口 | 委托目标 | 既有行为 |
| --- | --- | --- |
| `bind`、`unbind`、`status` | `AccountCommandHandler` 对应 operation | 绑定/解绑/状态 |
| `roster`、`character <name>`、`info <name>` | 角色/账号查询 runtime | 练度图片、指定角色卡、公开资料 |
| `campaign <stage> [mode]` | `CampaignCommandHandler` | 当前会话反馈和展示回退 |
| `raid`、`union_raid` | raid overview | 同中文联盟突袭入口 |
| `news` | `AnnouncementCommandHandler.view` | 公告浏览 |
| `guide [category]` | `GuideCommandHandler` | 攻略，默认第 1 页 |
| `push <on/off>` | `AccountCommandHandler.push` | 每日群汇总开关 |
| `group [set]` | `AccountCommandHandler.group_set` | 当前会话设为目标 |
| `schedule <HH:MM>`、`summary <HH:MM>` | `AccountCommandHandler` 对应 operation | 定时设置 |
| `run`、`health` | `AccountCommandHandler` 对应 operation | 立即运行/只读健康检查 |
| `tarot [action] [value]` | `TarotCommandHandler` | 同中文塔罗入口 |

## 合同测试对照

- 根命令别名、实际 AstrBot command filter 注册及 handler 异步结果：`tests/test_astrbot_command_adapter.py`。
- 中文根路由、旧版平铺别名与各 handler 分支：`tests/test_core.py`、`tests/test_announcement_v2.py`、`tests/test_daily_auto.py`、`tests/test_guide_pagination.py`。
- 账号授权/账户操作/旧入口适配：`tests/test_account_command_contract.py`。
- Voice 全消息事件注册与 poke 路由：`tests/test_voice_character_and_costume.py`、`tests/test_voice_audio.py`。
- Calendar、CDK、Profile、Campaign 等领域合同：分别见对应的 `tests/test_calendar_*.py`、`tests/test_cdk*.py`、`tests/test_profile*.py`、`tests/test_campaign*.py`。

未在本次改变现有命令别名、权限、参数解释或领域写入合同；未来删入口须先补充消费者证据并更新此对照表。
