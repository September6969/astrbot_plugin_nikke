# REFACTOR_PLAN_V2 Phase 0 基线

对应计划：[REFACTOR_PLAN_V2.md](REFACTOR_PLAN_V2.md) 的 `PR-0`。本 PR 只新增门禁、测试与文档。为了让 mypy 进 CI 时是绿的，另外修了 3 处类型标注问题，见第 4 节。

## 1. 基线快照（`ab610f5`）

| 项 | 实测 |
| --- | --- |
| `python scripts/audit/architecture_metrics.py --check` | 退出码 0；648 个 `.py`、267 个生产模块、1,724 条内部导入边、0 循环 |
| 既有跨层边 | 8 条，已登记到 `CROSS_LAYER_BASELINE_ALLOWLIST`（见 [ARCHITECTURE_GATES.md](ARCHITECTURE_GATES.md)） |
| `python -m pytest --collect-only -q` | 1,955 项，0 收集错误（需第 2 节的目录名与依赖） |
| `python -m pytest` | 1,945 通过、8 跳过、2 失败。2 项失败都是本地没装 Python `playwright`（`test_character_pixel_calibration`、`test_spine_batch_review`），CI 会装它 |
| `node --test tests/extension.test.cjs` | 4 通过 / 0 失败 |
| `mypy`（`mypy.ini` 覆盖的 37 个模块，mypy 2.4.1） | `ab610f5` 上有 3 个错误，本 PR 修复后为 0 |
| `SCHEMA_VERSION` | 代码中为 **3**（计划正文写的是 2，以代码为准；本计划各阶段均不改 schema） |

## 2. 测试环境

测试统一按 `from astrbot_plugin_nikke...` 导入，`pytest.ini` 的 `pythonpath = . ..` 依赖检出目录名正好是 `astrbot_plugin_nikke`。

- 工作树请按 `<worktrees>/<branch>/astrbot_plugin_nikke` 布局检出，或者直接在名为 `astrbot_plugin_nikke` 的目录里运行；
- 不要在 `conftest.py` 里注入 `sys.modules` 别名，也不要为此改生产代码的导入方式；
- 依赖与 CI 一致：

```bash
pip install -r requirements.txt pytest pytest-asyncio "astrbot==4.24.0" playwright "mypy==2.4.1"
python -m playwright install chromium   # 可选：像素校准与 Spine 审阅脚本测试需要
```

## 3. 新增门禁

- `scripts/audit/architecture_metrics.py`：新增 `cross_layer_import` 与 `cross_layer_allowlist_stale` 两类违规。Phase 0 对现状仍返回 0 违规；出现新的跨层边会立即变红。
- `.github/workflows/ci.yml`：新增 `static-gates` job，运行 `architecture_metrics.py --check` 与 `mypy`。mypy 版本固定，避免升级 mypy 带来漂移。
- `tests/test_refactor_v2_regression_baseline.py`：回归矩阵覆盖隐私脱敏、换绑授权、绑定会话竞态、调度器异常边界与命令尾参。已复核但尚未修复的缺陷用 `xfail(strict=True)` 标注 AUD 编号，修复它的 PR 必须同时删除标记。

| 标记 | 修复 PR |
| --- | --- |
| AUD-002 换绑继承授权、AUD-014 后发失败覆盖成功 | `PR-1A` |
| AUD-003 调度器被 SQLite 锁终止、AUD-006 脱敏漏项 | `PR-1B` |
| AUD-008 多词角色名与空格批量 CDK 截断 | `PR-2` |

## 4. 类型修复

| 位置 | 修复 | 行为影响 |
| --- | --- | --- |
| `features/character/application.py` | `asyncio.gather(..., return_exceptions=True)` 的结果按 `BaseException` 判定后重新抛出 | 原来如果返回 `CancelledError`，会在 `dict(...)` 处变成 `TypeError`；现在按原取消信号抛出 |
| `features/daily/runner.py` | `_account_locks` 补标注 `dict[str, asyncio.Lock]` | 无 |
| `integrations/calendar/visual_cache.py` | `extensions` 补标注；fake-DNS 分支中 hostname 缺失时按"URL 不允许访问"拒绝 | 原来会把 `None` 写进 `host` 头，导致 httpx 报错 |

## 5. 生产版本核对与成对备份 SOP

以下步骤需要运维在生产机上执行，本 PR 没有触碰生产环境，结果标为**未核对**。

1. 只读核对生产插件目录的提交：`git -C <AstrBot>/data/plugins/astrbot_plugin_nikke rev-parse HEAD`，与 `main` 比较；
2. 涉及 `core/storage.py` 或写状态机的发布（`PR-1A`、`PR-3B`）之前，必须先跑：

```bash
python scripts/operations/upgrade_preflight.py --data-dir /实际路径/AstrBot/data/nikke
python scripts/operations/backup_nikke_data.py --data-dir /实际路径/AstrBot/data/nikke --destination /安全备份目录
```

3. `nikke.sqlite3` 与 `secret.key` 必须成对保存、成对恢复。如果用的是 `NIKKE_ENCRYPTION_KEY` 环境变量，备份时要同时记录密钥来源；
4. 需要回滚时，先停服，再切回上一个版本，然后用 `backup_nikke_data.py --restore-from <备份目录> --restore-destination <新目录>` 恢复到新目录，核对无误后再替换。
