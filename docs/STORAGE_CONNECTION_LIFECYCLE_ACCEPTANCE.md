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
pytest -q                                                       258 passed, 43 subtests
compileall -q .                                                 PASS
node --test tests/extension.test.cjs                             3 passed
git diff --check                                                 PASS
```

新增行为测试先在未修复代码上复现 Windows `PermissionError: [WinError 32]`，修复后通过；同时验证异常事务回滚、原异常传播和连接关闭。本机完整回归不再出现临时 SQLite 清理失败。没有合成图片预览需求，因为本主题不改变用户界面或渲染输出。

## D-14：Python 3.13 兼容性证据

- Python 3.13 已移除标准库 `audioop`；本插件源码没有直接导入 `audioop` 或 `pydub`。本地安装的 AstrBot 4.28.0 元数据会在 `python_full_version >= 3.13` 时声明 `audioop-lts`，本次验证实际安装版本为 `audioop-lts 0.2.2`。
- 在 Windows Python 3.13.13、仓库 `requirements.txt` 加 CI 测试依赖和 AstrBot 4.28.0 的环境中，PR #19 修复后的全量测试为 `258 passed, 43 subtests passed, 1 warning`。
- 修复前的同一 Python 3.13 回路为 `238 passed, 32 failed, 31 subtests passed`；失败均为临时目录清理时的 `PermissionError: [WinError 32]`，原因是 SQLite 连接未明确关闭。PR #19 的显式提交/回滚/关闭连接修复后，原始回路通过。
- CI Python 矩阵扩展为 3.10、3.11、3.12、3.13；CI 只验证对应 Linux 运行环境的依赖、导入、编译和测试，不能替代本地 Windows 文件句柄证据。
- 当前证据范围到 Python 3.13；Python 3.14、真实 AstrBot 进程、生产数据库和真实账号仍未验证，也不据此宣称完成现场联调。

## 证据边界

- CI、真实 AstrBot 进程和生产数据库未访问；本记录只证明本地存储接口及测试生命周期。
- 未修改 `main`、未 force push、未自动合并、未部署、未执行真实账号写操作或消息发送。
