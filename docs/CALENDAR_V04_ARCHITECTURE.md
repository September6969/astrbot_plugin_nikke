# NIKKE Calendar v0.4 架构设计与运行时合同

## 1. 概述与核心原则

NIKKE 插件 Calendar v0.4 引入了独立的结构化活动日程层，彻底解决以往 `/妮姬 日程` 单纯依赖官方公告正文解析活动时间导致的准确度与覆盖度不足问题。

### 核心分层原则
> **InformationFeeds 管“官方说了什么”，Calendar/GameKee 管“活动什么时候开始和结束”；结构化源挂了就保留旧快照，再不行才退回公告正文解析，任何时候都不能因为辅助源失败把原有日程功能拖死。**

1. **彻底分层**:
   - `InformationFeedsSource` 继续作为官方公告标题、正文、发布时间、版本、官方链接的绝对权威来源。
   - `GameKeeNikkeScheduleSource` 仅作为辅助的结构化活动时间与元数据来源（开始时间、结束时间、分类、banner 图、重要度等）。
   - GameKee 数据**绝对不写回或污染 `AnnouncementRecord`**。
2. **渐进降级 (Graceful Degradation)**:
   - 优先使用 GameKee 结构化日程并持久化本地快照；
   - GameKee 同步失败但本地已有快照：继续使用旧快照展示并输出黄色告警（`⚠️ 日程数据同步失败：...，以下为本地缓存。`）；
   - GameKee 失败且本地无快照：无缝回退到 `AnnouncementService + DeadlineParser` 路径，并明确提示降级；
   - 任何上游异常绝不清空、覆盖或损坏现有缓存。
3. **两层防线阻止未开始活动触发截止提醒**:
   - 第一层：`CalendarService.list_reminder_deadlines()` 只返回当前处于 `active` (`start_at <= now <= end_at`) 的活动；
   - 第二层：`AnnouncementDelivery.plan()` 增加防御检查 `start_at <= now`，即便未来有上游逻辑误传 `upcoming` 活动，也不会提前计算其结束提醒。

---

## 2. 整体数据流与组件关系

```text
       +---------------------------------------------+
       |   Official Announcement (InformationFeeds)   |
       +---------------------------------------------+
                              |
                              v
                   [ AnnouncementRecord ]
                              |
               +--------------+--------------+
               |                             |
               v                             v
         /妮姬 公告                     DeadlineParser
                                             |
                                             | (Fallback only)
                                             v
+------------------------+        +---------------------+
| GameKee Activity API   |        | AnnouncementService |
+------------------------+        +---------------------+
            |                                |
            v                                |
   [ CalendarActivity ]                      |
            |                                |
            v                                |
    CalendarService                          |
  (Local Atomic Cache)                       |
            |                                |
            +------------+                   |
            |            |                   |
            v            v                   v
     /妮姬 日程     Reminder Deadlines -> AnnouncementDelivery
```

---

## 3. 核心组件规范

### 3.1 `CalendarActivity` (`calendar_models.py`)
- `@dataclass(slots=True)`
- 内部所有 datetime 强制规范化为 **timezone-aware UTC**，彻底拒绝 naive datetime；
- 强类型校验：`importance` 与 `version` 严格要求原生 `int`，显式拒绝 `bool`（因 `bool` 为 `int` 子类）与 `float`；
- 时间窗口强校验：`end_at > start_at`；
- 接口兼容性：提供 `name` 与 `deadline_version` 属性，与 `AnnouncementDelivery` 的 deadline 协议完全兼容；
- 状态判定互斥：
  - `is_active(now)`: `start_at <= now <= end_at`
  - `is_upcoming(now)`: `now < start_at`
  - `is_ended(now)`: `now > end_at`
- 规范化指纹：基于 `title`, `start_at`, `end_at`, `category`, `source_id`, `banner_url` 等字段计算稳定 SHA-256，仅在指纹发生实质变更时递增 `version`。

### 3.2 `GameKeeNikkeScheduleSource` (`calendar_sources.py`)
- 固定请求合同：
  - URL: `https://www.gamekee.com/v1/activity/page-list`
  - Headers: `game-alias: nikke`
  - Params: `importance=0, sort=-1, keyword="", limit=999, page_no=1, serverId=19, status=0`
- 强隔离与隐私安全：请求中绝对不传递任何 QQ 号、OpenID、UID、Cookie 或 Token；
- 容错解析：支持单个畸变行（缺失字段、时间倒置等）跳过，并在 `last_scan` 记录 `rows/valid/malformed/duplicates`；
- **Schema Drift 保护**：若上游返回非空列表，但有效解析条数为 0，必须抛出 `ValueError`，阻止非法空数据冲掉本地快照。

### 3.3 `CalendarService` (`calendar_service.py`)
- 缓存管理：
  - 路径：`data/nikke/calendar/calendar_cache.json`；
  - 原子写入：先写临时文件 `.tmp`，flush + fsync 后原子替换目标文件；
  - 损坏自愈：若本地缓存损坏，记录安全警告，维持 `_has_snapshot=False`，绝不阻塞插件启动。
- 查询视窗与分组互斥：
  - 支持 `7`、`14`、`30` 天 horizon 过滤，默认 `14` 天；
  - 拒绝其他无效参数并返回标准帮助说明；
  - 输出严格互斥的三大分组：
    1. 【即将结束】：`is_active` 且 `end_at - now <= 24h`；
    2. 【进行中】：`is_active` 且 `end_at - now > 24h`；
    3. 【即将开始】：`is_upcoming` 且 `now < start_at <= now + horizon`。

---

## 4. 指令合同与展示格式

### 指令
- `/妮姬 日程`（默认 14 天）
- `/妮姬 日程 7`
- `/妮姬 日程 14`
- `/妮姬 日程 30`
- 英文别名支持：`/nikke schedule [7|14|30]`
- 管理员指令兼容：`/nikke schedule HH:MM`（若包含冒号且为管理员，仍优先进入日常任务时间设置，互不干扰）。

### 正常输出示例
```text
【NIKKE 近期日程 · 未来 14 天】
（最近更新时间: 2026-09-13 13:00:00）

【即将结束】
• [协同] 协同作战：神罚
  09/12 12:00 → 09/13 12:00 · 剩余 3小时 20分钟

【进行中】
• [招募] 特殊招募：新角色
  09/05 04:00 → 09/19 04:59 · 剩余 5天 18小时

【即将开始】
• [单人突袭] 单人突袭 第18期
  09/18 12:00 → 09/25 04:59 · 距开始 4天 22小时
```

### 降级输出示例
当 GameKee 同步失败且本地无快照时：
```text
⚠️ 结构化日程不可用，已降级使用官方公告时间解析。
（结构化源错误: 连接超时）

【NIKKE 近期日程与活动倒计时】
...
```

---

## 5. 故障恢复与安全矩阵

| 场景 | Calendar 状态 | 用户响应 | 缓存影响 |
| :--- | :--- | :--- | :--- |
| **GameKee 正常拉取** | 刷新内存快照与版本 | 正常显示最新结构化日程 | 原子写入新快照 |
| **GameKee 网络/超时失败（有旧快照）** | 保留旧快照 | 显示旧快照，顶部附带黄色告警提示 | 旧快照保持不变 |
| **GameKee 接口数据格式漂移（非空全坏）** | 判定 schema drift 失败 | 触发失败保护，不覆盖旧快照 | 旧快照保持不变 |
| **GameKee 失败（无本地快照）** | `_has_snapshot=False` | 降级调用 `AnnouncementService` 文本 | 无缓存产生 |
| **未来活动传给投递器** | 双重防线拦截 | 绝不提前触发截止推送 | 无非法推送产生 |
| **非法查询范围参数** | 校验拦截 | 返回用法说明，绝不发起上游网络请求 | 无影响 |
