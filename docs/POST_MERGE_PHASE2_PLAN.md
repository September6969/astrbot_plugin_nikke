# Post-Merge Phase 2 计划

> 本文是 2026-09-06 接手计划的仓库入口和快照，不是实现完成声明。远端合并、CI、工作区和当前能力以 [POST_MERGE_STATUS.md](POST_MERGE_STATUS.md) 为准。

## 目标与顺序

先完成 A，再从最新 `origin/main` 独立开始 B；不等待 A 合并，也不把旧 `feat/overnight-backlog` 当作开发分支。

- **A：Post-Merge Sync**：收口合并后状态入口，只改文档，建立可审 Draft PR。
- **B：Profile V2**：完成 `/妮姬 我的` 从命令、受控请求、字段模型、分区构建到 PNG 预览的闭环。

边界：不修改 `main`，不自动 merge，不 force push，不删除分支，不改 ruleset，不部署，不访问未明确授权的真实账号，不执行账号写操作或消息发送。未接线模块、合成测试和公开资源访问不能被描述为产品完成、真实联调或资源授权。

## A：Post-Merge Sync

分支：`chore/post-merge-sync`，基于开始执行时重新 fetch 得到的最新 `origin/main`。

交付内容：

1. 维护合并后状态、PR #5、CI、已关闭 blocker 和剩余能力的状态页。
2. 将 `DEVELOPMENT_PLAN.md`、`AUTONOMY_REVIEW_REPORT.md`、`EXECUTION_AUTONOMY_PLAN.md` 的当前入口改为合并后事实；历史段落保留原 SHA 并明确其历史性质。
3. 将本阶段计划保存在仓库，区分计划快照和运行时最新状态。
4. 只做文档范围的验证、提交、push 和 base 为 `main` 的 Draft PR；不顺带改变功能、版本、默认写开关、部署、CI 触发器或分支保护。

## B：Profile V2

B 使用独立工作树和分支 `feat/profile-v2`，从最新 `origin/main` 创建，不继承 A 的未合并提交。B 的验收说明放在 `docs/PROFILE_V2_ACCEPTANCE.md`。

### 先确认的真实代码入口

沿现有链路工作，不另造 ProfileService 或孤立 renderer：

`main.py:NikkePlugin.me` → `client.py:get_profile_dashboard` → `profile_models.py` → `profile_builder.py` → `profile_card_renderer.py`。

同时核对 `research_registry.py`、Profile 结构化测试、主题/核心测试和脱敏 fixture 的来源。字段合同只覆盖本次确实展示的字段，合同表至少记录来源响应/字段、含义证据、类型、缺失显示和是否为部分结果。

### 数据与错误语义

- 缺失、解析失败、接口失败、合法 `0`、已知空数组必须保持不同语义。
- `bool`、非有限数、非整数、坏字符串、字典/列表和不允许的负数不能让整卡崩溃，也不能静默转成 `0`。
- basic 已知的角色数/时装数在 roster 不可用时仍可显示；未知最大等级/战力不能冒充 `0`。
- 部分损坏列表保留可靠条目，但摘要必须标记部分或隐藏完整总计；不能过滤坏条目后声称完整。
- 没有分类唯一性或互斥性证据时，不从 `memorial_counts` 推导独立收藏总量。
- 未知研究类型使用中性本地名称，不直接泄露原始标识，也不按数字猜职业/公司/属性。
- 取消和 `CookieExpired` 按既有合同传播或处理；不能用宽泛异常吞掉取消信号。

### 展示与请求预算

目标分区顺序为：`BASIC → CAMPAIGN → OUTPOST → ROSTER → COLLECTION → RESEARCH → MORE`。

- Normal/Hard 主线从已有基本信息中清晰拆出，不为标题新增接口。
- 同一字段只在一个有明确用途的分区出现；不在 OUTPOST、COLLECTION、RESEARCH、MORE 重复占位。
- Research 使用已有 9 类名称和等级；没有公式与输入来源的 stat value 不猜。
- Collection 只展示已证明的计数/条目；Favorite Item、Attractive Level 等未确认字段不冒充已取得。
- 全空分区按一致规则隐藏或显示“未提供”；已知空集合可显示“暂无记录”，不能与请求失败混淆。
- 长昵称、大数字、大量条目要稳定换行/截断，并提示受限条目剩余数量。
- 已有 `area_id` 的合成账号中，basic/outpost/roster 各至多请求一次；不请求每角色 CharacterDetails，不为统计再次拉 roster。renderer 不发网络请求。

### 行为与视觉验收

先写能复现缺陷或验证外部行为的测试，再修实现。至少覆盖：完整资料、可选字段缺失、合法 0 与空数组、outpost/roster 失败、坏数值/坏列表/部分无效条目、未知研究/收藏类别、长内容和请求次数。至少一项测试使用真实 Builder/Renderer，仅在 client 网络边界注入 synthetic 响应；另有 client 层测试验证 endpoint 次数和解析结果，`CharacterDetails` 必须为 0。

生成并实际打开检查三张临时预览：

- `full`：完整 BASIC/CAMPAIGN/OUTPOST、9 类研究和可靠收藏分类；
- `sparse`：只有 basic 可靠字段，其余失败或未知；
- `stress`：长中英文昵称、大数字、多分类和未知类型。

检查默认主题及另一种已有主题的区块顺序、重复字段、占位语义、换行、越界、遮挡、页脚和 PNG 句柄释放。预览和真实账号图不提交源码。

## 交接规则

每个主题的验收记录必须写明：起始 base SHA、工作树/分支/PR、用户可见变化、字段合同、实际接线、测试命令和 exit code、预览路径及实际查看结果、CI run/headSha、证据缺口、未提交文件归属和下一步最小动作。未运行的检查写明原因，不能填入预期结果冒充完成。
