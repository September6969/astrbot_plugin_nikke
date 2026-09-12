# NIKKE 工作树索引

更新时间：2026-09-11。当前核验的远端基线为 `origin/main@e4a9ff9867dc9a92c203484c748562e4c0a7f1d0`；下表是历史与当前工作索引。工作树可能继续变化，恢复前必须运行 `git worktree list`、逐树 `git status`，并以远端 PR/CI 为权威。

| 范围 | 状态 | 备注 |
| --- | --- | --- |
| `main` | 仅通过 GitHub PR 合并推进 | 本轮未直接修改本地 main、未 force push；当前核验基线 `origin/main@75edaaa` |
| 已合并代码 worktree | 历史/独立分支 | 保留，不删除；其旧 HEAD 不代表当前 main |
| 资源子系统 worktree | 已完成并入 main | #16、#17、#37、#38 按 campaign → single-flight → 全局槽位 → 预取生命周期顺序整合 |
| 日常/存储 worktree | 已完成并入 main | #18、#19、#24、#35、#36 依赖顺序整合并经 CI 验证 |
| 文档/evidence worktree | 已完成并入 main | #31、#33、#39 已分别更新、复核、合并；#14 负责最终台账收口 |
| 现场证据 | Arcana 已完成授权只读采样 | 只保存脱敏结构证据；未执行账号写入、消息发送或部署 |
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
- 当前路线图授权最小现场范围；环境可用时执行真实账号只读、最小必要写入、QQ/NapCat、Voice、Spine 与部署验证；不采集秘密、不修改 ruleset。GitHub 合并仍按独立 PR、exact-head CI 全绿和自审执行，不直接改 main、不 force push、不删分支。

## 当前新增工作树

| 范围 | 状态 | 备注 |
| --- | --- | --- |
| P0 静态 FB / Costume | PR #47 已合并 | `E:\_codex_work\nikke-fb-static-v1` / `feat/fb-static-mainline-v1`；普通出卡不进入 Spine |
| P1 角色卡最终版 | PR #48 已合并 | `E:\_codex_work\nikke-character-card-final-v1` / `feat/character-card-final-v1`；依赖 #47 |
| P1 Item/Cube 完整性 | PR #49 已合并 | `E:\_codex_work\nikke-item-resource-integrity-v1` / `test/item-resource-integrity-v1`；仅补行为矩阵，不制造资源映射 |
| P2 Guide/Help 素材 | PR #50 已合并 | `E:\_codex_work\nikke-guide-assets-v1` / `feat/guide-assets-v1`；原件保留在 `E:\walkthrough` |
| P4 Spine 隔离 | PR #51 已并入当前 main | `E:\_codex_work\nikke-spine-isolation-v1` / `feat/spine-experimental-isolation`；历史隔离分支保留，不代表当前基线 |
| Spine 正式后端 | PR #52 已合并 | `E:\_codex_work\nikke-spine-formal-v1` / `feat/spine-formal-backend-v1`；历史分支保留，HEAD 不代表当前 main |
| Spine 4.1 runtime / Costume | PR #53 已合并 | `E:\_codex_work\nikke-spine-runtime-v1` / `feat/spine-runtime-costume-v1`；历史分支保留，官方 Linux 构建、合法 bundle 和现场渲染仍待证据 |
| Resource Registry V2 | PR #54 已合并 | `E:\_codex_work\nikke-resource-registry-v2` / `feat/resource-registry-v2`；历史分支保留，costume 映射保持空表 |
| Voice Pipeline V2 | PR #55 已合并 | `E:\_codex_work\nikke-voice-pipeline-v2` / `feat/voice-pipeline-v2`；历史分支保留，Poke 动态映射保持空表 |
| Final acceptance / release prep | 当前独立 Draft PR 主题 | `E:\_codex_work\nikke-final-acceptance-v1` / `feat/final-acceptance-v1`；从 `origin/main@2f969756b18ad7e28c41564b07ba0aa60b0dc59d` 建立，收口清单与现场阻塞登记 |
| Live RC Profile stabilization v1 | PR #58 已合并 | `E:\DevCache\nikke-live-rc-profile-stabilization-20260909` / `feat/live-rc-profile-stabilization-v1`；从 `origin/main@d65065b` 建立，Campaign 反查、时间格式化和中性内部 ID 语义已完成离线验证 |
| Live RC Character localization v1 | PR #59 已合并 | `E:\DevCache\nikke-live-rc-localization-20260909` / `feat/live-rc-character-localization-v1`；从 `origin/main@a34f6fc` 建立，统一目录身份字段与 Arcana 查询 alias，HEAD 不代表当前 main |
| Live RC OL contract v1 | PR #60 已合并 | `E:\DevCache\nikke-live-rc-ol-20260909` / `feat/live-rc-ol-contract-v1`；从 `origin/main@530eeef` 建立，固定四部位三 option 行与未知/空槽 fallback，离线证据已通过，HEAD 不代表当前 main |
| Live RC Character stats evidence v1 | PR #61 已合并 | `E:\DevCache\nikke-live-rc-card-evidence-20260909` / `feat/live-rc-card-evidence-v1`；从 `origin/main@bee6d580` 建立，新增 HP/ATK/DEF 脱敏结构诊断，真实字段仍待现场证据，HEAD 不代表当前 main |
| Live RC StateEffect registry v1 | PR #62 已合并 | `E:\DevCache\nikke-live-rc-state-effect-20260909` / `feat/live-rc-state-effect-registry-v1`；从 `origin/main@70c811c` 建立，merge `1a98895e`，严格来源/hash/formatter 合同，映射空表保持待证据 |
| Live Data Closure / Arcana evidence v1 | PR #63 已合并 | `E:\DevCache\nikke-live-data-closure-20260909` / `feat/live-data-closure-v1`；merge `bd5f518e8dcd5001d9b52d0a3f8882f4d7275df5`，保留历史工作树，HEAD 不代表当前 main |
| Live StateEffect data v1 | PR #64 已合并 | `E:\DevCache\nikke-live-state-effect-data-20260909` / `feat/live-state-effect-data-v1`；merge `7c164cd1d9814fc7b4530de861813665187e63b5`，保留历史工作树，HEAD 不代表当前 main |
| Live Numeric Semantics v1 | 当前独立主题 | `E:\DevCache\nikke-live-numeric-semantics-20260909` / `feat/live-numeric-semantics-v1`；从最新 `origin/main@7c164cd1d9814fc7b4530de861813665187e63b5` 建立，严格整数/有限值/fallback 行为测试，未执行账号读取、写入、消息或部署 |
| Live OL Tier Registry v1 | PR #66 已合并 | `E:\DevCache\nikke-ol-tier-registry-20260909` / `feat/ol-tier-registry-v1`；merge `ad0ef208`，9 组/135 ID/1--15 阶级已接线，历史 worktree 保留 |
| Live Data Closure v1 | 当前独立主题 | `E:\DevCache\nikke-live-ol-data-closure-v1-20260909` / `feat/live-ol-data-closure-v1`；从 `origin/main@ad0ef20` 建立，177 角色批量详情、109 条 OL function、HP/ATK/DEF 字段审计与一次授权 Signin 已完成，待提交 PR 与 CI |
| Final live deployment evidence v1 | 当前独立主题 | `E:\DevCache\nikke-final-live-deploy-evidence-20260909` / `feat/final-live-deploy-evidence-v1`；从 `origin/main@39c469e` 建立，记录部署后 healthz、registry、数据库、日志隐私及剩余外部阻塞 |
| Spine-only Portrait & Card Calculation v2 | 当前独立主题 | `E:\DevCache\nikke-spine-only-card-calc-v2-20260909` / `feat/spine-only-card-calc-v2`；从 `origin/main@8910170f` 建立，移除角色路径 FB、升级 Costume identity、接入 OL tier UI 和 fail-closed stat calculator |
| CharacterStatTables / Costume Spine live v1 | PR #72 Draft，进行中 | `E:\DevCache\nikke-stat-costume-spine-live-v1-20260909` / `feat/stat-costume-spine-live-v1`；基线 `origin/main@d3f824cc`。`7be1c6e` 全 CI 通过，默认 Spine 实渲染已查看；旧版 skin01 视觉异常，撤销未经证明的 20001 映射。SSH/HTTPS 已恢复，尚未部署此分支 |

| PR #79 接管续作：Profile v0.4 / Local Spine / Campaign | 进行中，原地追加到现有 PR #79 | `E:\DevCache\nikke-live-runtime-v03` / `fix/live-runtime-v03`；基线/原 head `34786c7`，本轮追加待 push；Profile、local resolver、manifest v2、Campaign capture 已有离线测试，现场 runtime/账号/QQ/部署保持缺口 |
