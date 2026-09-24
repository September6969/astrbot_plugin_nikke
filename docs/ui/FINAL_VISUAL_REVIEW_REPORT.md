# FINAL VISUAL REVIEW REPORT

> 历史视觉复核记录：Character 章节针对旧阶段设计。该 1800×1000 Pillow 单角色卡现已退役；当前唯一生产路径是 1600×2400 白色竖版 replica，失败不回退旧版。

本次最终视觉复核已完成。分支 `feat/t2i-campaign-phase1`，HEAD `ebbb18f8c32ca5cf27ba3fb3ceb1255fe6acabb5`。

实现继续保存在未提交工作树；未 commit、push、PR、merge、deploy 或发送 QQ。以开始本轮时的未提交工作为基线，没有覆盖此前功能与资产交付。

## A. Pages reviewed

逐页复核 Campaign、Calendar、Union Overview、Union Records、Union Member、Profile、Character。依据生产 AstrBot 原生 PNG，检查 100% 细节、50% 主要业务阅读、30% 主体/关键数字/状态；没有改成网页响应式布局或另做 demo HTML。

开始时读取交付审计、资产来源与资产交接，核对分支、HEAD、工作树及 diff。原交付的 54 张 PNG 保持原字节；本轮新图独立保存于 `E:\DevCache\nikke-t2i-phase1\preview\t2i-visual-final`。

## B. Visual problems found

| 页面 / 公共部分 | 原图问题 |
|---|---|
| 公共文字与状态 | 英文小标题 tracking 偏宽；状态大多只有同一种中性外框，层级不够明确。 |
| Campaign | LV 与姓名过于接近，顶部强调线略厚。Stage、TOTAL CP、五槽位本身稳定，无须重排。 |
| Calendar | 三组权重相近；UPCOMING 倒计时与 ACTIVE 抢视觉。嵌套 footer 导致重复规则线和额外留白。 |
| Union Overview | Boss 名称换成两到三行后，把部分卡片的状态、HP 和精确数值向下推，行基线不齐。 |
| Union Records | DAMAGE / RETURNED RECORDS 表头左对齐，列值右对齐；当前响应提示缺少稳定视觉锚点。 |
| Union Member | 队员 LV/CP 和头像略小，记录伤害需要更明确地成为每行第一数字。 |
| Profile | 2680px 高度中有较多 section/行留白；资源项节奏松散。 |
| Character | 立绘独立底板与四块装备实底造成明显分块；OL summary 的无聚合 tier 横杠重复占位，底部说明偏重。 |

## C. Visual changes made

- 公共：收敛英文小标题字距；统一页脚字号/基线与细规则线。AVAILABLE 使用克制的灰绿，PARTIAL 使用警告金，UNAVAILABLE 使用低饱和红，UNKNOWN 使用虚线，EMPTY 保留明确文字及中性边框。浅底与 TODAY 深底分别验证状态文字对比度，不覆盖 OL semantic colors。
- Campaign：顶部线 6→4px；LV 降至次级颜色/18px，姓名 22px；长姓名仍使用既有 18px 档。保持 Stage/Mode、五人顺序、所有精确 combat、TOTAL CP 和既有整页回退预算。
- Calendar：只对 Service 已给定的组名应用展示样式；临近结束使用适度警告色，ACTIVE 保持主要权重，UPCOMING 减轻；空组紧凑展示。移除嵌套 footer 与重复 UTC+8，不重新分类、排序或截断事件。
- Overview：名称使用固定 90px 区域、22px 字号与 30px 行高，已知长名称保持完整；五张卡状态/HP 基线一致。减轻面板边线与 HP 字号，保留完整 Boss 图的 contain 展示。
- Records：数字表头与数值右对齐，缩小行内空白；范围提示采用细侧线。rank、排序、tie rank、精确 damage、RETURNED RECORDS 文义不变。
- Member：头像高度 115→124px，姓名 15→17px，LV 15→16px，combat 18→20px，记录伤害 29→34px；收敛行间空白，FINAL HIT 使用克制金色。所有成员、记录与精确数值均保留。
- Profile：section 垂直 padding 25→18px，常规行 padding 9→6px，缩小重复 gap；资源图标 48→52px，资源仍为 4×2。容量百分比 32→36px、进度条保留。完整模型高度减至 2331px，减少 349px（约 13.0%），没有删除字段。
- Character：保持 1800×1000、700×744 人物区、完整人物/武器与独立数据区；移除立绘底板和装备实底，使用细分隔线组织 2×2 装备。CP 56→64px，调整数据区内部高度；每件仍恰好 3 OL。OL summary 隐去无已确认聚合 tier 的横杠，payload 与具体 OL tier 不变。底部次要文字 20→18px，面板标题不再笼统宣称“已确认”。

没有增加卡片套卡片、圆角移动 UI、玻璃、霓虹、厚阴影、运行时框架或外部图片引用。

## D. Files changed

相对于本轮开始的未提交工作，修改已有文件 12 个：

- `templates/t2i/_shared/components.css`
- `templates/t2i/_shared/macros.jinja`
- `templates/t2i/_shared/utilities.css`
- `templates/t2i/campaign.html`
- `templates/t2i/calendar_schedule.html`
- `templates/t2i/union_overview.html`
- `templates/t2i/union_records.html`
- `templates/t2i/union_member.html`
- `templates/t2i/profile.html`
- `templates/t2i/character.html`
- `scripts/preview_t2i_ui.py`
- `scripts/preview_t2i_frontend.py`

预览脚本仅增加逗号分隔 fixture 选择，便于一次使用同一生产堆栈复核多个案例。

新增 `tests/test_t2i_visual_contracts.py`、本报告与 `docs/T2I_VISUAL_REVIEW_AUDIT.json`。其余 **1030 个基线文件逐字节不变**，包括 Client、Builder、Resolver、DTO、AssetManager、资产镜像、Spine manifest、CalendarService、Union ranking 和 presentation adapter。

## E. Screenshots reviewed

新生成 30 组案例，每组含原始 PNG、50%、30%，共 **90 张**。全部通过 PNG 解码、画布/缩略尺寸及最终 HTML 外部资源检查。

| 页面 | 新生成案例 |
|---|---|
| Campaign | normal、hard、long-text、max-density |
| Calendar | normal、stale、long-title、many-events、empty |
| Overview | with-boss-assets、partial-hp、empty |
| Records | normal、long-name、tie-rank、many-members |
| Member | with-portraits、many-records |
| Profile | full-current-model、today-partial、research-long-names、unavailable、long-commander |
| Character | c010、c010_02、c010_03、c330、c471、long-name、missing-art |

人工复核重点：七页代表图的三种比例；Campaign 长名/高密度；Calendar 长标题；Boss 长名称和 HP 对齐；成员精确数字；Profile 完整/Partial；Character 默认/两套皮肤/大武器/长名称。已测样例未发现关键数值截断、人物侵入数据区、武器裁切或破图。没有要求 30% 读清全部 OL、成员名或小型辅助文字。

## F. Before / after notes

| 代表图 | 修改前 | 修改后 | 结果 |
|---|---:|---:|---|
| Campaign normal | 1600×880 | 1600×880 | 保留 Stage 主视觉，姓名与 LV 更明确。 |
| Calendar normal | 1400×1371 | 1400×1247 | 少 124px；分组/时间主次更清楚，消除重复页脚。 |
| Overview | 1600×900 | 1600×900 | 五卡名称区域和 HP 基线统一。 |
| Records normal | 1500×720 | 1500×720 | 行密度更紧凑；原生最小视口高度不变。 |
| Member with portraits | 1500×1896 | 1500×1903 | 头像/文字增大，行间距回收，整体高度近似不变。 |
| Profile full model | 1200×2680 | 1200×2331 | 少 349px，保留全部信息与 TODAY 主地位。 |
| Character c330 | 1800×1000 | 1800×1000 | 完整人物优先，减少 dashboard 分块感。 |

七页代表性 JSON payload 与修改前一致；Overview 的实时 remaining time 单独排除比较。资源身份、金额、战力、装备/OL、队伍、排序和状态语义没有变化。

## G. Remaining visual debt

- 不同原生端点的 CJK 字体/字重仍可能略有差异；保留现有字体回退链，不引入网络字体。
- 超出已测范围的极长未来名称或更多异构文本仍需单独截图验证；没有擅自扩大 Campaign 既有文字/数字上限。
- QQ 最终观感由用户决定何时验证，本次没有实机发送。

以上不是当前实现 blocker。原生服务一次返回不可用图片后，由既有预览重试成功；没有修改生产超时或回退策略。

## H. Test results

- 全量 `python -m pytest -q`：**775 passed，490 subtests passed**。
- 原 T2I 与资产集成定向集合：**57 passed**。
- 新视觉回归：**12 passed**，覆盖组序/长标题保留/单 footer、状态转义、深浅底状态对比度。
- `node --test tests/extension.test.cjs`：**4 passed**。
- `python -m compileall .`：通过。
- `git diff --check`：通过；CalendarService 的既有 LF/autocrlf 提示不属于本轮改动。

测试集合有包含关系，不能相加作全量总数。日志位于 `E:\DevCache\nikke-t2i-phase1\visual-full-tests.log`、`visual-targeted-tests.log`、`visual-extension-tests.log`；完整截图路径/hash 和未修改文件验证见同目录文档 `T2I_VISUAL_REVIEW_AUDIT.json`。

## I. Functional issues intentionally not modified

未发现需要修改业务层的新功能回归。继承边界保持：缺少面板或物品名称时继续显示 Unknown；未覆盖 Spine 继续安全降级；未来 Boss metadata 不补造；原生服务可用性不通过绕开 Star 或修改后端来处理。原资产交接中提到的 Playwright 指引没有覆盖当前已验证的 Star.html_render 架构。

## J. Exact preview paths

最新代表图：

- [Campaign](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/campaign/normal.png)
- [Campaign HARD](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/campaign/hard.png)
- [Calendar](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/calendar_schedule/normal.png)
- [Union Overview](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/union_overview/with-boss-assets.png)
- [Union Records](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/union_records/normal.png)
- [Union Member](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/union_member/with-portraits.png)
- [Profile](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/profile/full-current-model.png)
- [Character 默认](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/character/c010.png)
- [Character 白色皮肤](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/character/c010_02.png)
- [Character 夏日皮肤](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/character/c010_03.png)
- [Character 皇冠](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/character/c330.png)
- [Character 大武器](E:/DevCache/nikke-t2i-phase1/preview/t2i-visual-final/character/c471.png)

各图同目录有 `-50.png`、`-30.png`、生产 HTML 与 JSON。原始对照图仍在 `E:\DevCache\nikke-t2i-phase1\preview\t2i`，未覆盖。至此停止，等待用户查看最终 PNG 后决定下一步。
