# 整仓重构架构门禁

此门禁按 `planning/full_repository_refactor_v2/PLAN.md` 与 `TASKS.json` 执行。门禁从 R01 起纳入版本控制；初始红灯是当前架构债务的可复现基线，不表示后续迁移可以忽略该检查。

## 可重复指标

运行：

```powershell
python scripts/audit/architecture_metrics.py --output <run_dir>/architecture-current.json
python scripts/audit/architecture_metrics.py --baseline <run_dir>/architecture-baseline.json --output <run_dir>/architecture-current.json
python scripts/audit/architecture_metrics.py --check
```

指标使用 Python AST 和仓库静态文件，不安装依赖、不导入插件、不访问网络或数据库。输出包括：

- 六个计划热点的行数/字节数、最大生产模块、插件公开方法的 AST 语句数与复杂度提示。
- 仓库内部静态导入边、强连通循环、公共 `__init__.py` 导出清单。
- features/ui/main/adapter 依赖方向、容器定义位置、关键资源构造位置、后台任务创建点。
- 空转发模块、通配符导入、模块级及 class-level `__getattr__`、适配器资源构造和默认关闭 Profile 路由标记。
- 对照格式中的热点行数增量、模块/导入边变化、循环新增/消除及门禁违规数变化。

指标不将行数当作迁移的充分条件。薄包装测试会识别只转发导入、星号导入和动态属性转发；入口、资源 owner 和实际依赖边仍需各自通过静态门禁与消费者测试。

## 硬阈值

硬阈值由 `scripts/audit/architecture_metrics.py` 和对应架构测试共同锁定：`main.py` 300 行（PR-6C 删除 36 个未注册遗留方法后由 700 收紧）、`adapters/astrbot/command_runtime.py` 400 行、`core/asset_manager.py` 300 行、`ui/t2i_payloads.py` 100 行、Calendar `schedule_service.py` 450 行、Announcement `service.py` 450 行、`core/container.py` 350 行。插件业务方法最多 20 个 AST 逻辑语句；构造和关闭方法不计入该规则。

`NikkePlugin` 公开成员另有白名单门禁 `main_public_member_allowlist`（`MAIN_PUBLIC_MEMBER_ALLOWLIST`）：只允许 `command_runtime`、`nikke`、`nikke_hash_prefix`、`on_nikke_poke`；`terminate`/`close` 为宿主生命周期、私有成员（`__init__`、`_apply_directory`）不计入。新增公开成员前须补消费者证据并同步更新白名单与 `docs/architecture/ASTRBOT_COMMAND_ENTRY_MAP.md`。

`command_runtime.py` 另有责任门禁：不得导入 `features`、`integrations`、`ui` 或 storage 实现，不得直接访问领域 application、client、store、AssetManager 或 renderer。feature DTO / domain exception 的宿主转换仍可留在专用 AstrBot adapter；command router 不承担 feature use-case orchestration。

class-level `__getattr__` 默认视为过宽动态转发并失败。唯一保留项是 `features/announcement/service.py::AnnouncementService` 对 `_COMPAT_STATE` 显式成员集合的兼容访问；门禁同时核对成员检查和 `AttributeError` 终止分支。不得把此例外扩展成 runtime/plugin 双向代理。

所有 `adapters/` 静态拒绝直接导入 `integrations/`、SQL/network client 模块、`core.storage`、`core.container` 与 `core.providers`；直接创建共享 store/client/AssetManager/ClientSession 也失败。AstrBot event 转换可以引用 framework-free application handler、必要的结果 DTO/领域异常和 presentation renderer；用例流程必须留在 `application/commands/`。

## 跨层依赖基线（REFACTOR_PLAN_V2 Phase 0）

`CROSS_LAYER_FORBIDDEN_TARGETS` 规定分层方向 `adapters -> application -> features <- integrations`，生产代码不得依赖 `scripts/` 与 `tests/`。违反方向的内部导入边记为 `cross_layer_import`。

`CROSS_LAYER_BASELINE_ALLOWLIST` 只登记 Phase 0 时已存在的 8 条边，并且只允许删减：

| 既有边 | 计划清零阶段 |
| --- | --- |
| `application.commands.{campaign,cdk,character,daily,profile,raid}` → `integrations.blablalink.client` | Phase 2（`PR-2`） |
| `integrations.spine.prerenderer` → `scripts.spine.inspect_spine_bundle` | Phase 4（`PR-4C`，已清零：预检查迁入 `integrations.spine.bundle_inspection`，`scripts/spine/inspect_spine_bundle.py` 仅保留 CLI 薄入口；已转为硬门禁） |
| `features.calendar.schedule_service` → `integrations.calendar.blabla_source` | Phase 6（`PR-6B`，已清零：`BlablaCalendarAdapter` 由组合根 `core/providers/announcement.py` 以 `adapters=` 注入，`source_mode` 已删除；已转为硬门禁） |

某条边对应的导入被移除后，门禁会报 `cross_layer_allowlist_stale`，要求在同一 PR 中删掉该条目，使其变成硬门禁。

**现状（PR-6B 起）**：Phase 0 的 8 条基线边已全部清零，`CROSS_LAYER_BASELINE_ALLOWLIST` 为空集；`tests/test_full_refactor_architecture.py::test_cross_layer_baseline_only_shrinks` 断言其 `== frozenset()`，任何新增跨层边都直接以 `cross_layer_import` 失败。

## 初始红灯

R01 在 R00 checkpoint 上首次运行 `tests/test_full_refactor_architecture.py`，记录失败门禁与指标。预期红灯必须对应实际旧结构；测试框架自检、指标计算、薄包装识别和对照格式测试必须通过。之后每张迁移卡只在其目标结构真实改变且消费者切换后才允许相应门禁转绿。

每个 checkpoint 的架构指标写入运行目录 `architecture-baseline.json` 或 `architecture-current.json`，同时保留 checkpoint SHA 与 source manifest。不得通过删除断言、扩宽阈值、跳过模块或把实现搬进另一个巨型通用文件消除红灯。
