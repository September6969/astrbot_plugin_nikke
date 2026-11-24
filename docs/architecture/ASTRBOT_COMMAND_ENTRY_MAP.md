# AstrBot 命令入口对照

宿主装配与框架注册保留在 `main.py`；尾参解析在 `adapters/astrbot/command_parser.py`，命令分派在 `adapters/astrbot/command_runtime.py`（`NikkeCommandRuntime`）。本表对照 REFACTOR V2 `PR-6C` 之后的真实装饰器与路由代码（`PR-2` 统一解析与 `#妮姬` 插件级入口、`PR-3B` 日常任务确认恢复、`PR-6C` 删除未注册遗留方法），防止收缩插件外壳时静默删除入口。

## 宿主注册入口

`NikkePlugin` 只有 3 个 AstrBot 注册入口（`tests/test_main_refactor_integrity.py` 锁定列表 `["nikke", "nikke_hash_prefix", "on_nikke_poke"]`）：

| 注册入口 | 装饰器 / 宿主事件 | 处理流程 |
| --- | --- | --- |
| `NikkePlugin.nikke` | `@filter.command("妮姬", alias={"nikke", "#妮姬", "#nikke"})` | 直接位置传参时把 `arg3` 并入 `arg2`，再薄委托到 `NikkeCommandRuntime.nikke` |
| `NikkePlugin.nikke_hash_prefix` | `@filter.regex(HASH_PREFIX_PATTERN)`，模式 `^\s*#(?:妮姬\|nikke)(?:\s\|$)`（忽略大小写） | 处理宿主未唤醒的 `#妮姬` / `#nikke` 消息；`event.is_at_or_wake_command` 为真时跳过，交给 `nikke` 处理以免重复回复。不修改宿主全局 `wake_prefix` |
| `NikkePlugin.on_nikke_poke` | `@filter.event_message_type(EventMessageType.ALL)` | 薄委托到 `AstrBotVoiceAdapter.on_poke`（`self.adapters.voice.on_poke`），由其判断并处理戳一戳事件；同时传入运行时 `closing` 标志 |

其余成员只有装配与生命周期：`__init__`、`_apply_directory`（目录加载回调）、`command_runtime` 延迟属性、`terminate`（AstrBot 按类 `__dict__` 调用）与 `close`。`scripts/audit/architecture_metrics.py` 的 `main_public_member_allowlist` 门禁只允许公开成员 `command_runtime`、`nikke`、`nikke_hash_prefix`、`on_nikke_poke`。

## 解析规则

- 前缀后必须跟空白或消息结束；`#妮姬` / `#nikke` 由 `normalize_nikke_prefix` 规范化为 `/妮姬` / `/nikke`。
- 宿主按空白切分且只绑定固定个数参数；`NikkeCommandRuntime.nikke` 优先用 `parse_nikke_message(event.message_str)` 还原第二个参数之后的多词、换行与空格尾参（根命令须与宿主传入值一致）。
- 根命令按 `casefold` 匹配；未识别子命令进入 `_legacy`，仍无匹配时提示“未知指令。发送 /妮姬 帮助 查看可用功能。”。

## 运行时分支（`NikkeCommandRuntime.nikke`）

| 根命令 | 别名 / 子命令 | 最终委托 |
| --- | --- | --- |
| `竞技场` | `arena`；`解队`、`沙盒`、`我的`、`数据状态`；网页启用时私聊 `编辑`、`三队`、`结果` | `ArenaCommandHandler`（`action` / `value`）；`enable_arena` 关闭时 handler 未装配，返回“竞技场功能当前未启用。” |
| `塔层` | `tower` | `TowerCommandHandler`，参数 `tower` / `floor` |
| `语音` | `voice`；`开`、`关`、`语言`、`角色`、`服装` | `AstrBotVoiceAdapter.voice_settings` |
| `塔罗` | `tarot`；`单抽`、`三张`、`今日`、`状态`、`帮助` | `TarotCommandHandler`，参数 `action` / `value` |
| 空、`帮助` | `help`；`帮助 <分类>`；`帮助 详解\|detail [主题]` | `help_home` / `help_category` / `help_detail`（`application/commands/help.py` → `features/help` 单一数据源）；管理员可见管理区；分类与详解共同遵循竞技场、网页及额外写操作能力门禁 |
| `账号` | `account`；`绑定`、`解绑`、`汇总 开\|关`、`续期`、`自动续期` | `AccountCommandHandler` 的 `account` operation |
| `我的` | `me`、`progress` | `ProfileCommandHandler` |
| `查询` | `query` | `NikkeCommandRuntime.query` 二级分派（见下） |
| `签到` | — | `DailyCommandHandler`，`scope="signin"`（仅签到） |
| `日常` | `daily`、`claim`、`routine`；`自动 开\|关`；`任务 状态\|执行\|自动 开\|关\|确认恢复 [确认]` | `DailyCommandHandler`，`scope="community"`（社区签到及免费领奖）；`任务` 子命令转社区自动化 handler，`确认恢复` 只解除人工核实后的下一周期阻断，不重放 |
| `兑换` | `cdk`；普通码 | `CdkCommandHandler` 的 `single` operation |
| `兑换 批量` | `batch` | `batch` operation；缺少码时由入口给出用法提示 |
| `兑换 可用` / `兑换 历史` | `available` / `history` | 只读 `available` / `history` operation |
| `战役` | `campaign`、`关卡`、`stage` | `CampaignCommandHandler`，参数 `stage` / `mode` |
| `日程` | `schedule`；`[7\|14\|30] [页码]`、`刷新`、`订阅 [类型]`、`订阅状态`、`取消订阅` | `CalendarCommandHandler`（`horizon` / `page`）；仅当根命令为 `schedule`、参数含 `:` 且发送者为管理员时转 `AccountCommandHandler` 的 `schedule` operation |
| `公告` | `news`、`announcement`；无参数 | `AnnouncementCommandHandler` 的 `view` operation |
| `公告 语言\|分类\|搜索 <值>` | `language`/`locale`、`category`、`search` | `view` operation，分别带 `locale` / `category` / `query` 过滤（一次一个） |
| `公告 诊断` | `diagnostic`、`diagnostics` | `diagnostic` operation |
| `公告 深度刷新 [语言]` | `rescan`、`deep_rescan` | `deep_rescan` operation，默认 `en`；仅管理员 |
| `公告 订阅` / `公告 取消订阅` | — | `subscribe` / `unsubscribe` operation，目标为当前 `unified_msg_origin` |
| `公告 <其他参数>` | — | `unsupported` operation，不执行未知操作 |
| `攻略` | `guide`、`guides` | `GuideCommandHandler`，默认页为 `1` |
| `突袭` | `联盟突袭`、`raid`、`union_raid`；无参数 / `排名\|ranking [页码]` / `我的\|my [页码]` | `RaidCommandHandler` 的 `overview` / `ranking` / `member` operation，其他参数为 `invalid` |
| `管理` | `admin`；`健康`、`设群`、`任务时间`、`汇总时间`、`执行` | `AccountCommandHandler` 的 `admin` operation；授权检查在 handler/application |

`查询` 的二级映射：`练度` / `roster` / `character` → 无角色名时 roster、有角色名时角色卡；`资料` / `info` → 公开角色资料；`战役` / `关卡` / `campaign` / `stage` → campaign；`攻略` / `guide` → guide；`突袭` / `联盟突袭` / `raid` / `union_raid` → raid overview。空缺参数返回用法提示。

## 旧版英文平铺兼容入口（`NikkeCommandRuntime._legacy`）

这些名称没有独立 AstrBot 装饰器，只作为 `/妮姬 <name>` / `/nikke <name>` / `#妮姬 <name>` 子命令调用：

| 旧入口 | 委托目标 | 行为 |
| --- | --- | --- |
| `bind`、`unbind`、`status` | `AccountCommandHandler` 对应 operation | 绑定 / 解绑 / 状态 |
| `roster`、`character <name>`、`info <name>` | `CharacterCommandHandler` | 练度图片、指定角色卡、公开资料 |
| `push <on/off>` | `AccountCommandHandler.push`（`state`） | 本人每日汇总偏好，等同 `/妮姬 账号 汇总 开\|关` |
| `group [set]` | `AccountCommandHandler.group_set`（`action`，空值与 `set` 等价） | 当前会话设为目标 |
| `summary <HH:MM>` | `AccountCommandHandler.summary` | 汇总时间设置 |
| `run`、`health` | `AccountCommandHandler` 对应 operation | 立即运行 / 只读健康检查 |

`campaign`、`raid`、`union_raid`、`news`、`announcement`、`guide`、`schedule`、`tarot`、`voice`、`daily`、`claim`、`routine`、`cdk`、`me`、`progress` 等英文名是上表主分支的别名，不经 `_legacy`。

## PR-6C 删除记录与四重核查

`PR-6C` 删除了 `NikkePlugin` 上 35 个未注册公开方法（`tarot_command`、`nikke_help`、`me`、`query`、`progress`、`daily`、`claim`、`cdk`、`cdk_batch`、`cdk_available`、`cdk_history`、`campaign`、`event_schedule`、`announcements_view`、`announcement_deep_rescan`、`announcement_subscription`、`guide`、`account`、`bind`、`unbind`、`status`、`push`、`admin`、`group_set`、`schedule`、`summary`、`run`、`health`、`voice_settings`、`roster`、`character`、`info`、`union_raid`、`union_raid_ranking`、`union_raid_my`）、私有 `_dispatch_account_command`，以及 `NikkePlugin._help_text` / `NikkeCommandRuntime._help_text` 两个包装：

- **静态引用**：生产代码无调用者；`NikkeCommandRuntime` 不回引插件，3 个注册入口只调用 `command_runtime.nikke` 与 `adapters.voice.on_poke`。测试调用已迁至 `/妮姬` 统一路由或 `application.commands.help`。
- **动态调用**：生产无 `getattr`/字符串路由到这些名称；`NikkePlugin` 与 `NikkeCommandRuntime` 均无 `__getattr__`；AstrBot 只绑定注册 handler，并仅按名查找 `initialize`、`__del__`、`terminate`，与删除名称不重叠。
- **外部运维脚本**：`scripts/`、`.github/workflows/ci.yml`、`deploy/`、`extension/` 无引用；配置与模板不含 handler 名。
- **回退用途**：无错误路径或迁移回退指向这些方法；历史平铺别名由上方运行时分支与 `_legacy` 承担。

每个被删方法覆盖的 QQ 命令由 `tests/test_command_routing_contract.py::test_removed_plugin_methods_keep_qq_command_routes` 逐项锁定。今后新增或删除入口须先补消费者证据，并同步更新本表、`MAIN_PUBLIC_MEMBER_ALLOWLIST` 与相关合同测试。

## 合同测试对照

- 注册入口、外壳成员白名单与本对照表关键字：`tests/test_main_refactor_integrity.py`、`tests/test_full_refactor_architecture.py`。
- 中文、英文、`#妮姬` 前缀与历史平铺别名路由：`tests/test_command_routing_contract.py`、`tests/test_command_parser_and_help.py`（含 regex 装饰器）、`tests/test_astrbot_command_adapter.py`。
- 帮助与详解：`tests/test_help_detail.py`、`tests/test_core.py::HelpTests`。
- 账号与管理（含 `group_set`、`schedule`、`health`）：`tests/test_account_command_contract.py`、`tests/test_runtime_health.py`。
- 公告（announcement）与订阅：`tests/test_announcement_command_contract.py`、`tests/test_announcement_v2.py`、`tests/test_announcement_push_wiring.py`。
- 日程、CDK、日常与确认恢复：`tests/test_calendar_command_contract.py`、`tests/test_cdk_command_contract.py`、`tests/test_cdk*.py`、`tests/test_daily_auto.py`、`tests/test_daily_recovery.py`、`tests/test_community_automation_commands.py`。
- 竞技场：`tests/test_arena_commands.py`。
- 塔罗与语音（含 `on_nikke_poke` 全消息事件）：`tests/test_tarot_service.py`、`tests/test_voice_application.py`、`tests/test_voice_character_and_costume.py`、`tests/test_voice_audio.py`。
