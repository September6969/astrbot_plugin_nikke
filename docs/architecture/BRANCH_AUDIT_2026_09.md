# Git 远程分支卫生治理与清理审计报告 (2026-09)

> **遵循原则**：
> 严格遵循 Issue #82 第 7 节要求：**逐条确认，拒绝一键批量删除**。
> 仅清理 `ahead=0` 且其全部提交已完整并入 `origin/main` 的陈旧历史分支；对任何存在独立提交（`ahead > 0`）的分支予以 **100% 完整保留与安全隔离**。

---

## 一、审计概览

- **审计基准**：`origin/main` (commit: 2863d5d)
- **扫描远程分支总数**：86
- **完全已合并分支（ahead = 0）**：65 个（符合安全清理条件）
- **独立/未合并分支（ahead > 0）**：15 个（严格保留，禁止删除）
- **Issue #82 阶段性 PR 分支**：6 个（已通过 Squash Merge 并入 main）

---

## 二、保留与隔离分支清单（ahead > 0，严禁删除）

以下 15 个分支包含尚未并入 `origin/main` 的独立提交或特定现场证据，**全部完整保留**：

| 分支名 | Ahead 提交数 | Behind 提交数 | 说明与保留理由 |
| :--- | :---: | :---: | :--- |
| `origin/docs/live-costume-evidence-v1` | 1 | 94 | 包含 live costume 证据链文件 |
| `origin/feat/character-card-final-v1` | 4 | 128 | 历史探索卡面方案与参考资料 |
| `origin/feat/fb-static-mainline-v1` | 2 | 129 | 静态资源主线历史分支 |
| `origin/feat/final-live-deploy-evidence-v1` | 1 | 95 | 独立部署现场验证证据 |
| `origin/feat/guide-assets-v1` | 3 | 126 | 攻略资源独立提交 |
| `origin/feat/live-data-closure-v1` | 1 | 100 | Live 数据闭环现场记录 |
| `origin/feat/live-numeric-semantics-v1` | 1 | 98 | 数值语义未并入提交 |
| `origin/feat/live-ol-data-closure-v1` | 4 | 96 | OL 原始抓取数据快照 |
| `origin/feat/live-state-effect-data-v1` | 1 | 99 | 状态效果原始数据快照 |
| `origin/feat/ol-tier-registry-v1` | 1 | 97 | 历史词条注册表试验数据 |
| `origin/feat/spine-experimental-isolation` | 6 | 125 | Spine 实验性隔离方案与早期工作 |
| `origin/feat/spine-only-card-calc-v2` | 1 | 93 | Spine 纯本地测算原型 |
| `origin/feat/stat-costume-spine-live-v1` | 22 | 92 | 22 个独立测试/数据提交，需长期归档 |
| `origin/fix/live-spine-assets-v03` | 1 | 63 | 包含现场资源修正未并入部分 |
| `origin/test/item-resource-integrity-v1` | 2 | 127 | 早期独立测试资产 |

---

## 三、安全清理候选清单（ahead = 0，已 100% 并入 main）

以下 65 个分支的所有提交均已被 `origin/main`（或 PR #84 / 历次正式 PR）完整吸纳，无任何未合并悬挂 commit：

1. `chore/post-merge-sync` (behind 445)
2. `docs/live-evidence-register-v1` (behind 254)
3. `docs/v4-ledger-update` (behind 130)
4. `feat/announcement-v2` (behind 354)
5. `feat/asset-global-concurrency-v1` (behind 294)
6. `feat/asset-prefetch-lifecycle-v1` (behind 282)
7. `feat/asset-request-dedup-v2` (behind 316)
8. `feat/astrbot-registration-api-v1` (behind 440)
9. `feat/cache-cleanup-v1` (behind 439)
10. `feat/caddy-hardening-v1` (behind 440)
11. `feat/calendar-v04` (behind 28)
12. `feat/campaign-history-contract-v2` (behind 435)
13. `feat/campaign-resource-lifecycle-v2` (behind 275)
14. `feat/cdk-batch-contract-v1` (behind 439)
15. `feat/character-card-data-contract` (behind 504)
16. `feat/character-card-pixel-calibration-v1` (behind 15)
17. `feat/character-data-v2` (behind 327)
18. `feat/character-replica-calendar-v05` (behind 19)
19. `feat/daily-auto-per-account-v1` (behind 329)
20. `feat/daily-evidence-p1` (behind 433)
21. `feat/daily-result-contract-v1` (behind 337)
22. `feat/data-backup-hardening` (behind 364)
23. `feat/dynamic-voice-v2` (behind 296)
24. `feat/final-acceptance-v1` (behind 113)
25. `feat/health-diagnostics-v1` (behind 371)
26. `feat/healthz-readiness-v1` (behind 439)
27. `feat/live-rc-card-evidence-v1` (behind 103)
28. `feat/live-rc-character-localization-v1` (behind 107)
29. `feat/live-rc-ol-contract-v1` (behind 105)
30. `feat/live-rc-profile-stabilization-v1` (behind 109)
31. `feat/live-rc-state-effect-registry-v1` (behind 101)
32. `feat/log-privacy-v1` (behind 268)
33. `feat/overnight-backlog` (behind 448)
34. `feat/plugin-shutdown-lifecycle` (behind 437)
35. `feat/profile-post-merge-v1` (behind 263)
36. `feat/profile-v2` (behind 445)
37. `feat/recent-work-integration-v1` (behind 7)
38. `feat/release-metadata-v1` (behind 366)
39. `feat/requirement-evidence-matrix-v1` (behind 257)
40. `feat/resource-registry-v2` (behind 117)
41. `feat/roadmap-ledger-v3` (behind 147)
42. `feat/runtime-config-hardening` (behind 437)
43. `feat/spine-formal-backend-v1` (behind 123)
44. `feat/spine-runtime-costume-v1` (behind 119)
45. `feat/spine-spike-v2` (behind 331)
46. `feat/storage-connection-lifecycle` (behind 436)
47. `feat/storage-migration-v1` (behind 439)
48. `feat/t2i-campaign-phase1` (behind 17)
49. `feat/tower-snapshot-contract-v1` (behind 439)
50. `feat/ui-polish-v0.3` (behind 66)
51. `feat/union-raid-v2` (behind 432)
52. `feat/upgrade-preflight-v1` (behind 437)
53. `feat/v4-backup-recovery` (behind 145)
54. `feat/v4-cdk-safety` (behind 142)
55. `feat/v4-costume-cache` (behind 144)
56. `feat/v4-daily-safety` (behind 144)
57. `feat/v4-raid-my` (behind 137)
58. `feat/voice-mapping-v2` (behind 334)
59. `feat/voice-pipeline-v2` (behind 115)
60. `fix/live-runtime-v03` (behind 30)
61. `fix/remove-ael-residue-v1` (behind 111)
62. `fix/review-followups` (behind 487)
63. `fix/spine-4.0-worker-ci` (behind 69)
64. `prep/blabla-static-assets` (behind 14)
65. `refactor/code-quality-v0.3` (behind 70)
