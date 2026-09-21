# Character Card v2 Spine 语义锚点验收

## 范围

- 主题：`Character Card v2` 上躯干语义锚点增强。
- 基线：`origin/main@d79650ae442c7c31e740b281e1332da640b31409`。
- 分支：`feat/spine-semantic-anchor-v2`。
- 目标角色：`c401`（Spine 4.0）与 `c581`（Spine 4.1）。
- 状态：`READY_OFFLINE`；本轮不部署、不访问真实账号、不发送 QQ 消息。

## 证据

完整的 skeleton、atlas、运行时版本、SHA-256、骨骼/attachment 计数、idle `t=0` 与 `t=0.5` 采样及选择结果见：

- `docs/evidence/spine_semantics/c401_c581_idle_audit_20260921.json`
- `docs/evidence/spine_semantics/c401_c581_idle_audit_20260921.md`

原始 bundle 仅在服务器只读核验和本地临时审计目录中使用，不提交仓库；证据不声称素材分发授权或生产联调。

## 选择合同

上躯干选择优先级为：单次渲染手工覆盖 → 已有 verified override → 语义 registry → 已验证 attachment mapping → 保守通用名称匹配 → fail closed。`op*`、发饰、外套、武器、特效、屏幕位置和任意平均值不能单独成为上躯干证据。

- `c401`：`body_total/body_total` attachment，骨骼 `move3`，父级 `move2`，来源 `override`，置信度 `0.98`。
- `c581`：`chest_l + chest_r` bone pair，父级 `pelvis7`，来源 `semantic`，置信度 `0.96`。

结构化 `bone_pair`、`attachment`、`surface` 记录只由新选择器消费；旧的单骨骼 mapper 不会把它们伪造成空骨骼或单骨骼匹配。

## 兼容性

- `SelectedPoint.confidence` 有默认值，旧调用仍有效。
- `breast_y` metadata/layout 输入继续兼容；新路径使用 `torso_y` / `upper_torso_y`。
- `attachment_candidates_1024` 只属于 extractor discovery sidecar，不写入 runtime metadata。
- 旧 `breast_point` / `breast_source` 输出别名保留，正式诊断增加 `torso_*` 字段。

## 验收记录

- 定向 Python：`30 passed`。
- Node sidecar/surface：`6 passed`。
- `python -m compileall -q .`：通过。
- `node --check scripts/extract_spine_face_anchor.mjs scripts/spine_attachment_candidates.mjs`：通过。
- `git diff --check`：通过；Git 的 LF→CRLF 提示不是 diff 错误。
- 最终唯一 full pytest：`1130 passed, 2 skipped, 653 subtests passed, 1 failed`。失败为既有 `tests/test_registration_api.py::test_import_uses_star_auto_registration_without_deprecated_decorator` 的子进程环境问题：测试经 `Path.resolve()` 取到当前 worktree 的父目录后，父目录中同名的旧 `E:\_codex_work\astrbot_plugin_nikke` worktree 抢先被导入；错误 traceback 已指向该旁边旧树的 `main.py`。未修改该旧树，也未重复 full pytest。
- 使用临时包别名隔离当前分支后，等价自动注册导入核验通过，输出 `astrbot_plugin_nikke.main`；当前分支 `main.py` 不含已弃用装饰器。
- GitHub CI run `35635088655`：Extension (Node)、Spine 4.0 headless worker、Python 3.10、3.11、3.12、3.13 全部通过。

缺少生产 runtime、账号、QQ 或部署证据时保持 `READY_OFFLINE`，不升级为 live 完成。
