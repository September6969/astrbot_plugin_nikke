# NIKKE 长期路线台账

更新时间：2026-09-07。当前基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 已合并

| 主题 | 状态 | 证据 |
| --- | --- | --- |
| Post-Merge Sync | DONE | PR #6 已合并 |
| Profile V2 | DONE | PR #7 已合并 |
| Raid contract/evidence hardening | DONE on main | `8afacc4`、`b964f18`、`26e9e10`；相关行为测试通过 |

## 独立 Draft PR

| PR | 分支 | 主题 | 当前状态 |
| --- | --- | --- | --- |
| #8 | `feat/union-raid-v2` | Union Raid Increment A | OPEN / Draft / CI green |
| #9 | `feat/announcement-v2` | Announcement Increment A + cache lifecycle P1 | OPEN / Draft / CI green；head `fc1c6db`；CI `34097200948` |
| #10 | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | OPEN / Draft / CI green |
| #11 | `feat/character-data-v2` | Character Data V2 Increment A | OPEN / Draft / CI green |
| #12 | `feat/spine-spike-v2` | Spine technical spike | OPEN / Draft / CI green |
| #13 | `feat/voice-mapping-v2` | Voice mapping public research | OPEN / Draft / CI green |
| #14 | `feat/roadmap-ledger-v3` | Roadmap status reconciliation | OPEN / Draft / CI green |
| #15 | `feat/campaign-history-contract-v2` | Campaign History numeric contract | OPEN / Draft / CI green |
| #16 | `feat/campaign-resource-lifecycle-v2` | Campaign renderer asset lifecycle | OPEN / Draft / CI green |
| #17 | `feat/asset-request-dedup-v2` | AssetManager same-key single-flight | OPEN / Draft / CI green；head `8c293d1`；CI `34096785354` |
| #18 | `feat/daily-evidence-p1` | Daily Evidence sign-in recovery safety | OPEN / Draft / CI green；head `3686968`；CI `34099070943` |
| #19 | `feat/storage-connection-lifecycle` | SQLite connection lifecycle hardening | OPEN / Draft / CI green；head `808417e`；CI `34100353287` |
| #20 | `feat/runtime-config-hardening` | Runtime configuration and scheduler boundary hardening | OPEN / Draft / CI green；head `375498c`；CI `34102399018` |
| #21 | `feat/plugin-shutdown-lifecycle` | Plugin shutdown lifecycle idempotency | OPEN / Draft / CI green；head `a9ccb48`；CI `34102939859` |

## 当前推进

| 主题 | 分支 | 基线 | 状态 |
| --- | --- | --- | --- |
| Roadmap status reconciliation | `feat/roadmap-ledger-v3` | `bada0b3` | Draft PR #14；台账与工作树索引已同步 |
| Announcement cache lifecycle P1 | `feat/announcement-v2` | `bada0b3` | Draft PR #9；`last_changed_at`、自动清理、旧缓存安全迁移；head `fc1c6db`；CI `34097200948` 与 headSha 一致；新增 10 项生命周期行为测试 |
| Campaign History numeric contract | `feat/campaign-history-contract-v2` | `bada0b3` | Draft PR #15；严格数值/槽位合同，26 个主题测试、合成图片预览和 CI 已验证 |
| Campaign renderer asset lifecycle | `feat/campaign-resource-lifecycle-v2` | `bada0b3` | Draft PR #16；复用共享 AssetManager，wiring 测试和 CI 已验证 |
| AssetManager request dedup | `feat/asset-request-dedup-v2` | `bada0b3` | Draft PR #17；同一缓存键 5 个并发调用只发 1 次模拟请求；head `8c293d1`；CI `34096785354` 全绿；不宣称全局 N+1、真实资源或账号证据 |
| Daily Evidence sign-in recovery | `feat/daily-evidence-p1` | `bada0b3` | Draft PR #18；intent 先于读取，running/unknown 只读恢复，未确认进入 unknown、Cookie 失效进入 expired；head `3686968`；CI `34099070943` 全绿；不宣称 Like/Browse 或真实账号证据 |
| SQLite connection lifecycle | `feat/storage-connection-lifecycle` | `bada0b3` | Draft PR #19；每次存储操作成功提交/异常回滚并明确关闭连接；Windows 临时目录生命周期回归通过；head `808417e`；CI `34100353287` 全绿 |
| Runtime config hardening | `feat/runtime-config-hardening` | `bada0b3` | Draft PR #20；非法数值配置和损坏持久化调度字段按合同回退，不让调度循环退出；head `375498c`；CI `34102399018` 全绿 |
| Plugin shutdown lifecycle | `feat/plugin-shutdown-lifecycle` | `bada0b3` | Draft PR #21；顺序/并发 terminate 只回收一次资源；head `a9ccb48`；CI `34102939859` 全绿 |

本轮核验确认：D-01/D-02 已在当前 main，不再重复开实现 PR；D-03、D-04、D-07 也有现行代码和测试证据。

## 任务池

- `WAITING_REVIEW`：Announcement V2 / PR #9；Union Raid A / PR #8；Campaign History / PR #15；Campaign renderer lifecycle / PR #16；AssetManager request dedup / PR #17；Daily Evidence / PR #18；SQLite connection lifecycle / PR #19；Runtime config hardening / PR #20；Plugin shutdown lifecycle / PR #21；其余已创建 Draft PR。
- `READY`：在不依赖上述未合并分支的前提下，继续做可离线验证的独立主题。
- `WAITING_DEPENDENCY`：Raid Increment B/C 等待相关基线进入 `main`；不从旧 overnight 分支继续开发。
- `NEEDS_LIVE_EVIDENCE`：真实 Profile、Raid canonical identity、Daily Like/Browse 写入、Voice QQ 实际播放、Spine 生产许可/运行时。
- `NEEDS_HUMAN_DECISION`：自动 merge、ruleset、部署、真实生产 migration、价值 CDK 消费。

## 依赖与暂缓

- Raid Increment B/C 等待 Raid A 的接口语义进入可复用基线，不能把未合并分支当作当前 main。
- Character Data V2 后续字段等待 registry A 的独立变更合并或明确依赖处理。
- Voice QQ 实际播放、Daily 写入、真实 Profile 和 Spine production runtime 仍需要现场/人工证据。
- 公开只读研究、合成测试和离线 payload 不得冒充真实联调、消息发送或资源授权。
