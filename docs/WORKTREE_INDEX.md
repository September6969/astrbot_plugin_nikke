# NIKKE 工作树索引

更新时间：2026-09-08。当前核验的远端基线为 `origin/main@7b1b07cd89b1b5dbac20bf03f2f162b0b22b65c1`；下表是本轮收口时的索引。工作树可能继续变化，恢复前必须运行 `git worktree list`、逐树 `git status`，并以远端 PR/CI 为权威。

| 范围 | 状态 | 备注 |
| --- | --- | --- |
| `main` | 仅通过 GitHub PR 合并推进 | 本轮未直接修改本地 main、未 force push |
| 已合并代码 worktree | 历史/独立分支 | 保留，不删除；其旧 HEAD 不代表当前 main |
| 资源子系统 worktree | 已完成并入 main | #16、#17、#37、#38 按 campaign → single-flight → 全局槽位 → 预取生命周期顺序整合 |
| 日常/存储 worktree | 已完成并入 main | #18、#19、#24、#35、#36 依赖顺序整合并经 CI 验证 |
| 文档/evidence worktree | 已完成并入 main | #31、#33、#39 已分别更新、复核、合并；#14 负责最终台账收口 |
| 现场证据 | 未执行 | 不访问真实账号，不发送消息，不做部署或账号写操作 |
| v4 CDK worktree | PR #41 已合并 | `E:\_codex_work\nikke-v4-cdk` / `feat/v4-cdk-safety`；保留，HEAD 不代表 main |
| v4 Daily worktree | PR #42 已合并 | `E:\_codex_work\nikke-v4-daily` / `feat/v4-daily-safety`；保留，HEAD 不代表 main |
| v4 Costume worktree | PR #43 已合并 | `E:\_codex_work\nikke-v4-costume` / `feat/v4-costume-cache`；保留，HEAD 不代表 main |
| v4 Backup worktree | PR #44 已合并 | `E:\_codex_work\nikke-v4-backup` / `feat/v4-backup-recovery`；保留，HEAD 不代表 main |
| v4 Raid “我的” worktree | PR #45 已合并 | `E:\_codex_work\nikke-v4-raid-my` / `feat/v4-raid-my`；保留，离线证据已记录 |
| v4 Ledger worktree | 当前文档 PR 工作树 | `E:\_codex_work\nikke-v4-ledger` / `docs/v4-ledger-update`；从最新 main 创建 |

## 持久化规则

- 每个新主题独立 branch/worktree/Draft PR。
- 不把旧 overnight 分支、历史文档 SHA 或未合并分支当作当前开发基线。
- 只把实际运行的测试、CI、合成预览和已查来源写入台账；缺少 live evidence 时明确标为缺口。
- 本轮未启用真实账号读写、QQ 发送、部署或资源授权；GitHub 仓库未开放 Auto-Merge，因此未修改设置，所有合并均在 required checks 全绿后完成并保留远端分支。

## 当前新增工作树

| 范围 | 状态 | 备注 |
| --- | --- | --- |
| 六项 Guide / Help | 开发中 | `E:\_codex_work\nikke-guide-assets-v1` / `feat/guide-assets-v1`；基线 `origin/main@c4f1755a`，原件保留在 `E:\walkthrough` |
