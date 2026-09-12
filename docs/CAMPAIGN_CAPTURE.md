# Campaign 全量抓包与静态快照实现记录

## 范围与状态

抓取工具以 `assets/campaign_stages.json` 为唯一关卡来源，只处理 `NORMAL` 和 `HARD`，排除 Story/EX。所有 stage ID 来自已验证静态表，不通过章节公式生成。工具是只读维护动作，最终真实快照只放服务器，不提交 Git。

## 请求与复用

`scripts/capture_campaign_history.py` 复用现有 `BlaBlaClient.get_main_quest_clear_lineup()`、现有账号 session 和 `CampaignHistoryBuilder`，不复制 HTTP client，不执行 Daily、CDK、Signin、绑定变更或其它写操作。

## Snapshot schema

每行保存 mode、chapter、stage_name、stage_id、captured_at、API code、脱敏 safe message、status、响应 schema、member count。`AVAILABLE` 只保存 slot、tid、lv、combat，以及 API 明确提供的 costume_id；不保存请求 header、Cookie、Token、OpenID、Authorization、QQ ID 或账号身份。

状态在 JSON 中使用 `available`、`unavailable`、`rate_limited`、`error`、`malformed`（文档语义对应 `AVAILABLE`、`UNAVAILABLE`、`RATE_LIMITED`、`ERROR`、`MALFORMED`）。既有合同 `1300017 → UNAVAILABLE`、`212000/HTTP 429 → RATE_LIMITED` 不混同为普通失败。

## Resume、过滤与限流

正式现场抓取使用最多 3 路的有界只读并发，快照仍由单写入器按批次原子落盘；`--resume` 跳过已有完成 stage，`--force` 重抓；支持 `--mode NORMAL|HARD` 与 `--chapter N` 局部运行。请求间使用 0.8–1.5 秒 jitter；限流按 5/10/20/40 秒退避，达到阈值先落盘进度再停止，并将后续续跑降为单并发。正式运行前输出 NORMAL、HARD、TOTAL 数量和最低耗时估算；顺序固定为 NORMAL chapter 1 smoke、NORMAL 全量、HARD 全量，不同时抓取两种模式。

## Output 与隐私

服务器目录为 `/opt/nikke-bot/astrbot/data/nikke/campaign-capture`（容器内 `/AstrBot/data/nikke/campaign-capture`），包含 manifest、NORMAL/HARD JSONL、TID inventory 与 Costume inventory。manifest 记录 stage 文件 SHA-256、插件 Git SHA、开始/完成时间、计数和非敏感 area 信息；若 stage 文件 hash 改变，标记 `SNAPSHOT_OUTDATED`。真实完整 response 永不写入仓库。

抓取过程中使用 `CharacterMasterResolver` 建立 Battle TID inventory：raw tid、normalized prefix、occurrence、resolved character、resource_id、spine_asset_id、首末关卡。未知 TID 保持 unresolved，不按名称、相邻 ID 或顺序猜测。Costume inventory 只收录响应明确出现的 costume_id 及 tid+costume_id pair，不从 TID 推断服装。

## Regression usage

2026-09-12 的授权只读现场抓取已覆盖 NORMAL 1785/1785、HARD 1787/1787：最终 2699 `AVAILABLE`、873 `UNAVAILABLE`、0 `RATE_LIMITED`、0 `ERROR`、0 `MALFORMED`，`stopped_reason` 为空。首轮 3 并发产生的 4 个可重试错误已由单并发 `--resume` 全部清零；全程未观察到限流。71 个 unique raw battle TID、33 个 normalized prefix 均解析成功；API 响应没有明确提供 costume_id，因此 Costume inventory 为 0，不从 TID 猜测服装。完整快照只保留在服务器持久化目录。

完成后使用固定随机种子从 snapshot 抽取 10 个 NORMAL 与 10 个 HARD，经 `CampaignHistoryBuilder → CharacterMasterResolver → static Spine portrait → CampaignHistoryRenderer` 离线回放。20/20 均满足 5 个 slot、正式中文名、本地 manifest 立绘和总战力求和；接触表已实际查看，无 `NIKKE <tid>`、灰色 silhouette、空图或明显裁切异常。回放不再请求真实 API，仍不代表真实 QQ 客户端送达。
