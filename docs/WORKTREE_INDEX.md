# NIKKE 工作树索引

更新时间：2026-09-06。当前主题从实时 `origin/main` 建立，`main` 未被直接修改。

| 工作树 | 分支 | 用途 | 状态 |
| --- | --- | --- | --- |
| `E:\DevTools\astrbot_plugin_nikke` | `master` | 历史本地 checkout | 不作为当前开发基线 |
| `E:\DevCache\nikke-post-merge\astrbot_plugin_nikke` | `chore/post-merge-sync` | Post-Merge Sync | 已完成 |
| `E:\DevCache\nikke-profile-v2\astrbot_plugin_nikke` | `feat/profile-v2` | Profile V2 | 已完成 |
| `E:\DevCache\nikke-union-raid-v2\astrbot_plugin_nikke` | `feat/union-raid-v2` | Union Raid Increment A | Draft PR #8 |
| `E:\DevCache\nikke-announcement-v2\astrbot_plugin_nikke` | `feat/announcement-v2` | Announcement Increment A | Draft PR #9 |
| `E:\DevCache\nikke-dynamic-voice-v2\astrbot_plugin_nikke` | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | Draft PR #10 |
| `E:\DevCache\nikke-character-data-v2\astrbot_plugin_nikke` | `feat/character-data-v2` | Character Data V2 Increment A | Draft PR #11 |
| `E:\DevCache\nikke-spine-spike-v2\astrbot_plugin_nikke` | `feat/spine-spike-v2` | Spine technical spike | Draft PR #12 |
| `E:\DevCache\nikke-voice-mapping-v2\astrbot_plugin_nikke` | `feat/voice-mapping-v2` | 当前 Voice 映射研究 | Draft PR #13，当前 head CI 全绿 |

## 协作规则

- 每个主题独立 branch/worktree/Draft PR。
- 不直接修改 `main`，不 force push，不自动 merge，不删除分支，不改 ruleset，不部署。
- 公开只读研究、合成测试和离线 payload 不得冒充真实联调、消息发送或资源授权。
