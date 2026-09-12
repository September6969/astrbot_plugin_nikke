# Campaign 全量抓包与静态快照实现记录

## 范围与状态

抓取工具以 `assets/campaign_stages.json` 为唯一关卡来源，只处理 `NORMAL` 和 `HARD`，排除 Story/EX。所有 stage ID 来自已验证静态表，不通过章节公式生成。工具是只读维护动作，最终真实快照只放服务器，不提交 Git。

## 请求与复用

`scripts/capture_campaign_history.py` 复用现有 `BlaBlaClient.get_main_quest_clear_lineup()`、现有账号 session 和 `CampaignHistoryBuilder`，不复制 HTTP client，不执行 Daily、CDK、Signin、绑定变更或其它写操作。

## Snapshot schema

每行保存 mode、chapter、stage_name、stage_id、captured_at、API code、脱敏 safe message、status、响应 schema、member count。`AVAILABLE` 只保存 slot、tid、lv、combat，以及 API 明确提供的 costume_id；不保存请求 header、Cookie、Token、OpenID、Authorization、QQ ID 或账号身份。

状态在 JSON 中使用 `available`、`unavailable`、`rate_limited`、`error`、`malformed`（文档语义对应 `AVAILABLE`、`UNAVAILABLE`、`RATE_LIMITED`、`ERROR`、`MALFORMED`）。既有合同 `1300017 → UNAVAILABLE`、`212000/HTTP 429 → RATE_LIMITED` 不混同为普通失败。

## Resume、过滤与限流

默认单线程；`--resume` 跳过已有完成 stage，`--force` 重抓；支持 `--mode NORMAL|HARD` 与 `--chapter N` 局部运行。请求间使用 0.8–1.5 秒 jitter；限流按 5/10/20/40 秒退避，达到阈值先落盘进度再停止。正式运行前输出 NORMAL、HARD、TOTAL 数量和最低耗时估算；推荐顺序为 NORMAL chapter 1 smoke、NORMAL 全量、HARD 全量，不并发两种模式。

## Output 与隐私

服务器目录为 `/opt/nikke-bot/astrbot/data/nikke/campaign-capture`（容器内 `/AstrBot/data/nikke/campaign-capture`），包含 manifest、NORMAL/HARD JSONL、TID inventory 与 Costume inventory。manifest 记录 stage 文件 SHA-256、插件 Git SHA、开始/完成时间、计数和非敏感 area 信息；若 stage 文件 hash 改变，标记 `SNAPSHOT_OUTDATED`。真实完整 response 永不写入仓库。

抓取过程中使用 `CharacterMasterResolver` 建立 Battle TID inventory：raw tid、normalized prefix、occurrence、resolved character、resource_id、spine_asset_id、首末关卡。未知 TID 保持 unresolved，不按名称、相邻 ID 或顺序猜测。Costume inventory 只收录响应明确出现的 costume_id 及 tid+costume_id pair，不从 TID 推断服装。

## Regression usage

抓取完成后从 snapshot 随机抽取至少 10 个 NORMAL 与 10 个 HARD，使用 `CampaignHistoryBuilder → CharacterMasterResolver → static Spine portrait → CampaignHistoryRenderer` 离线回放。检查 stage、5 个 slot、中文名、总战力求和及无 `NIKKE <tid>`/灰色 silhouette；回放不再请求真实 API。缺少现场账号或响应时，工具和 fixture 仍可完成合同测试，但报告必须保留 `NEEDS_LIVE_EVIDENCE`/`PARTIAL` 边界。
