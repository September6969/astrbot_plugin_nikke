# 第二轮合并审查修复（历史记录，2026-09-06）

> 本文记录合并前 overnight 工作分支上的审查修复，不是当前开发状态入口。PR #5 已将该分支合并到 `main`；当前远端基线、CI 和剩余能力见 [POST_MERGE_STATUS.md](POST_MERGE_STATUS.md)，下一阶段见 [POST_MERGE_PHASE2_PLAN.md](POST_MERGE_PHASE2_PLAN.md)。

起始 main：`deeef6277f09a42918d71b44f49170398a05558b`。
本轮起始 HEAD：`470f16cfd4cc0a0a25456729187c3348c3cec273`。

- 单条与批量 CDK 不再重新领取 stale running；数据库条件更新将其原子转为 unknown，要求核对官方历史。
- fresh running 不发送；success/terminal/unknown 不重放；只有 failed/expired 可原子重领。
- 两个数据库实例并发转换只有一个成功；批量中旧请求跳过，新兑换码继续。
- 单条持久化也使用固定说明，防止上游响应回显完整兑换码。
- 保留 CancelledError 回归；新测试覆盖单条并发、批量继续处理、跨实例原子性和状态矩阵。
- 当时工作分支为 `feat/overnight-backlog`；该分支随后由 PR #5 合并，不应作为本阶段开发分支。

本轮本地验证：243 passed、2 warnings、43 subtests；compileall 与 Node 3 项通过。完整 SHA/Actions URL 在本轮最终交付记录中给出；本文件提交后的 HEAD 用 `git rev-parse HEAD` 核对。
完整工作提交用 `git log --reverse --format="%H %s" origin/main..HEAD` 获取。

后续状态保持：动态剧情语音不冒充互动语音；角色/皮肤、实际播放、Raid 多轮与 Daily 状态变化仍需证据。
公开资源访问不视为再分发许可，许可研究仍可继续；最终采用具体运行时才需人工决策。
没有新增 HARD_BLOCKED。公告 baseline 容量整理保留后续阶段，避免为清理引入历史重放。

---

## 后续自治推进

CDK 修复提交 `61e16d59b433bcea62918b3030b3f052ca285043` 的 [Actions](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34047280265) 已通过 Python 3.10/3.11/3.12 和 Node。

语音增加独立的下载/编码管线，统一请求预算、共享任务和关闭回收；未接入真实发送。官方二创指引与 Spine 许可研究见 [证据记录](evidence/voice_licensing_and_pipeline.md)，没有将公开访问当作再分发授权。

语音管线提交 `9ba66d954d23669e66b093a75ec231f29fa3ee2e` 的 [Actions](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34047412675) 已全绿。

追加真实 AstrBot Record 序列化测试，合成 WAV 转 Base64 字节不变，不包含本地路径，不发送消息。
最终本地验证：248 passed、2 warnings、43 subtests；Node 3 项、compileall 和 diff-check 通过。
最终提交与 Actions 精确记录在工作区外的 `E:/DevCache/nikke-second-review-final.md`，避免追记当前文件导致 HEAD 自引用失效。

## 前轮报告（历史验收记录）

# 审核修复与动态资源阶段报告（2026-09-06）

起始 main：deeef6277f09a42918d71b44f49170398a05558b。
本轮起始工作分支 HEAD：fc8d17d790ce2a71ec4682308ccaa27b2d48fab2。
分支仍为 feat/overnight-backlog，没有修改 main、merge、force push 或创建 PR。

## DONE

- 伤害证据撤销 GCD/比例转换，改为 ordinal 标签和参与者聚合顺序；保留排序/并列、身份及结构，无实际伤害值。此格式显式 builder_compatible=false，数值 Builder 测试继续使用完全合成输入。
- Guide 删除裸目录 fallback，未登记不发送，维持占位，不添加内容。
- 单条 CDK CancelledError 保存 unknown 后重新抛出，unknown 不进入重试集合；取消回归测试确认不会再次兑换。
- Voice cooldown 按平台、用户、会话隔离，用户间不互相阻塞，过期项清理。
- 删除 CI 临时分支 push trigger；使用 workflow_dispatch 在工作分支验证。
- DEVELOPMENT_PLAN 增加权威当前状态表，旧正文明确归档，纳入新的自治执行计划。
- CDK 服务层最多 10 项，间隔最少 1 秒，调用者传 0 也不能绕过。
- 公告成功历史压缩为版本水位，过期 retry state 清理，不因删除记录而重放已送公告。

## 动态语音：PARTIAL，已解除源读取阻塞

公开证据：

- 主 bundle：<https://www.blablalink.com/assets/nikke/version/default/assets/index-CLXejj5I.js>
- 播放器：<https://www.blablalink.com/assets/nikke/version/default/assets/voice-BZiQtVF1.js>
- 语言选择：<https://www.blablalink.com/assets/nikke/version/default/assets/cv-CgAWFBO0.js>
- 枚举：<https://www.blablalink.com/assets/nikke/version/default/assets/shiftyspad-Bq3J23cd.js>

实际播放器调用 GET_VOICE_URL，format=mp3；cv_lang 枚举为 en/ja/ko。
匿名读取 /scene/en/scene_list_en.json 与 /scene/voice_map/d_main_01.json 返回 200，后者明确列出 d_main_01_01_e_1。
VoiceResourceProvider 只允许 map 内的 speech_id，固定官方 CDN、无认证头、无重定向、大小限制、并发 2、最多 20 个待处理键、共享下载、失败冷却与 24 小时源缓存校验。

VoiceEncoder 使用 ffprobe 校验有限且不超过 30 秒的时长，输出 PCM 16-bit、单声道、24kHz WAV。
encoded key 包含源内容 hash、工具版本、适配器与编码参数。它不声称所有 OneBot 实现均能实际播放该格式，也没有猜测 Silk。

真实匿名 smoke：源 MP3 30587 bytes，输出 WAV 179752 bytes、3.7424167 秒、24kHz、单声道。
复用已有原生 FFmpeg/ffprobe，未安装新工具；媒体仅在工作区外缓存，未提交 Git，也没有发送 QQ 消息。

公开场景详情 /scene/en/scene_detail_d_main_01_01_e_en.json 返回 200，
scenario_group_id.records.value 中 value.id 与 voice_map 的语音 ID 一致，value.speaker 与 speaker.value 共同确认 Marian。
新增 SceneVoice 解析器交叉核对上述字段，voice_type=story，skin=None；不把故事台词冒充专用互动语音。
尚未完成完整角色→皮肤→voice_id 对应，没有把剧情语音随意绑到 Poke。
源与编码模块尚未接入 Poke 动态路径；当前 Poke 仍使用既有本地 registry。
动态完整链路首次 3–5 秒总预算与编码后台任务生命周期仍需继续接线。

## 仍待推进

- PARTIAL：Raid 完整身份/范围、Spine 实际运行时与 benchmark、动态 Voice 接线、完整静态 registry、公告深度重扫。
- NEEDS_LIVE_EVIDENCE：真实 Raid 多轮/成员关联、Daily 写前后状态、QQ 最终播放与消息送达。
- NEEDS_HUMAN_DECISION：只在具体 Spine runtime 正式采用时做最终许可确认；Guide 当前不列人工任务。
- HARD_BLOCKED：无已确认永久技术阻塞。

本轮没有连接真实账号或执行任何账号写入/测试发送；新增文档允许的受控实验尚未开展。

## 验证与提交

238 passed、2 warnings、31 subtests passed；compileall、diff-check、Node 3 项通过。
审核修复 91ad7f9 的 Actions 已全绿：<https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34019038172>。
后续提交用对应 workflow_dispatch 结果核对。

本轮主要提交：

- 91ad7f9：六项审核修复和当前计划状态。
- 891aa50：CDK 服务层保守限制。
- 9cef44a：按需读取已确认语音资源。
- 59621ef：音频校验和版本化编码缓存。
- a70cebd：公告记录清理、语音缓存过期。
- 剧情 speaker 映射及本报告另有独立提交。

完整提交：`git log --reverse --format="%H %s" fc8d17d790ce2a71ec4682308ccaa27b2d48fab2..HEAD`。
此阶段无需用户上传素材或运行新的命令；后续离线接线仍由 Agent 推进。
