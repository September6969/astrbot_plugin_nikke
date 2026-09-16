# NIKKE 最终发布检查清单

## 当前代码状态

- [x] `origin/main` 在本主题开始前已核验为 `2f969756b18ad7e28c41564b07ba0aa60b0dc59d`。
- [x] 依赖顺序的 PR #52 → #53 → #54 → #55 已通过各自 required checks 后合并；工作分支均保留，不删除历史。
- [x] `gh pr list --state open` 当前为空；没有待合并 PR。
- [x] 直接修改 main、force push、自动部署、ruleset 修改和分支删除均未执行。

## 离线验收门槛

- [x] Python 定向行为测试、完整 pytest、`python -m compileall -q .`、Node extension tests 和 `git diff --check` 已执行；CI 负责 Python 3.10–3.13、Node 与 Spine Docker 构建。
- [x] 角色卡、Profile、Guide、Registry、Voice、Spine fallback 和既有模块的合成/fixture 证据均明确标注为离线证据。
- [x] 四类资源 registry 只按精确 ID 和 manifest/hash 合同工作；未知或损坏输入使用中性 fallback，不猜测相邻资源。
- [x] Voice 动态映射清单为空；没有把剧情语音、Alice 或默认服装冒充已确认 Poke 语音。

## `BLOCKED` / `NEEDS_LIVE_EVIDENCE`

| 项目 | 当前状态 | 最小现场动作 |
| --- | --- | --- |
| `ssh serv` 现场 | `BLOCKED`：2026-09-08 复核在 SSH banner 阶段超时，未执行远程写操作 | 恢复 SSH 后只读执行容器、健康入口、版本和日志隐私检查；不读取秘密 |
| Spine Linux worker | `NEEDS_LIVE_EVIDENCE` | 在隔离 Docker/tag 中用合法测试 bundle 编译并记录 runtime、RGBA、冷/热缓存和 benchmark；不修改现有容器 |
| Costume 完整映射 | `NEEDS_LIVE_EVIDENCE` / `NEEDS_HUMAN_DECISION` | 提供 API costume ID、Nikke-DB asset ID、来源响应范围、SHA-256 和授权；否则保持空表 |
| Poke Voice 映射与 Record | `NEEDS_LIVE_EVIDENCE` | 提供一个已核验角色/服装/locale 映射后，使用现有授权 NapCat/AstrBot 环境做最小 Record 序列化/播放检查；不发任意消息 |
| 真实账号与部署 | `NEEDS_HUMAN_DECISION` | 由维护者安排具体测试账号、备份、回滚窗口和目标会话；本仓库不自动登录、写账号、消费 CDK 或部署 |

## 发布前人工确认

1. 复核 `CHANGELOG.md`、`docs/REQUIREMENT_EVIDENCE_MATRIX.md` 和各主题 acceptance 文档的状态没有把 fixture/合成输出写成 live evidence。
2. 在目标环境运行只读 `scripts/upgrade_preflight.py`，确认 `nikke.sqlite3` 与 `secret.key` 成对备份，并由人工保留回滚副本。
3. 通过 Caddy/HTTPS 和 `/healthz` 的现场检查后，再由维护者决定是否启用公告推送、签到、CDK 或 Voice 动态映射。

本清单不包含 Cookie、token、密码、二维码、账号标识或消息内容。
