# Voice 公开映射研究

状态：`RESEARCHED / PARTIAL`。本记录只覆盖公开 story 场景映射，不代表 Poke 互动语音、角色皮肤绑定、音频再分发授权或真实 QQ 播放完成。

## 现场来源

本轮以匿名、无 Cookie 的只读请求核验以下逻辑路径。CDN 地址由现有 `AssetManager.game_resource_url()` 解析，不把哈希 CDN 路径写成稳定 API 合同：

| 逻辑路径 | 现场结果 | 观测结构 |
| --- | --- | --- |
| `/scene/voice_map/d_main_01.json` | HTTP 200 | JSON 字符串数组，共 507 个 ID |
| `/scene/en/scene_list_en.json` | HTTP 200 | 数组；嵌套 `sub_category_id.scenes.value[].value.scenario_group_id` |
| `/scene/en/scene_detail_d_main_01_01_e_en.json` | HTTP 200 | `scenario_group_id.records.value` 共 12 条 |

观测到的公开 CDN 响应没有认证要求；本轮只读取 JSON，没有读取 MP3、批量下载音频、写入仓库或访问账号。

## 已确认字段合同

### `voice_map`

它提供语音资源 ID 列表，例如 `d_main_01_01_e_1`。一个 `d_main_01.json` 会覆盖多个场景组，因此审计某个场景时只使用已观察到的 `scene_group_id + "_"` 前缀进行范围隔离；不能把同一文件其它场景的 ID 算成当前场景缺失。

### `scene_list`

它提供剧情目录和 `scenario_group_id`，可用于选择 scene detail；当前数据没有在该层提供角色数值 ID、皮肤 ID 或互动类型。

### scene detail

当前样例记录的有效字段包括：

- `value.id`
- `value.speaker`
- `speaker.value`
- `value.scenario_localkey`
- `value.speech_window`

对 `d_main_01_01_e` 的现场审计结果：10 个场景前缀 ID 与 detail 匹配；detail 另有 `d_main_01_01_e_4`、`d_main_01_01_e_7` 两条没有在 map 中出现。样例 speaker 为 `marian` 与 `Self`。

## 代码语义

`audit_story_voice_mapping()` 生成 `StoryVoiceMappingAudit`：

- `scope=STORY_SCENE`；
- 显式区分 `matched_ids`、`map_only_ids`、`detail_only_ids`、重复 map ID 和重复 detail ID；
- `interaction_type_evidence=NOT_OBSERVED`；
- `skin_evidence=NOT_OBSERVED`；
- 只有 ID 集合完整一致且 map/detail 两侧均无重复时才报告 `coverage_complete=True`；重复 detail 行不会因集合去重而被误报为完整覆盖。

因此 story `speaker` 不能被提升为角色/皮肤/互动语音映射；缺失项保持可见，不用角色经验或 ID 连续性补齐。

## 授权边界和后续条件

官方社区规范要求尊重版权，禁止未经同意分享/模仿他人作品，也禁止发布未官方提供或解包得到的内容。公开可读不等于插件可以再分发音频。后续若要做 Poke，至少还需要独立的 interaction mapping 证据、适用资源授权、用户偏好和 OneBot 实际发送/播放证据；本增量不执行这些动作。
