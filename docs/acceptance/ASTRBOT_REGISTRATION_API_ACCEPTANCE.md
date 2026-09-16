# AstrBot 注册 API 迁移验收

## 范围

本主题处理路线图 D-13 / A-CI-05：移除已废弃的 `register_star` 装饰器，保留插件自动发现、元数据和更新仓库地址。

基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`

## 已核实的运行时合同

当前 AstrBot `>=4.24,<5` 代码提供以下行为：

1. `astrbot.core.star.Star.__init_subclass__` 会为继承 `Star` 的插件类建立 `star_map` 元数据。
2. `PluginManager` 优先从插件根目录的 `metadata.yaml` 读取 `name`、`author`、`desc`、`version` 和 `repo`。
3. `register_star` 在本地 AstrBot 包中明确标记为 deprecated，并在首次调用时发出 `DeprecationWarning`。

上述结论来自本地安装包的源代码检查，不代表真实生产实例已经升级或重载。

## 本主题变更

- `main.py` 不再导入或调用 `register`。
- `NikkePlugin(Star)` 保持不变，由 AstrBot 的自动子类注册机制发现。
- `metadata.yaml` 补齐原装饰器中的 `repo` 字段，保留插件更新地址。

## 验收证据

- 在独立子进程中以 `register_star` 弃用警告为错误导入插件，导入成功。
- 同一进程验证 `star_map[NikkePlugin.__module__].star_cls_type is NikkePlugin`。
- 文档测试验证 `metadata.yaml` 保留插件名称和仓库地址。
- 本主题不访问真实账号、不发送消息、不部署，也不宣称生产实例已经完成升级。
