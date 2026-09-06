# 动态语音与运行时许可研究（2026-09-06）

## 来源核验

从 [NIKKE 官网](https://nikke-en.com/) 页脚提取 Secondary Creative Activities Guideline 链接，内容 ID 为 `dd1e01cfa3ad7a4a92a83a8aaa1402e17feb`。
使用已验证的 InformationFeeds `GetContentInfoById` 只读接口匿名请求：外层 code=0、内层 result=0，标题正确，正文引用 [SHIFT UP 原始指引](https://policy.shiftup.co.kr/ip/en/index.html)。已同时读取该原始页面。

该指引定义二创需要新的表达或创意添加，单纯复制原作品不属于二创；还涉及使用范围、第三方权利及来源标注。因此，不能从这份指引推出原始 MP3 可作为插件资源再分发。此为工程范围判断，不是已取得授权的声明。

[Level Infinite 官网条款](https://www.levelinfinite.com/terms-of-service/english/)描述个人有限的网站使用许可；[Level Infinite Pass 条款](https://account.levelinfinite.com/tos.html)明确游戏另有游戏协议。两者均不能替代针对 BlaBlaLink 音频再分发的证据。官网当前 NIKKE EULA 指向 `/termsofservice/children/en.html`，本轮浏览抓取超时，未用旧 CBT 条款冒充当前版本。

## Spine

已读取 [Spine Runtimes License](https://en.esotericsoftware.com/spine-runtimes-license) 与 [Editor License](https://esotericsoftware.com/licenses/Spine-Editor-License-Agreement.pdf) 第 2 节。运行时集成、分发和编辑器许可存在明确关联，替代路径也要求产品用户持有许可并随附声明。公开源码不等于无条件自由再分发。

状态：已找到权威许可文本；具体采用方式仍为 NEEDS_HUMAN_DECISION。版本检查、输入验证、队列预算和使用合成素材的外围测试可以继续，不以此作为整个开发停止理由。本轮未购买、接受协议、下载运行时或对外联系。

## 语音管线推进

`voice_pipeline.py` 将已存在的 provider 与 encoder 组合：默认 4 秒请求预算（上限 5 秒）覆盖下载、排队、编码全过程；同键任务共享，最多 20 项；后台准备最长 35 秒；关闭取消等待中的编码并回收 provider。

这是独立、可注入测试的准备层，未宣称插件生产生命周期已经接入，也没有改变语音类型或角色/皮肤语义。已知剧情记录继续保留 story/skin=None，未冒充互动语音。

后续：确认互动映射及适用资源权限后再接入 Poke；OneBot 最终播放仍需 NEEDS_LIVE_EVIDENCE。当前没有触发真实消息发送或真实账号写操作。

## AstrBot / OneBot 序列化证据

本地已安装 AstrBot 的 `Record.fromFileSystem()` 创建本地文件组件；`AiocqhttpMessageEvent._from_segment_to_dict()` 对 Record 调用 `convert_to_base64()`，生成 `type=record`、`data.file=base64://...`。该转换本身没有进行音频转码。

新增 `tests/test_voice_adapter.py` 用合成的 24kHz 单声道 WAV 调用真实转换方法，验证解码字节完全一致且协议载荷不包含本地路径；未调用任何发送接口。这解除该版本适配器需要 NapCat 与 AstrBot 共享音频文件路径的假设，但不能证明远端实际播放，也不证明所有版本相同行为。
