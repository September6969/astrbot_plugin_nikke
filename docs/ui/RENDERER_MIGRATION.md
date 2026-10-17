# T2I 渲染器迁移说明

更新时间：2026-10-17
统一分支：`feat/ui-redesign-luna`

## 当前规则

- 所有卡片和结构化页面渲染统一走 AstrBot 注入的异步 `html_render` 与 T2I 模板；作为素材分发的静态图片不属于卡片 renderer。
- 图片渲染失败、超时、返回空路径或渲染不可用时，由命令层用已经取得的同一份 DTO 生成中文文本；回退不重复查询或刷新业务数据。
- 外层任务取消继续向上传播。单次原生渲染的超时目标为 30 秒。
- `ui_renderer` 已不再是可选路由。缺失、`t2i`、历史 `pillow` 和其他旧值均归一到 T2I；旧非默认值只产生一次不包含配置值的弃用提示。
- 生产 Pillow 卡片 renderer、其 provider/container 注入和旧导出已退役。Pillow 仍用于图片素材解码、裁切/缩放、立绘与头像处理、资源缓存校验和 T2I 输入准备。

## 页面与失败回退

| 用户入口 | 图片页 | 失败文本来源 | 保持的语义 |
|---|---|---|---|
| `/妮姬 查询 资料 <name>` | `character_info` | 同一公开 `CharacterInfoData` | 只用已确认的公开目录字段与头像，不请求私有账号详情。 |
| `/妮姬 查询` | `roster` | 同一 `CharacterRosterData` | Top 20、稳定排序、身份映射及未知字段语义不变。 |
| `/妮姬 查询 练度 <name>` | `character` | 同一 `CharacterCardData` | 资产准备复用当前 DTO，不为文本回退再次解析或查询。 |
| `/妮姬 个人资料` | `profile` | 同一 `ProfileDashboardData` | 保留缺失、未知、真实零值和部分数据提示。 |
| `/妮姬 战役 <stage>` | `campaign` | 同一 `StageClearRecord` | 保留五个队员槽位、状态、顺序和已有格式化内容。 |
| `/妮姬 突袭` | `union_overview` | 同一 `UnionRaidOverviewData` | Boss/历史摘要的显式未知状态和现有查询范围不变。 |
| `/妮姬 突袭 排名 [page]` | `union_records` | 同一 `RaidRankingData` | 排名、并列、页码、范围分母和精确数值不变。 |
| `/妮姬 突袭 我的 [page]` | `union_member` | 同一 `RaidRankingData` | 每页记录、五个队员槽及未知状态不变。 |
| `/妮姬 日程 ...` | `calendar_schedule` | 同一快照的当前页 | 页码、完整标题、分页 ID 和订阅语义不变。 |
| 管理员手动/定时日常摘要 | `daily_summary` | 同一批 `DailyTaskResult` | 使用结构化状态码；`UNKNOWN_AFTER_ACTION` 仍为“待确认”，不推断任务已领取。 |

## 实现位置

- `adapters/astrbot/command_presentation.py` 将页面交给 `T2IRenderer`，失败时只返回不可用信号，由对应命令用现有 DTO 格式化文本。
- `ui/renderers/t2i.py` 调用注入的 `html_render`，并以 30 秒边界等待结果；取消异常不转换成普通失败。
- `core/config.py` 统一归一旧 `ui_renderer` 值；`_conf_schema.json` 与 README 不再承诺 Pillow 卡片路由。
- `scripts/architecture_metrics.py` 与 `tests/test_p4_renderer_migration.py` 防止生产 Pillow 卡片类、旧导入或容器注入被重新引入。

## 验收边界

P4 的本地回归与 Chromium 预览不能替代 CI、AstrBot 原生 `html_render` 或真实 QQ 消息验收。上述宿主边界必须按实际执行结果单独记录。绑定网页与扩展只用合成 token、假 Cookie 和假服务响应进行可访问性/状态测试，不代表真实绑定或账号写入。
