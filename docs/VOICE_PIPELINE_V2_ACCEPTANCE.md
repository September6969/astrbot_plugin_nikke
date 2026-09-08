# Voice Pipeline V2 验收

## 离线状态

`READY_OFFLINE`：`/妮姬 戳一戳` 已按本地音频 → 有来源证据的官方动态资源 → 文本顺序接线。动态 pipeline 使用 single-flight、4 秒常规预算和不超过 5 秒的最大预算；超时的共享准备任务只继续填充缓存，不向迟到响应发送音频。

`NEEDS_LIVE_EVIDENCE`：当前 `assets/voice_poke_map.json` 保持空表。真实角色/服装到 `voice_map`/`speech_id` 的对应关系、远端资源授权、OneBot/NapCat Record 播放和 QQ 送达尚未核验。

## 合同

- `VoiceMapRegistry` 只接受完整的 `character + costume + locale` 精确键；不存在通配符、相邻 ID 推导、Alice 借用或默认服装回退。
- 每条映射必须有 HTTPS `source`、`source_ref` 和 `checked_at`；资源 provider 仍会在线核对 `voice_map` 是否包含 `speech_id`。
- `VoiceResourceProvider` 不携带 Cookie、token 或私有 header，使用官方资源路径、受限 HTTP、24 小时 SHA-256 manifest、路径/符号链接防护和并发上限。
- `VoiceEncoder` 通过 ffprobe 校验源时长，使用 ffmpeg 输出 24kHz、单声道、16-bit PCM WAV；工具缺失时跳过动态路径并使用文本回退。
- `VoicePipeline.close()` 取消在途任务并关闭 provider/encoder；插件 terminate 会在素材管理器之前回收语音资源。

## 验证

- `tests/test_voice_mapping.py` 覆盖空清单、精确身份、未知角色/服装/locale、重复条目和来源字段。
- `tests/test_voice_audio.py` 覆盖本地 miss 后的动态 pipeline 接线；既有 Voice provider、encoder、pipeline 和 OneBot Record 合同测试继续运行。
- 合成 Record 序列化只证明 AstrBot 能把本地 WAV 转换为 OneBot payload，不证明 NapCat 真实播放或 QQ 送达。

## 最小现场动作

恢复 `ssh serv` 后，仅在已存在的授权测试环境使用一条已经核验的 voice map/音频映射，记录脱敏的请求路径、响应状态、输出格式和 Record 结果；不读取或写入账号状态，不采集 Cookie/token，不发送未经明确确认的消息。没有可用的精确映射或 SSH 不可用时，保持 `NEEDS_LIVE_EVIDENCE`。
