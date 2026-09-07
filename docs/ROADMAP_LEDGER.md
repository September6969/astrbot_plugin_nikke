# NIKKE 长期路线台账

更新时间：2026-09-06。当前基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 已合并

| 主题 | 状态 | 说明 |
| --- | --- | --- |
| Post-Merge Sync | DONE | PR #6 已合并 |
| Profile V2 | DONE | PR #7 已合并 |

## 独立 Draft PR

| PR | 分支 | 主题 | 当前状态 |
| --- | --- | --- | --- |
| #8 | `feat/union-raid-v2` | Union Raid Increment A | OPEN / Draft / CI green |
| #9 | `feat/announcement-v2` | Announcement Increment A | OPEN / Draft / CI green |
| #10 | `feat/dynamic-voice-v2` | Dynamic Voice Increment A | OPEN / Draft / CI green |
| #11 | `feat/character-data-v2` | Character Data V2 Increment A | OPEN / Draft / CI green |
| #12 | `feat/spine-spike-v2` | Spine technical spike | OPEN / Draft / CI green |

## 当前推进

| 主题 | 分支 | 基线 | 状态 |
| --- | --- | --- | --- |
| Voice mapping public research | `feat/voice-mapping-v2` | `bada0b3` | 本地实现、实时只读证据和行为测试完成，待 Draft PR |

本主题只增强 story voice_map 的范围审计和字段证据，不接 Poke，不读取真实账号，不下载音频，不声称获得资源授权。

## 依赖与暂缓

- Raid Increment B/C 等待 Raid A 的接口语义进入可复用基线，不能把未合并分支当作当前 main。
- Character Data V2 后续字段等待 registry A 的独立变更合并或明确依赖处理。
- Voice QQ 实际播放、Daily 写入、真实 Profile 和 Spine production runtime 仍需要现场/人工证据。

