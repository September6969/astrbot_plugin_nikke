# NIKKE 长期路线台账

更新时间：2026-09-06。当前基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

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
| #9 | `feat/announcement-v2` | Announcement Increment A | OPEN / Draft / CI green |
| #10 | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | OPEN / Draft / CI green |
| #11 | `feat/character-data-v2` | Character Data V2 Increment A | OPEN / Draft / CI green |
| #12 | `feat/spine-spike-v2` | Spine technical spike | OPEN / Draft / CI green |
| #13 | `feat/voice-mapping-v2` | Voice mapping public research | OPEN / Draft / CI green |
| #14 | `feat/roadmap-ledger-v3` | Roadmap status reconciliation | OPEN / Draft / CI green |
| #15 | `feat/campaign-history-contract-v2` | Campaign History numeric contract | OPEN / Draft / CI green |

## 当前推进

| 主题 | 分支 | 基线 | 状态 |
| --- | --- | --- | --- |
| Roadmap status reconciliation | `feat/roadmap-ledger-v3` | `bada0b3` | Draft PR #14；台账与工作树索引已同步 |
| Campaign History numeric contract | `feat/campaign-history-contract-v2` | `bada0b3` | Draft PR #15；严格数值/槽位合同，26 个主题测试、合成图片预览和 CI 已验证 |

本轮核验确认：D-01/D-02 已在当前 main，不再重复开实现 PR；D-03、D-04、D-07 也有现行代码和测试证据。

## 依赖与暂缓

- Raid Increment B/C 等待 Raid A 的接口语义进入可复用基线，不能把未合并分支当作当前 main。
- Character Data V2 后续字段等待 registry A 的独立变更合并或明确依赖处理。
- Voice QQ 实际播放、Daily 写入、真实 Profile 和 Spine production runtime 仍需要现场/人工证据。
- 公开只读研究、合成测试和离线 payload 不得冒充真实联调、消息发送或资源授权。
