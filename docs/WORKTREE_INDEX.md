# NIKKE 工作树索引

更新时间：2026-09-06。以下路径均为独立工作树，`main` 未被本主题直接修改。

| 工作树 | 分支 | 用途 | 状态 |
| --- | --- | --- | --- |
| `E:\DevTools\astrbot_plugin_nikke` | `master` | 历史本地 checkout | 不作为当前开发基线 |
| `E:\DevCache\nikke-post-merge\astrbot_plugin_nikke` | `chore/post-merge-sync` | 已完成 Post-Merge Sync | 保留供审计 |
| `E:\DevCache\nikke-profile-v2\astrbot_plugin_nikke` | `feat/profile-v2` | 已完成 Profile V2 | Draft PR 已留档 |
| `E:\DevCache\nikke-union-raid-v2\astrbot_plugin_nikke` | `feat/union-raid-v2` | Union Raid Increment A | Draft PR #8 |
| `E:\DevCache\nikke-announcement-v2\astrbot_plugin_nikke` | `feat/announcement-v2` | Announcement Increment A | Draft PR #9 |
| `E:\DevCache\nikke-dynamic-voice-v2\astrbot_plugin_nikke` | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | Draft PR #10 |
| `E:\DevCache\nikke-character-data-v2\astrbot_plugin_nikke` | `feat/character-data-v2` | Character Data V2 Increment A | Draft PR #11 |
| `E:\DevCache\nikke-spine-spike-v2\astrbot_plugin_nikke` | `feat/spine-spike-v2` | 当前 Spine 技术预研 | 当前工作树 |

## 协作规则

- 新主题从实时 `origin/main` 建立独立分支/工作树。
- 不直接修改 `main`，不 force push，不自动 merge，不删除分支，不改 ruleset，不部署。
- 每个主题独立提交、测试、CI 和 Draft PR；不能把另一个主题的未合并改动当作当前基线。

