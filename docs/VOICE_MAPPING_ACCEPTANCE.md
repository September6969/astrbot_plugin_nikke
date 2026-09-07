# Voice 映射研究验收

基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 已完成

- [x] 只读核验公开 `voice_map`、`scene_list`、scene detail 的当前结构。
- [x] 增加 scene-group 范围隔离，避免把同一 map 文件的其它场景误计入当前覆盖。
- [x] 增加 story 映射审计结果，保留 matched/map-only/detail-only/duplicate 语义。
- [x] 明确 interaction type 和 skin 没有公开字段证据，状态固定为 `NOT_OBSERVED`。
- [x] 使用合成 fixture 补齐完整覆盖、部分覆盖和重复 ID 行为测试。

## 当前现场结论

`d_main_01_01_e`：map 文件总计 507 个 ID；按 scene-group 前缀隔离后 10 个；detail 12 条；匹配 10 条；detail-only 为 `d_main_01_01_e_4`、`d_main_01_01_e_7`；speaker 观测到 `marian` 和 `Self`。

## 未完成

- [ ] 完整角色→皮肤→interaction→voice_id 对应。
- [ ] Poke 事件接线、用户偏好和真实发送/播放。
- [ ] 音频再分发授权与生产资源许可。
- [ ] 真实账号访问或消息操作。

本主题的 JSON 读取是公开、匿名、只读研究，不是产品完成、真实联调或资源授权。

