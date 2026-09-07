# Dynamic Voice V2 Increment A 验收

## 本地行为验证

在 `feat/dynamic-voice-v2` 工作树执行：

```text
python -m pytest -q tests/test_voice_resource_provider.py tests/test_voice_pipeline.py tests/test_feedback_and_voice.py tests/test_voice_audio.py
```

结果：`21 passed`、`12 subtests passed`。

同一工作树的最终本地回归：`python -m pytest -q` 为 `262 passed`、`55 subtests passed`；`node --test tests/extension.test.cjs` 为 3/3 通过。`python -m compileall -q .` 和 `git diff --check` 通过。全量 pytest 在此 Windows 依赖环境中会打印既有 native-trace，但退出码为 0；本增量的 Voice 专项回归不出现该输出。

覆盖点：

- 五个并发请求共享一次 voice map 与一次 MP3 请求；
- manifest 与 MP3 成功落盘，provider 重启后命中持久缓存；篡改身份字段或将 manifest 时间戳置为未来时会重新读取；
- 未确认的 speech ID 不下载音频，失败结果短时复用；
- provider 与 pipeline 拒绝布尔、字符串、NaN、无穷和非正预算/容量；
- 路径逃逸被拒绝；
- provider 关闭会取消在途下载、释放任务引用并拒绝新工作；
- 未登记角色不会回退到 Alice；
- 已登记角色与既有 locale 行为保持兼容。

## 代码与证据状态

| 维度 | 状态 |
| --- | --- |
| 代码状态 | DONE：缓存临时文件复用错误已修复；未知角色语义已显式降级 |
| 测试状态 | DONE：定向与全量本地行为测试、Node 测试、compileall 与 diff check 通过；待 push 后由最终 head 对应 CI 再核验 |
| 合成预览 | 不适用：本增量没有图片卡或音频播放预览；仅使用合成 MP3 头 |
| 现场证据 | NEEDS_LIVE_EVIDENCE：角色/皮肤互动映射、远程资源授权、OneBot 实际播放 |
| 产品状态 | PARTIAL：未接入动态 Poke 互动映射，不宣称真实联调或资源授权 |

## 最小现场动作

若未来获得明确授权，最小动作是读取一个公开、只读且允许使用的 voice map 与对应语音响应，记录字段合同和许可来源；不得登录真实账号、写入账号状态或发送消息。本增量不执行该动作。
