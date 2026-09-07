# NIKKE 路线图台账

最后核验：2026-09-06（本次续跑重新 `git fetch origin --prune`、核对 PR、CI 与工作树）。本台账只记录本分支检查点的当前事实；路线图文档是启动提示，不替代实时核验。

## 远端与 PR

| 项目 | 已核验状态 |
| --- | --- |
| `origin/main` | `bada0b3aafcd7127d07ca40f554808b0433540f8`，PR #7 合并提交 |
| PR #5 | MERGED，旧 `feat/overnight-backlog` 仅为历史恢复点 |
| PR #6 | MERGED，Post-Merge Sync |
| PR #7 | MERGED，Profile V2 |
| PR #8 | OPEN / Draft，`feat/union-raid-v2@d98cce4c8b898e1ba3aeca3d4234ea2d780cb803`；CI `34083806757` 全绿 |
| PR #9 | OPEN / Draft，`feat/announcement-v2@47fd311490e7fd607f5144738e2822f3c97e17e9`；CI `34086582482` 全绿 |
| PR #10 | OPEN / Draft，`feat/dynamic-voice-v2@265ad13b182e59710a684b05f4fae39a5b83763d`；CI `34088210654` 的 Node 与 Python 3.10/3.11/3.12 均 SUCCESS |

## 当前独立主题：Dynamic Voice V2 Increment A

| 项目 | 状态 |
| --- | --- |
| 分支 / base | `feat/dynamic-voice-v2`，从最新 `origin/main@bada0b3` 独立创建；未继承 PR #8/#9 |
| 工作树 | `E:/DevCache/nikke-dynamic-voice-v2/astrbot_plugin_nikke` |
| 代码 | 缓存内容与 manifest 分离原子落盘；未知角色不再静默回退 Alice |
| 合同 / 验收 | [Dynamic Voice V2 合同](DYNAMIC_VOICE_V2_CONTRACT.md)；[验收记录](DYNAMIC_VOICE_V2_ACCEPTANCE.md) |
| 本地验证 | 定向 Python `8 passed`；full suite 与最终 head CI 待本轮后续完成 |
| PR / CI | [PR #10](https://github.com/September6969/astrbot_plugin_nikke/pull/10) 为 Draft；实现 head `265ad13` 对应 CI `34088210654` 全绿。本次台账更新会产生新的 docs-only head，必须对新 SHA 单独核验 |
| 证据边界 | 无真实账号、无真实消息、无动态资源授权；公开角色/皮肤互动映射仍需现场证据 |

## 后续选择规则

PR #8、#9 与本主题保持独立。不得把等待审阅、缺少 live evidence 或本地合成测试写成产品完成。Raid B 仍需 PR #8 合并后从当时最新 main 独立创建；Raid C、真实 Voice 播放与资源授权继续标记 NEEDS_LIVE_EVIDENCE / NEEDS_HUMAN_DECISION。

## 本检查点后

完成本主题的 full suite、最终 head CI 与 Draft PR 记录后，下一独立主题应重新读取路线图并实时核验依赖；不自动选择或启动依赖 PR #8 合并的工作。
