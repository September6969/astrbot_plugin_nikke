# NIKKE 工作树索引

更新时间：2026-09-08。下表是本轮收口时的索引；工作树可能继续变化，恢复前必须运行 `git worktree list`、逐树 `git status`，并以远端 PR/CI 为权威。

| 范围 | 状态 | 备注 |
| --- | --- | --- |
| `main` | 仅通过 GitHub PR 合并推进 | 本轮未直接修改本地 main、未 force push |
| 已合并代码 worktree | 历史/独立分支 | 保留，不删除；其旧 HEAD 不代表当前 main |
| 资源子系统 worktree | 已完成并入 main | #16、#17、#37、#38 按 campaign → single-flight → 全局槽位 → 预取生命周期顺序整合 |
| 日常/存储 worktree | 已完成并入 main | #18、#19、#24、#35、#36 依赖顺序整合并经 CI 验证 |
| 文档/evidence worktree | 已完成并入 main | #31、#33、#39 已分别更新、复核、合并；#14 负责最终台账收口 |
| 现场证据 | 未执行 | 不访问真实账号，不发送消息，不做部署或账号写操作 |

## 持久化规则

- 每个新主题独立 branch/worktree/Draft PR。
- 不把旧 overnight 分支、历史文档 SHA 或未合并分支当作当前开发基线。
- 只把实际运行的测试、CI、合成预览和已查来源写入台账；缺少 live evidence 时明确标为缺口。
