# NIKKE 工作树索引

更新时间：2026-09-07。所有当前主题均从实时 `origin/main` 建立；`main` 未被直接修改。

| 工作树 | 分支 | 用途 | 状态 |
| --- | --- | --- | --- |
| `E:\DevTools\astrbot_plugin_nikke` | `master` | 历史本地 checkout | 不作为当前开发基线 |
| `E:\DevCache\nikke-post-merge\astrbot_plugin_nikke` | `chore/post-merge-sync` | Post-Merge Sync | 已完成 |
| `E:\DevCache\nikke-profile-v2\astrbot_plugin_nikke` | `feat/profile-v2` | Profile V2 | 已完成 |
| `E:\DevCache\nikke-union-raid-v2\astrbot_plugin_nikke` | `feat/union-raid-v2` | Union Raid Increment A | Draft PR #8；head `c4a6fe4`；CI `34120205125` 全绿；工作树 clean |
| `E:\DevCache\nikke-announcement-v2\astrbot_plugin_nikke` | `feat/announcement-v2` | Announcement Increment A + cache lifecycle P1 | Draft PR #9；head `84f5032`；CI `34120996910` 全绿；工作树 clean |
| `E:\DevCache\nikke-dynamic-voice-v2\astrbot_plugin_nikke` | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | Draft PR #10；head `afc06d0`；CI `34123169902` 全绿；工作树 clean |
| `E:\DevCache\nikke-character-data-v2\astrbot_plugin_nikke` | `feat/character-data-v2` | Character Data V2 Increment A | Draft PR #11；head `2e77ad2`；CI `34124685883` 全绿；工作树 clean |
| `E:\DevCache\nikke-spine-spike-v2\astrbot_plugin_nikke` | `feat/spine-spike-v2` | Spine technical spike | Draft PR #12；head `137b931`；CI `34115112516` 全绿；工作树 clean |
| `E:\DevCache\nikke-voice-mapping-v2\astrbot_plugin_nikke` | `feat/voice-mapping-v2` | Voice 映射研究 | Draft PR #13；head `68138bc`；CI `34115632353` 全绿；工作树 clean |
| `E:\_codex_work\nikke-roadmap-ledger-v3` | `feat/roadmap-ledger-v3` | 路线图合同债状态核验 | Draft PR #14；当前 head 与 CI 以 PR 检查为权威；工作树 clean |
| `E:\_codex_work\campaign-history-contract-v2\astrbot_plugin_nikke` | `feat/campaign-history-contract-v2` | Campaign History 数值合同 | Draft PR #15；head `6a6a641`；CI `34134245113` 四项全绿；工作树 clean |
| `E:\_codex_work\campaign-resource-lifecycle-v2\astrbot_plugin_nikke` | `feat/campaign-resource-lifecycle-v2` | Campaign renderer 资源生命周期 | Draft PR #16；head `a09493b`；CI `34116765420` 全绿；工作树 clean |
| `E:\_codex_work\asset-request-dedup-v2-worktree\astrbot_plugin_nikke` | `feat/asset-request-dedup-v2` | AssetManager same-key single-flight | Draft PR #17；head `e2d709f`；CI `34117403120` 全绿；工作树 clean |
| `E:\_codex_work\asset-global-concurrency-v1-worktree\astrbot_plugin_nikke` | `feat/asset-global-concurrency-v1` | AssetManager global remote-download limit | Draft PR #37；head `244ba06`；CI `34140238453` 四项全绿；与 PR #17 均修改 `asset_manager.py`，需合并时协调；工作树 clean |
| `E:\_codex_work\asset-prefetch-lifecycle-v1-worktree\astrbot_plugin_nikke` | `feat/asset-prefetch-lifecycle-v1` | AssetManager bounded prefetch lifecycle | Draft PR #38；head `85d1b85`；CI `34141290303` 四项全绿；与 PR #17/#37 均修改 `asset_manager.py`，需合并时协调；工作树 clean |
| `E:\_codex_work\live-evidence-register-v1-worktree\astrbot_plugin_nikke` | `docs/live-evidence-register-v1` | Authorized live-evidence register | Draft PR #39；head `9877fc9`；CI `34142711091` 四项全绿；只记录现场证据最小动作，不执行账号/消息/部署操作；工作树 clean |
| `E:\_codex_work\daily-evidence-p1\astrbot_plugin_nikke` | `feat/daily-evidence-p1` | Daily Evidence sign-in recovery safety | Draft PR #18；head `b7b19f3`；CI `34118342055` 全绿；工作树 clean |
| `E:\_codex_work\storage-connection-lifecycle\astrbot_plugin_nikke` | `feat/storage-connection-lifecycle` | SQLite connection lifecycle hardening | Draft PR #19；head `0e9d323`；CI `34119004278` 全绿；工作树 clean |
| `E:\_codex_work\astrbot_plugin_nikke` | `feat/runtime-config-hardening` | Runtime configuration and scheduler boundary hardening | Draft PR #20；head `375498c`；CI `34102399018`；工作树 clean |
| `E:\_codex_work\shutdown-lifecycle\astrbot_plugin_nikke` | `feat/plugin-shutdown-lifecycle` | Plugin shutdown lifecycle idempotency | Draft PR #21；head `a9ccb48`；CI `34102939859`；工作树 clean |
| `E:\_codex_work\data-backup-hardening\astrbot_plugin_nikke` | `feat/data-backup-hardening` | Offline database and secret.key backup hardening | Draft PR #22；head `6943e12`；CI `34104071393`；工作树 clean |
| `E:\_codex_work\health-diagnostics-v1\astrbot_plugin_nikke` | `feat/health-diagnostics-v1` | Read-only runtime health diagnostics | Draft PR #23；head `4a7190b`；CI `34105103222`；工作树 clean |
| `E:\_codex_work\storage-migration-v1\astrbot_plugin_nikke` | `feat/storage-migration-v1` | Transactional SQLite schema migration | Draft PR #24；head `16c9ac5`；CI `34106285962`；工作树 clean |
| `E:\_codex_work\healthz-readiness-v1\astrbot_plugin_nikke` | `feat/healthz-readiness-v1` | Healthz storage readiness contract | Draft PR #25；head `7e5e928`；CI `34106867556`；工作树 clean |
| `E:\_codex_work\log-privacy-v1-wt\astrbot_plugin_nikke` | `feat/log-privacy-v1` | Plugin log privacy hardening | Draft PR #26；head `87e63e4`；CI `34108218451`；工作树 clean |
| `E:\_codex_work\cache-cleanup-v1-wt\astrbot_plugin_nikke` | `feat/cache-cleanup-v1` | Safe offline cache cleanup | Draft PR #27；head `bb94d18`；CI `34108821103`；工作树 clean |
| `E:\_codex_work\release-metadata-v1-wt\astrbot_plugin_nikke` | `feat/release-metadata-v1` | Release metadata and configuration contract | Draft PR #28；head `1f379d6`；CI `34109454981`；工作树 clean |
| `E:\_codex_work\caddy-hardening-v1-wt\astrbot_plugin_nikke` | `feat/caddy-hardening-v1` | Caddy example privacy hardening | Draft PR #29；head `160cb25`；CI `34110061494`；工作树 clean |
| `E:\_codex_work\upgrade-preflight-v1-wt\astrbot_plugin_nikke` | `feat/upgrade-preflight-v1` | Read-only upgrade/rollback preflight | Draft PR #30；head `e9bf5eb`；CI `34110890912` 全绿；工作树 clean |
| `E:\_codex_work\requirement-evidence-matrix-v1-wt\astrbot_plugin_nikke` | `feat/requirement-evidence-matrix-v1` | Final product review requirement/evidence matrix | Draft PR #31；head `369cc98`；CI `34112221252` 全绿；工作树 clean |
| `E:\_codex_work\tower-snapshot-contract-v1\astrbot_plugin_nikke` | `feat/tower-snapshot-contract-v1` | Tower static snapshot contract | Draft PR #32；head `eede5ab`；CI `34127584276` 全绿；工作树 clean |
| `E:\_codex_work\profile-post-merge-v1\astrbot_plugin_nikke` | `feat/profile-post-merge-v1` | Post-Profile V2 status reconciliation | Draft PR #33；head `8bb9cd5`；CI `34143501124` 四项全绿；同步运行时状态入口并新增文档回归测试；工作树 clean |
| `E:\_codex_work\cdk-batch-contract-v1\astrbot_plugin_nikke` | `feat/cdk-batch-contract-v1` | CDK batch idempotency contract reconciliation | Draft PR #34；head `c0f1e65`；CI `34135996980` 四项全绿；工作树 clean |
| `E:\_codex_work\daily-result-contract-v1\astrbot_plugin_nikke` | `feat/daily-result-contract-v1` | Structured DailyTaskResult status contract | Draft PR #35；head `df7fa7f`；CI `34137301772` 四项全绿；工作树 clean |
| `E:\_codex_work\daily-auto-per-account-v1\astrbot_plugin_nikke` | `feat/daily-auto-per-account-v1` | Per-account daily automation preference | Draft PR #36；head `0ba8b5d`；CI `34138915642` 四项全绿；工作树 clean |

## 协作规则

- 每个主题独立 branch/worktree/Draft PR。
- 不直接修改 `main`，不 force push，不自动 merge，不删除分支，不改 ruleset，不部署。
- 不访问真实账号，不执行账号写操作，不发送消息。
- 公开只读研究、合成测试和离线 payload 不得冒充真实联调、消息发送或资源授权。
