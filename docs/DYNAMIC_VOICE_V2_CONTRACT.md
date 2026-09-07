# Dynamic Voice V2 Increment A 合同

## 范围

本增量只处理动态语音准备层的两个确定性问题：

1. 下载内容与 manifest 必须分别原子落盘，首轮下载成功后可被同进程和重启后的 provider 复用。
2. 未登记的角色 ID 不得静默借用 Alice 的台词；只能使用中性文本降级。

本增量不添加未经核验的角色、皮肤、互动台词或远程资源 URL，也不把剧情 `speaker` 映射推断成 Poke 互动映射。

## 字段合同

| 字段 | 约束 | 语义 |
| --- | --- | --- |
| `map_key` | `[a-z0-9_]{1,100}` | 公开 voice map 的逻辑键 |
| `speech_id` | `[a-z0-9_]{1,100}` | 仅可使用 voice map 明确列出的 ID |
| `locale` | `en` / `ja` / `ko` | 远程资源语言；不把 `zh-cn` 当作已存在的 MP3 源 |
| `budget` | 有限正数；拒绝布尔、字符串、NaN、无穷和非正数 | 当前请求等待预算；异常值在创建下载任务前受控拒绝 |
| manifest `sha256` | 内容 SHA-256 | 内容完整性校验 |
| manifest `source_path` | 由已确认 locale 与 speech ID 组成 | 记录来源路径，不代表取得再分发授权 |

## 缓存与并发

- 同一 `(map_key, speech_id, locale)` 在 provider 内共享一个下载任务，避免 N+1 请求。
- 同时最多 20 个 pending key，网络下载最多 2 个并发槽，单个 MP3 不超过 12 MiB。
- MP3 内容与 JSON manifest 使用不同临时文件分别原子替换；任一阶段失败时不留下临时文件。
- 只有目标文件、manifest、时间窗口、SHA-256 与 MP3 头部同时有效时才命中持久缓存。

## 未知角色语义

`VoiceResolver.resolve_character_key()` 只返回 `CHARACTER_LINES` 中已登记的角色。未知 ID 的 `resolve_poke_line()` 使用中性提示，不得出现 Alice 或其他角色的专属台词。默认不带角色参数仍保持 Alice 的历史默认行为。

## 证据边界

本增量的行为证据来自 mock transport、合成 MP3 头和本地单元测试。它不证明官网资源可再分发、不证明 OneBot/NapCat 真实播放、不证明真实账号联调，也不触发消息发送。
