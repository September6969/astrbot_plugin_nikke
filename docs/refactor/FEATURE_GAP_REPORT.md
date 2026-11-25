# FEATURE_GAP_REPORT.md — 业务缺口、合规审查与技术风险报告

> **审计基线**：`origin/main` (`71e664f`，含 PR #141 & PR #142) + 本地提交 `9968a50`  
> **修订说明（2026-11-24）**：按 Phase 0 审阅结论，将数据许可合规前置至 PR-1A，将 ShiftyPad 会话安全与养成历史跨账号污染提升为 **P0**，并明确三套订阅统一治理与九宫格单一套 T2I 规范要求。

---

## 一、P0 阻断级问题（Phase 1A / 1B / 1C 必须解决）

### GAP-01（P0 合规）：无开源许可的 NikkeHub 抓取数据禁止推送至公开仓库
- **证据**：本地提交 `9968a50` 将 `counsel_bank.json`（24,611 行）、`sync-level-costs.json`（4,809 行）、`overload_recommendations.json`（146 行）、`solo_raid_seasons.json`（含 NikkeHub 抓取数据）直接放入 `assets/data/`。NikkeHub 网站本身无开源许可；补充 `NOTICE` 或来源署名**不等于取得分发授权**。
- **处置**：禁止先推至公开仓再删除。保留 `9968a50` 本地备份不丢失，从合规基线重构提交序列：仅随仓保留 MIT 授权产物 `assets/data/solo_raid_engine_names.json`（`Jgaram/nikke-calc@67835ca`）与 `LICENSE-nikke-calc.txt`，上述 4 份无许可数据全部不进入公开仓库；运行时保持严格导入格式与缺失安全降级。

### GAP-02（P0 安全）：ShiftyPad 只读会话安全漏洞与上游契约未实测
- **上游阻塞**：`features/shiftypad/fetcher.py:24` 标明 `CONTRACT = "official_public_profile_unverified_2026-11-23"`，无鉴权请求 `api.blablalink.com/.../User/GetUserProfile` 尚未经授权测试账号实测确认。
- **Web 会话安全漏洞（`integrations/web/shiftypad_service.py`）**：
  1. 令牌未作一次性消费，绑定成功后仍可在 600s 内反复调用 bind/sync/unbind（L242-245）；
  2. 令牌暴露于 `/shiftypad/{token}` 与 `GET /api/shiftypad/state?token=...` 查询串（易进反代日志与浏览器历史，L103, L310, L380）；
  3. 响应 CSP 缺少 `frame-ancestors 'none'`（L321）且使用 `'unsafe-inline'`；
  4. 本身无独立 Origin/CSRF 校验，隐式依赖 `BindingWebService.security_middleware`；`MAX_BODY = 16KB` 未使用（L34）；
  5. `storage.py:116` 将 `stale` 快照标为 `can_sync=False`（与 `sync()` 恢复用途矛盾）；换绑不同 `openid` 未重置 `bound_at`/`sync_count`；`identity.py:63` 误调 `unquote`。
- **第三方代理开关缺失**：`integrations/nikke_api/share_profile.py` 向 `nikke-api.pages.dev` 转发用户分享 ID 缺少默认关闭的管理员开关与数据外传告知。

### GAP-03（P0 数据隔离）：养成历史跨账号混染、清库不彻底与并发回写
- **身份混染**（`features/growth/history.py:164-168, 398-402`）：仅按 `actor_id` 建键，未绑定稳定游戏身份 `(actor_id, game_identity)`；用户未解绑直接换绑另一账号会混合数据并算出错误差值。
- **清空遗漏与并发回写**（`toolbox.py:806-808`）：`/妮姬 养成历史 清空` 漏删 `roster_growth`，且缺少清除代次/时间戳防护，正在飞行中的并发查询结束后可能把清理前的旧快照重新写回。
- **语义失真**（`history.py:405-407, 483-485`）：`RosterGrowthHistory` 将 `None`/`""` 转为 `0` 并触发假 `0 → N` 差异，且同日二次查询覆写清空当日 `changes`。

### GAP-04（P0 外部引擎安全与突袭计算错误）：`nikke-calc` 与单人突袭
- **Boss 弱点写反**（`features/solo_raid/builder.py:173-176`）：`_boss_weakness_element()` 返回 `boss.element` 而非 `boss.weakness`，导致克制配队优先级完全相反。
- **并发信号量失效**（`integrations/nikke_calc/engine.py:228`）：`asyncio.Semaphore(self.concurrency)` 在 `estimate()` 内部每次新建，跨用户请求无法限制并发进程数。
- **环境变量密钥泄漏**（`engine.py:171`）：`env = {**os.environ, ...}` 将宿主所有敏感环境变量（含 `NIKKE_ENCRYPTION_KEY`、代理凭据等）透传给外部第三方脚本。
- **版本校验假阳性与失控进程**（`engine.py:190, 216-239`）：无独立 `git rev-parse HEAD` / `git status --porcelain` 校验，且缺失 `evaluator.commit` 时静默回填 `PINNED_COMMIT` 造成 `version_ok=True` 假象；超时未回收进程组且缺总预算与输出大小限制；漏查 `resource_id`（L141-145）；硬编码 `"未提供赛季 43 防御/HP"`（L242）；`ui/payloads/solo_raid.py:63-65` 与 `toolbox.py:549,570` 写死 `"配置化估算"` 覆盖真实引擎标签。

### GAP-05（P0 游戏规则错误）：愿望单推荐违背 NIKKE 基础规则
- **证据**（`features/wishlist/advisor.py:25, 126-134, 179-330`）：按爆裂分组而非按**企业（极乐净土/米西利斯/泰特拉/朝圣·超标准）**；纳入不能入愿望单的 **SR/R** 角色；160 墙（L232）把 3 星 SR 误计入 `"X/5 名 3 星 SSR"`；`BURST_ORDER` 查找键写错（`Step1` vs `B1`）；手工输入（L222）不支持别名；缺少经核验的普通池与特殊卡池准入规则。

### GAP-06（P0 可用性）：咨询答案查询中文 0 命中
- **证据**：`9968a50` 抓取的 794 条索引全部为韩文关键词（**中文 = 0 条**）、无题干与选项内容，中文玩家输入中文关键词 0 命中，且来源无分发授权。需保持停用默认内置韩文表，明确标注 `BLOCKED`，继续调查合法中文题库并保留导入与精确/模糊检索能力。

### GAP-07（P0 渲染与双布局违规）：本命九宫格
- **双布局违背统一规范**：同时存在 `templates/t2i/favorite_grid.html` 与独立 `ui/renderers/favorite_grid_png.py`。
- **实际渲染缺陷**：Pillow 回退（`favorite_grid_png.py:21-26, 60-71, 86-98, 120`）标题与第 1 格重叠、头像未裁剪溢出邻格、Linux 字体优先 `DejaVuSans` 导致中文全成 `□□□`、缓存无上限；T2I 模板（`favorite_grid.html`）在 `1080×1080` 画布下总高度溢出导致底行被裁切；排行榜（`grid.py:201-207`）存在 N+1 读库。

---

## 二、P1 业务、订阅统一与架构缺口

### GAP-08（P1）：三套订阅机制分散与卡池板计数 Bug
- `features/announcement/feeds.py` 新增 `feed_subscriptions_v1`，与既有 `CalendarSubscriptions`（活动截止提醒）和 `AnnouncementDelivery`（管理员公告订阅）共存，存在投递状态、去重键、配置开关与调度入口不统一问题（`scheduler.py` 无条件运行 `dispatch_feeds`；`feeds.py` 重订阅时某源异常会丢失 baseline 致重复推送，`reminder_hours: [24]` 写入未使用）。
- `features/calendar/board.py:223-225`：按组过滤时将其他有效事件误计入 `unclassified`。

### GAP-09（P1）：超限模拟与建议未反映真实游戏机制
- `features/overload_advice/advisor.py` 未累计跨 4 个部位的已有目标行数、低阶词条盲目建议锁定、模拟每次仅重洗 1 条而非同件全部未锁词条、未反映蓝石头消耗（`1 + locked_count`）与真实出现概率边界、生产代码固定 `seed=0`，且未接入个人实际装备数据对比。

### GAP-10（P1）：同步器等级边界与前哨/箱子引导
- 缺失 1–200 级数据、缺前哨产速/资源箱输入与“当前库存可升等级”，不得使用未证实公式外推未知等级成本，需明确提示并保留手工补录入口；更新脚本需增加往返 Schema 校验。

### GAP-11（P1）：架构整合冲突与代码职责边界
- `9968a50` 将 10 项工具堆入 863 行的 `application/commands/toolbox.py`，且未含 `3d33f2f`（`_legacy` 多词修复）与 PR #142（8 类帮助导航 V2）。
- `scripts/audit/architecture_metrics.py` 需排除 `output/`，避免本地 `output/nikke-calc/` 污染架构扫描。
