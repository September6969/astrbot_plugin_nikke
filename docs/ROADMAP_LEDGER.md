# NIKKE 路线图台账

最后核验：2026-09-06（重新 fetch origin、核对 PR、CI 与工作树）。本台账记录本分支检查点的当前事实；路线图文档是启动提示，不替代实时核验。

## 远端与 PR

| 项目 | 已核验状态 |
| --- | --- |
| `origin/main` | `bada0b3aafcd7127d07ca40f554808b0433540f8`，PR #7 合并提交 |
| PR #5 | MERGED，旧 `feat/overnight-backlog` 仅为历史恢复点 |
| PR #6 | MERGED，Post-Merge Sync |
| PR #7 | MERGED，Profile V2 |
| PR #8 | OPEN / Draft，`feat/union-raid-v2@d98cce4c8b898e1ba3aeca3d4234ea2d780cb803`；CI `34083806757` 全绿 |
| PR #9 | OPEN / Draft，`feat/announcement-v2@47fd311490e7fd607f5144738e2822f3c97e17e9`；CI `34086582482` 全绿 |
| PR #10 | OPEN / Draft，`feat/dynamic-voice-v2@162d9d74812622a506bbd48d19b35b8f20eca638`；CI `34088342539` 全绿 |

## 当前独立主题：Character Data V2 Increment A

| 项目 | 状态 |
| --- | --- |
| 分支 / base | `feat/character-data-v2`，从最新 `origin/main@bada0b3` 独立创建；未继承 PR #8/#9/#10 |
| 工作树 | `E:/DevCache/nikke-character-data-v2/astrbot_plugin_nikke` |
| 代码 | 三类静态映射纳入 `StaticDataRegistry`，含来源 metadata、SHA-256、严格 parser 与未知 fallback |
| 合同 / 验收 | [Character Data V2 合同](CHARACTER_DATA_V2_CONTRACT.md)；[验收记录](CHARACTER_DATA_V2_ACCEPTANCE.md) |
| 本地验证 | 定向测试 `23 passed`；全量 Python `260 passed, 2 warnings, 43 subtests passed`，Node `3 passed`，compileall/diff-check 通过；合成预览已生成并实际查看 |
| PR / CI | 尚未创建；完成全量验证和预览后创建 Draft PR，不自动合并 |
| 证据边界 | 不访问真实账号，不推导角色属性/技能/OL/Costume，不宣称远程素材授权 |

## 后续选择规则

PR #8/#9/#10 与本主题保持独立。Raid B 仍等 PR #8 合并后从当时最新 main 创建；Voice QQ 播放和 Spine 生产 runtime 仍分别需要现场证据与人工许可。不得把本地静态 registry、合成预览或绿色测试写成完整产品完成。

## 本检查点后

完成本主题的全量测试、合成预览、Draft PR、最终 head CI 与索引更新后，再从路线图选择下一个不依赖未合并 PR 的主题。
