# Plugin Shutdown Lifecycle 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/plugin-shutdown-lifecycle`
- 主题：插件终止流程的顺序幂等与并发幂等
- 用户可见变化：重复或并发触发关闭时，后台任务、反馈管理器、素材管理器和绑定服务只完成一次资源回收。
- 不涉及：网络请求、账号数据、写操作、消息发送、部署、数据库迁移、ruleset 和 `main`。

## 行为合同

`terminate()` 的第一次调用设置关闭状态，取消并等待后台任务，再依次回收反馈、素材和 Web 资源；后续调用等待正在进行的关闭流程，随后直接返回，不重复关闭资源。若第一次回收抛出异常，完成标记不会提前写入，保留后续重试机会。

## TDD 与验证

先行红测：

```text
pytest -q tests/test_background_lifecycle.py
1 failed, 2 passed（重复 terminate 导致 close/stop 调用次数为 2）
```

实现后：

```text
pytest -q -W error::RuntimeWarning tests/test_background_lifecycle.py
5 passed
```

关闭反馈、素材或 Web 资源时即使某一项抛出异常，也会继续尝试后续资源，并重新抛出首个异常；只有全部资源回收成功才设置完成标记，允许后续重试。

专项回归、完整 pytest、`compileall`、Node 扩展测试和最终 CI 结果将在本次最终 head 确认后记录；Windows 上若出现临时 SQLite 文件锁，按独立 PR #19 的已知基线问题记录，不将其归因于本主题。

本主题不修改 UI 或渲染路径，无合成预览要求；未访问真实账号、未发送消息、未部署。
