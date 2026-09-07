# SQLite 连接生命周期加固验收记录

## 主题与边界

- 分支：`feat/storage-connection-lifecycle`
- 基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`
- 主题：让 `NikkeStore` 的每次 SQLite 操作在提交/回滚后明确关闭连接。
- 该主题不访问网络、真实账号或生产数据库，不改变账号、消息、部署和迁移行为。

## 行为合同

- 成功离开存储操作时提交事务，然后关闭连接。
- 存储操作抛出异常时回滚事务，然后关闭连接并继续抛出原异常。
- `NikkeStore` 实例仍存活时，临时目录也可以安全清理，不遗留 `nikke.sqlite3` 文件句柄。
- 保留原有 WAL、外键、行工厂和公开存储方法；修复只收紧连接生命周期。

## 验证

```text
pytest tests/test_storage_lifecycle.py                         2 passed
pytest tests/test_core.py::StoreTests tests/test_cdk_persistence.py \
  tests/test_cdk_stale_runs.py tests/test_announcement_delivery.py \
  tests/test_announcement_push_wiring.py tests/test_review_cancellation.py \
  tests/test_voice_audio.py                                    26 passed, 12 subtests
pytest -q                                                       257 passed, 43 subtests
compileall -q .                                                 PASS
node --test tests/extension.test.cjs                             3 passed
git diff --check                                                 PASS
```

新增行为测试先在未修复代码上复现 Windows `PermissionError: [WinError 32]`，修复后通过；同时验证异常事务回滚、原异常传播和连接关闭。本机完整回归不再出现临时 SQLite 清理失败。没有合成图片预览需求，因为本主题不改变用户界面或渲染输出。

## 证据边界

- CI、真实 AstrBot 进程和生产数据库未访问；本记录只证明本地存储接口及测试生命周期。
- 未修改 `main`、未 force push、未自动合并、未部署、未执行真实账号写操作或消息发送。
