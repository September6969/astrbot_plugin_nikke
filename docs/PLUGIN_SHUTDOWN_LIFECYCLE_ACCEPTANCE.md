# Plugin Shutdown Lifecycle 验收记录

## 范围

- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 分支：`feat/plugin-shutdown-lifecycle`
- 主题：插件终止流程的顺序幂等与并发幂等
- 用户可见变化：重复或并发触发关闭时，后台任务、反馈管理器、素材管理器和绑定服务只完成一次资源回收。
- 不涉及：网络请求、账号数据、写操作、消息发送、部署、数据库迁移、ruleset 和 `main`。

## 行为合同

`terminate()` 的第一次调用设置关闭状态，取消并等待后台任务，再依次回收已初始化的反馈、素材和 Web 资源；后续调用等待正在进行的关闭流程，随后直接返回，不重复关闭资源。注入的 falsey 资源仍按对象是否为 `None` 判断；部分初始化时缺失 Web 资源也可安全完成剩余清理。若第一次回收抛出异常，完成标记不会提前写入，保留后续重试机会。

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

本次补丁新增部分初始化（缺失 Web）和 falsey 资源清理回归；完整 wiring 仍交由 CI 依赖环境验证。

关闭反馈、素材或 Web 资源时即使某一项抛出异常，也会继续尝试后续资源，并重新抛出首个异常；只有全部资源回收成功才设置完成标记，允许后续重试。

- 本次代码提交 `c57209d` 对应 CI run `34172190073`：Python 3.10 全量 `261 passed`、`43 subtests`、`3 warnings`；Python 3.11/3.12 与 Node 扩展测试均通过。`compileall` 与 `git diff --check` 通过；Windows 上若出现临时 SQLite 文件锁，按独立 PR #19 的已知基线问题记录，不将其归因于本主题。

本主题不修改 UI 或渲染路径，无合成预览要求；未访问真实账号、未发送消息、未部署。
