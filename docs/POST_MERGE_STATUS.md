# Post-Merge 状态（2026-09-06，历史检查点）

本文保留 PR #5 合并后的原始检查点，不再是当前运行时状态入口。当前可核验状态见 [路线图台账](ROADMAP_LEDGER.md) 与 [工作树索引](WORKTREE_INDEX.md)：`origin/main` 已前进至 PR #7 的合并提交 `bada0b3aafcd7127d07ca40f554808b0433540f8`；PR #6 与 PR #7 已合并；PR #8 仍是 CI 已绿的 Draft。旧的 overnight 报告同样只作历史验收记录，不代表当前开发分支或当前未合并工作。

## 当前 checkpoint（2026-09-06，必须在每次恢复时重新核验）

| 项目 | 已核实结果 |
| --- | --- |
| 当前远端基线 | `origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8` |
| PR #6 | [Docs: close post-merge status and Phase 2 entry](https://github.com/September6969/astrbot_plugin_nikke/pull/6) 已于 `2026-09-06T19:46:15Z` 合并；merge commit `004ea30272662cc6a72164b77c8c5dc08bef4790`；PR CI [34055588477](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34055588477) 成功。 |
| PR #7 | [Feat: harden Profile V2 dashboard semantics](https://github.com/September6969/astrbot_plugin_nikke/pull/7) 已于 `2026-09-06T19:46:41Z` 合并；PR head `7df799a40c8fdbb12bd71a6775940219760e3b0a`，merge commit 即当前 `bada0b3`；PR CI [34053952299](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34053952299) 成功。 |
| PR #8 | [Feat: harden Union Raid response semantics](https://github.com/September6969/astrbot_plugin_nikke/pull/8) 为 `OPEN` / `DRAFT`；本次同步前 `head = 00f95363dbb8799abc9e2d280ea53645ddc8056e`，CI [34063656074](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34063656074) 成功且 headSha 匹配。 |
| 自动化边界 | 不自动合并任何 PR；每个主题单独分支/工作树，真实账号、写操作、部署和消息发送均未执行。 |

## 历史基线与 PR #5

| 项目 | 已核实结果 |
| --- | --- |
| 仓库 | `September6969/astrbot_plugin_nikke` |
| 默认分支 | `main` |
| 当时远端基线 | `origin/main@a812b7247e997e87886d9c076459bb2463123b15` |
| PR | [#5 Feat/overnight backlog](https://github.com/September6969/astrbot_plugin_nikke/pull/5) |
| PR head | `9a3db964d05ccbed1053ad35a6670cebe572a6c2` |
| 合并时间 | `2026-09-06T17:41:35Z` |
| 合并状态 | `MERGED`；合并提交的树与 PR head 一致 |
| 旧 overnight 分支 | `feat/overnight-backlog` 已合并，仅作历史恢复点，不是当前开发分支 |

PR #5 合并前最终 PR CI run 为 [34049251965](https://github.com/September6969/astrbot_plugin_nikke/actions/runs/34049251965)，`event = pull_request`、`head = 9a3db964d05ccbed1053ad35a6670cebe572a6c2`；以下 job 均为 `SUCCESS`：

- `Test (Python 3.10)`
- `Test (Python 3.11)`
- `Test (Python 3.12)`
- `Extension (Node)`

分支保护查询结果为 `main` 未启用 branch protection，仓库 rulesets 为空。本阶段不修改这些治理设置。

## 状态定义

这里把“代码模块存在”“用户命令已接线”“真实环境已验证”分开记录：

| 能力 | 模块/结构 | 命令接线 | 真实环境证据 |
| --- | --- | --- | --- |
| `/妮姬 我的` Profile | PR #7 已合并：client、model、builder、renderer 与结构化测试 | 已接线；离线闭环完成 | 未使用真实账号；仅离线合成与合成响应测试 |
| Campaign | 已有 stage resolver/history builder/renderer | 已有查询路径 | 未宣称完整账号联调 |
| Union Raid | PR #8 Draft：范围/解析加固、builder、renderer、fixture 与诊断 | overview/排名已接线；历史和“我的”不在 A 范围内 | 身份、多轮、分页与完整范围仍需证据 |
| Daily | 已有只读状态与受控写入框架 | 默认关闭 | 未宣称真实写后状态变化已验收 |
| Voice | 已有本地资源及动态资源管线 | Poke 动态接线仍待做 | 仅公开资源读取和离线编码证据；未发送消息 |
| Spine | 有预检查/队列结构 | 未接入生产渲染运行时 | 未验收真实 runtime 或 Linux benchmark |

## 已关闭事项与剩余边界

PR #5 已收口的审核修复包括 CDK stale-running 防重放、取消传播、Voice 资源预算与生命周期、公开资源许可边界、Guide registry 入口和临时 CI trigger 清理。它们的详细历史证据保留在 [AUTONOMY_REVIEW_REPORT.md](AUTONOMY_REVIEW_REPORT.md) 与 [OVERNIGHT_REPORT.md](OVERNIGHT_REPORT.md)。

当前没有已确认的永久技术阻塞。仍未完成的事项必须按证据状态处理，不能由合成数据、未接线模块或公开资源访问替代真实联调/资源授权：

- Profile V2：离线字段合同、异常值语义、分区去重、请求预算、行为测试和视觉预览已由 PR #7 合并；真实账号兼容性、命令网络联调和部署图仍为 `NEEDS_LIVE_EVIDENCE`。
- Raid 身份关联、多轮范围和剩余次数语义。
- Daily 写入后的真实状态变化。
- Voice 角色/皮肤映射、动态 Poke 接线和实际播放送达。
- Spine 可授权 runtime、真实 server-side render 与 benchmark。

## 本次状态入口验证

A 的文档工作树从上述 `origin/main` 创建，分支名为 `chore/post-merge-sync`。新树的基线回归命令为：

```text
PYTHONPATH=E:/DevCache/nikke-post-merge python -m pytest -q
```

实际结果（Python 3.10.11，2026-09-06）：`248 passed, 2 warnings, 43 subtests passed`。这是合并后基线回归，不是 Profile V2 的验收结果；A 文档变更后的复核结果写入本分支交接记录。

PR #6 与 PR #7 已合并；当前独立主题是 PR #8 的 Raid Increment A，保持 Draft 等待审核。PR #8 不阻塞路线图：下一独立 READY 主题是 Announcement V2，必须从最新 `origin/main` 创建 `feat/announcement-v2`，不继承 PR #8。
