# Character Card v2 Spine 语义锚点验收

## 范围

- 主题：`Character Card v2` 上躯干语义锚点增强。
- 历史开发基线：`origin/main@d79650ae442c7c31e740b281e1332da640b31409`；本次 integration base：`origin/main@e177026edffe36ea10211df9df4380792ebf426d`。
- 分支：`feat/spine-semantic-anchor-v2`。
- 目标角色：`c401`（Spine 4.0）与 `c581`（Spine 4.1）。
- 证据状态：`READY_OFFLINE`；Git/GitHub 集成通过全部门禁后状态为 `READY_FOR_LIVE_DEPLOYMENT`。本轮不部署、不访问真实账号、不发送 QQ 消息。

## 证据

完整的 skeleton、atlas、运行时版本、SHA-256、骨骼/attachment 计数、idle `t=0` 与 `t=0.5` 采样及选择结果见：

- `docs/evidence/spine_semantics/c401_c581_idle_audit_20260921.json`
- `docs/evidence/spine_semantics/c401_c581_idle_audit_20260921.md`

原始 bundle 仅在服务器只读核验和本地临时审计目录中使用，不提交仓库；证据不声称素材分发授权或生产联调。

## 选择合同

上躯干选择优先级为：单次渲染手工覆盖 → 已有 verified override → 语义 registry → 已验证 attachment mapping → 保守通用名称匹配 → fail closed。`op*`、发饰、外套、武器、特效、屏幕位置和任意平均值不能单独成为上躯干证据。

- `c401`：resource/render `c401` / `401:default`；`body_total/body_total` attachment，骨骼 `move3`，父级 `move2`，来源 `override`，置信度 `0.98`。
- `c581`：resource/render `c581` / `581:default`；`chest_l + chest_r` bone pair，父级 `pelvis7`，来源 `semantic`，置信度 `0.96`。

结构化 `bone_pair`、`attachment`、`surface` 记录只由新选择器消费；旧的单骨骼 mapper 不会把它们伪造成空骨骼或单骨骼匹配。

## 兼容性

- `SelectedPoint.confidence` 有默认值，旧调用仍有效。
- `breast_y` metadata/layout 输入继续兼容；新路径使用 `torso_y` / `upper_torso_y`。
- `vertical_gain` 保持 `0.0`；自动缩放下限为 `0.94`（最多 6%），超过预算且无法满足安全区时 fail closed。
- `attachment_candidates_1024` 只属于 extractor discovery sidecar，不写入 runtime metadata。
- 旧 `breast_point` / `breast_source` 输出别名保留，正式诊断增加 `torso_*` 字段。

## 验收记录

- 定向 Python Character/Spine/T2I：`86 passed`，覆盖 c401/c581 semantic path、旧 c016/c191、dynamic Summary、0 row Summary、empty equipment 与 fallback。
- Node sidecar/surface：`6 passed`。
- Calendar smoke：`27 passed`（canonical title、duplicate normalization、分类与 display ordering）。
- `python -m compileall -q .`：通过。
- `node --check scripts/extract_spine_face_anchor.mjs scripts/spine_attachment_candidates.mjs`：通过。
- `git diff --check`：通过；Git 的 LF→CRLF 提示不是 diff 错误。
- 最终唯一 full pytest（本次 main 对齐后）：`1128 passed, 2 skipped, 648 subtests passed, 17 failed`。失败为 11 个既有 Boss resolver、5 个既有 Lineup resolver 的相对素材路径/镜像环境问题，以及 `tests/test_registration_api.py::test_import_uses_star_auto_registration_without_deprecated_decorator` 从旁边旧 `E:\_codex_work\astrbot_plugin_nikke` worktree 加载 deprecated decorator；Character/Spine/Calendar 没有失败。未修改业务代码迎合环境，也未重复 full pytest。
- 使用临时包别名隔离当前分支后，等价自动注册导入核验通过；当前分支 `main.py` 不含已弃用装饰器。
- 旧基线 CI run `35635088655` 仅作历史记录；对齐后的 PR CI 使用新 push 后 run，必须以新的 Node、Spine 4.0 headless worker、Python 3.10、3.11、3.12、3.13 全绿为合并门禁。

缺少生产 runtime、账号、QQ 或部署证据时保持 `READY_OFFLINE`，不升级为 live 完成。
