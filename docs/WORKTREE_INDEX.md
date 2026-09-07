# NIKKE 工作树索引

最后核验：2026-09-07（本次文档更新前的状态快照）。下列工作树均在核验时 `git status --short` 为空；长期全局台账以 PR #14 为唯一权威来源，本文件不固定自身更新后产生的 SHA。

| 工作树 | 分支 / HEAD | 用途与状态 |
| --- | --- | --- |
| `E:/DevTools/astrbot_plugin_nikke` | `master@25b2116`，上游 `origin/master` 已删除 | 历史本地 checkout；不是当前开发基线 |
| `E:/DevCache/nikke-overnight/astrbot_plugin_nikke` | `feat/overnight-backlog@9a3db96` | PR #5 历史恢复点；不作为当前开发分支 |
| `E:/DevCache/nikke-post-merge/astrbot_plugin_nikke` | `chore/post-merge-sync@588fc47` | PR #6 已合并的文档检查点 |
| `E:/DevCache/nikke-profile-v2/astrbot_plugin_nikke` | `feat/profile-v2@7df799a` | PR #7 已合并的验收分支 |
| `E:/DevCache/nikke-union-raid-v2/astrbot_plugin_nikke` | `feat/union-raid-v2@当前 HEAD（以 git rev-parse HEAD 为准）` | PR #8 OPEN / Draft；最终 head/CI 以 PR 实时检查为准 |
| `E:/DevCache/nikke-announcement-v2/astrbot_plugin_nikke` | `feat/announcement-v2@84f5032（本次文档更新前）` | 当前独立 Announcement V2 Increment A；[PR #9](https://github.com/September6969/astrbot_plugin_nikke/pull/9) OPEN / Draft；本次重验前 head 对应 CI `34120996910` 全绿，更新后以 PR 实时 `headSha`/CI 为准 |
| `E:/DevCache/nikke-pr3-review/astrbot_plugin_nikke` | detached `3414c70` | 旧审阅检查点；不用于开发 |
| `E:/DevCache/nikke-pr3-review-v2/astrbot_plugin_nikke` | `fix/review-followups@87c1034` | 旧审阅修复分支；不用于当前主题 |

工作树索引只记录定位和当前审阅边界，不授权对历史分支进行删除、重写、force push 或合并。
