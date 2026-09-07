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
| #11 | `feat/character-data-v2` | Character Data V2 Increment A | OPEN / Draft / latest CI green |
| #12 | `feat/spine-spike-v2` | Spine technical spike | OPEN / Draft / latest CI run `34090288962` green |

## 当前推进

| 主题 | 分支 | 基线 | 状态 |
| --- | --- | --- | --- |
| Spine technical spike | `feat/spine-spike-v2` | `bada0b3` | Draft PR #12；当前 head `0df81a1` 的 CI 已全绿 |

当前增量只覆盖无运行时预检查、证据契约、队列生命周期和总预算截止语义。Spine runtime、许可、Linux headless、真实 render 和 benchmark 仍保持未完成，不因合成测试而提前验收。

## 暂缓项

- Raid canonical identity、真实 Profile、Daily Like/Browse、Voice QQ playback：需要现场证据。
- Spine production runtime/license：需要明确人工许可与产品决策。
- 真实生产 DB migration、ruleset、部署和真实账号写操作：不在本路线自动执行范围内。
