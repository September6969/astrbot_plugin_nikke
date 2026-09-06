# ROADMAP LEDGER

> 此台账从长期路线图 v2 的 Union Raid Increment A 开始维护。历史工作树与已合并 PR 不会因本表出现而被重新归属；每次恢复均以实时 GitHub、`origin/main` 和工作树核验为准。

## TASK-RAID-A

| 字段 | 当前记录 |
| --- | --- |
| 用户能力 | 联盟突袭 overview 与排名的响应范围、解析和展示语义 |
| requirement_id | `REQ-RAID-001` / `REQ-RAID-002` |
| 代码状态 | `IMPLEMENTED` / `WIRED` 的既有链路上进行 Increment A 加固 |
| 证据状态 | 已有脱敏 fixture 与合成行为测试；真实范围完整性仍为 `NEEDS_LIVE_EVIDENCE` |
| 产品状态 | 当前响应范围可离线验证；不宣称完整赛季、当前轮次或真实攻击次数 |
| 工作树 | `E:\DevCache\nikke-union-raid-v2\astrbot_plugin_nikke` |
| 分支 | `feat/union-raid-v2` |
| base SHA | `bada0b3aafcd7127d07ca40f554808b0433540f8` |
| 实现提交 | `665cfeab6e5b7c1946282dd46fdef5e5f114953d`（`feat: harden union raid response semantics`） |
| PR | 尚未创建；交接记录提交并普通 push 后创建 Draft PR |
| CI run / headSha | 尚无已推送主题 HEAD；创建 PR 后必须核对 run 的 `headSha` 与最终分支 HEAD 一致 |
| 行为测试 | 多 `level_info` 不取首项；重复 Boss 不聚合；坏数值不静默转换；负 HP 保留既有归零；排名仅称返回记录 |
| 合成预览 | `E:\DevCache\nikke-card-preview\raid-increment-a-20260906\`，完整/多阶段项/重复 Boss 均已实际查看 |
| 当前阻塞 | `GetUnionRaidLevelInfo` 的多项排序、分页和完整范围没有可验证的公开合同 |
| 已查来源 | 现有 client、builder、历史提交、脱敏 fixture、公开检索；第三方实现未作为合同依据 |
| 最小现场动作 | 仅在明确授权后，用一个真实账号执行一次只读响应采样并脱敏比较；本阶段未执行 |
| N+1 审计 | 本增量只改 builder、renderer 与既有排名格式化；未加入 client 调用、循环内请求或新 endpoint |
| 本地证据 | 额度重置前，同一源码 `python -m pytest -q`：`265 passed, 2 warnings, 50 subtests`；本次恢复后 `python -m compileall -q .`、`node --test tests/extension.test.cjs`（3 passed）和 `git diff --check` 均通过。恢复后的 PATH Python 缺少 `pytest`，故最终 Python 结论以 PR 矩阵 CI 为准。 |
| 下一步 | 提交本交接记录、普通 push、创建 Draft PR，并核验最终 HEAD CI；不自动合并。 |
| 未提交文件 | 本台账、工作树索引与验收记录 |
