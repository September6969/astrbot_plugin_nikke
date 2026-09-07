# NIKKE 路线图台账

最后核验：2026-09-06（GitHub CLI、`git fetch origin --prune`、本地工作树检查）。这是运行时状态入口；历史文档不替代本台账。

## 远端与 PR

| 项目 | 已核验状态 |
| --- | --- |
| `origin/main` | `bada0b3aafcd7127d07ca40f554808b0433540f8`，PR #7 的合并提交 |
| PR #5 | MERGED，旧 `feat/overnight-backlog` 仅为历史恢复点 |
| PR #6 | MERGED，Post-Merge Sync |
| PR #7 | MERGED，Profile V2 |
| PR #8 | OPEN / Draft，`feat/union-raid-v2@d98cce4c8b898e1ba3aeca3d4234ea2d780cb803`；CI run `34083806757` 的 Node 与 Python 3.10/3.11/3.12 均 SUCCESS |

## 当前独立主题：Announcement V2 Increment A

| 项目 | 状态 |
| --- | --- |
| 分支 / base | `feat/announcement-v2`，从最新 `origin/main@bada0b3` 独立创建；未继承 PR #8 提交 |
| 代码与合同 | 已完成本地实现，见 [Announcement V2 合同](ANNOUNCEMENT_V2_CONTRACT.md) 与 [验收记录](ANNOUNCEMENT_V2_ACCEPTANCE.md) |
| 本地验证 | Python `264 passed, 2 warnings, 43 subtests passed`；Node `3 passed`；`compileall` 与 `git diff --check` 通过 |
| 合成预览 | 已实际查看筛选公告及只读诊断文本；不是图片卡、真实账号、真实 CMS 或消息发送证据 |
| PR / CI | 尚待本分支首个提交、push、Draft PR 及最终 SHA 对应 CI |
| 证据缺口 | 未经授权，不访问真实账号、不做写操作、不发送消息；公开 CMS 未在本次执行中读取 |

## 后续选择规则

Announcement V2 本地验收后应创建 Draft PR 并等待最终 head 对应的 CI。PR #8 和本主题独立推进；任何一个等待审阅或缺少 live evidence 都不阻塞另一个已获授权主题。下一主题仅在两项验收状态写清后再选，不自动合并、部署、改 ruleset 或删除分支。
