# 整仓重构架构门禁

此门禁按 `planning/full_repository_refactor_v2/PLAN.md` 与 `TASKS.json` 执行。门禁从 R01 起纳入版本控制；初始红灯是当前架构债务的可复现基线，不表示后续迁移可以忽略该检查。

## 可重复指标

运行：

```powershell
python scripts/architecture_metrics.py --output <run_dir>/architecture-current.json
python scripts/architecture_metrics.py --baseline <run_dir>/architecture-baseline.json --output <run_dir>/architecture-current.json
python scripts/architecture_metrics.py --check
```

指标使用 Python AST 和仓库静态文件，不安装依赖、不导入插件、不访问网络或数据库。输出包括：

- 六个计划热点的行数/字节数、最大生产模块、插件公开方法的 AST 语句数与复杂度提示。
- 仓库内部静态导入边、强连通循环、公共 `__init__.py` 导出清单。
- features/ui/main/adapter 依赖方向、容器定义位置、关键资源构造位置、后台任务创建点。
- 空转发模块、通配符导入、模块级及 class-level `__getattr__`、适配器资源构造和默认关闭 Profile 路由标记。
- 对照格式中的热点行数增量、模块/导入边变化、循环新增/消除及门禁违规数变化。

指标不将行数当作迁移的充分条件。薄包装测试会识别只转发导入、星号导入和动态属性转发；入口、资源 owner 和实际依赖边仍需各自通过静态门禁与消费者测试。

## 硬阈值

硬阈值由 `scripts/architecture_metrics.py` 和对应架构测试共同锁定：`main.py` 700 行、`adapters/astrbot/command_runtime.py` 400 行、`core/asset_manager.py` 300 行、`ui/t2i_payloads.py` 100 行、Calendar `schedule_service.py` 450 行、Announcement `service.py` 450 行、`core/container.py` 350 行。插件业务方法最多 20 个 AST 逻辑语句；构造和关闭方法不计入该规则。

`command_runtime.py` 另有责任门禁：不得导入 `features`、`integrations`、`ui` 或 storage 实现，不得直接访问领域 application、client、store、AssetManager 或 renderer。feature DTO / domain exception 的宿主转换仍可留在专用 AstrBot adapter；command router 不承担 feature use-case orchestration。

class-level `__getattr__` 默认视为过宽动态转发并失败。唯一保留项是 `features/announcement/service.py::AnnouncementService` 对 `_COMPAT_STATE` 显式成员集合的兼容访问；门禁同时核对成员检查和 `AttributeError` 终止分支。不得把此例外扩展成 runtime/plugin 双向代理。

所有 `adapters/` 静态拒绝直接导入 `integrations/`、SQL/network client 模块、`core.storage`、`core.container` 与 `core.providers`；直接创建共享 store/client/AssetManager/ClientSession 也失败。AstrBot event 转换可以引用 framework-free application handler、必要的结果 DTO/领域异常和 presentation renderer；用例流程必须留在 `application/commands/`。

## 初始红灯

R01 在 R00 checkpoint 上首次运行 `tests/test_full_refactor_architecture.py`，记录失败门禁与指标。预期红灯必须对应实际旧结构；测试框架自检、指标计算、薄包装识别和对照格式测试必须通过。之后每张迁移卡只在其目标结构真实改变且消费者切换后才允许相应门禁转绿。

每个 checkpoint 的架构指标写入运行目录 `architecture-baseline.json` 或 `architecture-current.json`，同时保留 checkpoint SHA 与 source manifest。不得通过删除断言、扩宽阈值、跳过模块或把实现搬进另一个巨型通用文件消除红灯。
