# Astra UI v0.3 交接与自审报告

## 基线、范围与证据边界

- 执行时 origin/main 等于已接受后端提交 `1047984db31d31d91f66bc14343852fca530fb05`，从该最新 main 建立 `feat/ui-polish-v0.3`。
- 仅 UI 迭代；未部署、未合并、未修改主分支，未执行真实账号、签到或 QQ/Record 操作。
- 人物图来自已有 c010 / c010_03 idle PNG 缓存，仅只读复制。其他输入全部为合成展示 fixture，**不是角色真实养成、现场属性或新 runtime 验收证据**。
- 两张缓存图的 SHA-256：
  - c010：`e97628b1f676c363afc9f802f0917f581feefb4c9842027dc1ef70654f33ca74`
  - c010_03：`d5e534cea40fe78db7da9d25312886afc752ee6df83f5eceba6472e81853c0b5`
- 基线复现脚本通过 git show 读取已接受提交的展示模块，同一 fixture、同一 Python/Pillow 环境比较，不覆盖工作树。

## UI AUDIT

见 [初始审计](E:/DevCache/nikke-ui-polish-v0.3/docs/UI_AUDIT_V03.md)，覆盖 9 个主展示面和 6 类状态。
主要问题：人物下部遮挡、OL 数值栏过窄、Roster 名称重叠及页脚覆盖末行、各卡配色割裂、绑定页面正文回显秘密链接、扩展缺少独立标签和处理反馈。

## DESIGN SYSTEM

- 共享 `UI_COLORS`：画布 #111318、面板 #1A1E25、抬高面板 #222731、分隔线 #343B46、正文 #F2F3F5、辅助 #A9B2C0、琥珀 #E9B85A。
- 成功 #8FBCA2、警告 #E9B85A、失败 #E3A1A1、未知 #A9B2C0；文字状态始终保留，不只依赖颜色。
- Noto Sans Hans Regular/Medium；参考字号 18/21/24/28/32/40/54/68，网页使用系统字体。原有紧凑字段并非全部强制迁移到参考尺度。
- 间距尺度 8/16/24/32/40；面板圆角参考 12px，现有部分卡保留 14px；1px 边框，关键分隔线 3px。
- T1–T15 徽章保留现有分级，只调字号和留白，不改 tier 推导；未知与空槽为中性。
- 有界字体复用（128 项），不缓存玩家信息，不改资源并发或请求预算。
- 前端设计 skill 仅用于层级、间距与克制装饰；没有套营销页布局，也没有引入框架或远端装饰。

## CHARACTER PROGRESS CHANGES

- 仍为 1800×1000；去掉重复英文大字、条码、同心圈和覆盖人物的底部图标。
- 仅裁透明边缘，以 contain 比例完整显示轮廓，宽高异常图居中；不改姿态、animation、时间点、资源地址或 fallback。
- 企业文字移至页眉，企业/属性/武器/爆裂图标移出人物区域；英文副标题给图标留出安全宽度。
- HP/ATK/DEF 字号 28→32；数值、缺失语义和公式完全不变。
- OL 数值栏 78→110px，正文 19→26px，徽章 16→23px；四位置各三行，未装备也有三空槽且不读残留词条。
- 实际采用数值栏重分配而非扩宽整个装备列，避免挤占人物和已稳定的养成区域。
- 第一轮后实际检查并再次修订：英文/图标留白、三值字号、未知中性色、OL 字号、极宽轮廓垂直居中。
- 默认和非默认 c010_03 均查看过原尺寸与缩略图；未把普通卡切回 FB。

## PROFILE CHANGES

共享石墨面板、琥珀强调和更高对比辅助文字。字段所有权、分区内容、缺失语义和原分区顺序不变。
曾尝试把进度移前，既有顺序回归测试指出不兼容后已撤回该尝试，而非改测试掩盖回归。

## ROSTER CHANGES

由逐角色大面板改成名称/等级/战力/技能/突破核心五列表格、斑马行。保留原排序和最多20名，名称仅来自既有正式名称映射。
长名称按实际字宽处理；表格末行和页脚互不覆盖，12名示例高度由1785降至1336。

## CAMPAIGN CHANGES

统一主题，困难模式不再整片红色，HARD/NORMAL 文字区分保留。头部划定标题与总战力宽度；增大槽位、等级和战力字号，长标题及页脚有宽度约束。
五位置、同卡资源复用、resolver、记录状态和说明原文不变。预览使用几何 fallback，不冒充已加载真实阵容资源。

## RAID CHANGES

统一画布、面板和文字；当前/击破/未知颜色使用共享状态令牌，范围说明对比提高。
CURRENT_RESPONSE 的“非完整赛季”说明、HP 和进度计算、已有状态、记录顺序全部保留；未新增排名、主观评分或扩大范围。

## SUMMARY CHANGES

标题与副标题分行，正文以像素宽度换行并完整保留，修正页脚高度计算。二分查找换行点，避免逐字反复测量整段。
仅对明确的“成功：/待处理：/不可用：/失败：/UNKNOWN_AFTER_ACTION”前缀作颜色强调，原文不重写，UNKNOWN_AFTER_ACTION 不变成可重试失败。
**接口限制单独登记**：既有 summary_row 只传账号名与 detail，不传结构化 status。无上述前缀的生产自由文本维持中性，不能宣称所有生产状态已自动着色。本轮不改 Daily 模型、执行或重放逻辑。

## GUIDE CHANGES

只将 caption 的标题、版本/更新、来源/作者/授权分组换行。六分类、链接白名单、分页、发送顺序、全部原图及署名未改；过期提示原样保留。
文本前后产物：`E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/guide-captions.txt`、`E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/guide-captions.txt`。

## BINDING WEB CHANGES

响应式暗色面板、清楚的三步操作和有效/失效反馈、键盘焦点。去掉正文中的带令牌完整 URL，改为提示用户从地址栏复制，避免页面内容截图回显秘密。
不改有效性判定、路由、token、Cookie、请求、下载地址或安全合同。地址栏本身仍是原有绑定 URL，不声称改变了协议。

## EXTENSION CHANGES

380px border-box 与 max-width、防溢出、独立输入标签、URL 输入、键盘焦点、aria-live 状态区。
处理时禁用提交按钮，结束后恢复；成功/等待/错误各有文字与颜色。成功提示不再回显 QQ ID 或昵称。
域名校验、Cookie 选择、账号上下文、请求体和提交端点原样保留。

## BEFORE / AFTER ARTIFACTS

根目录：`E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03`。这些是本地忽略的证据文件，不把游戏素材重新公开提交。
每行原图对应同目录 `<名称>-50.jpg`、`<名称>-30.jpg`；JPEG quality=75，仅模拟 QQ 压缩。
`first-pass` 保存第一轮而非最终验收图；最终使用 `after`。

| 样本 | 修改前绝对路径 | 修改后绝对路径 |
| --- | --- | --- |
| character-c010 | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-c010-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-c010-0.png) |
| character-c010_03 | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-c010_03-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-c010_03-0.png) |
| character-full-ol | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-full-ol-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-full-ol-0.png) |
| character-missing-ol | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-missing-ol-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-missing-ol-0.png) |
| character-long-name | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-long-name-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-long-name-0.png) |
| character-fallback | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-fallback-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-fallback-0.png) |
| character-tall | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-tall-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-tall-0.png) |
| character-wide | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/character-wide-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/character-wide-0.png) |
| profile | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/profile-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/profile-0.png) |
| roster | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/roster-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/roster-0.png) |
| summary | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/summary-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/summary-0.png) |
| campaign | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/campaign-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/campaign-0.png) |
| campaign-unavailable | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/campaign-unavailable-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/campaign-unavailable-0.png) |
| raid | [before](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/before/raid-0.png) | [after](E:/DevCache/nikke-ui-polish-v0.3/artifacts/ui-v03/after/raid-0.png) |

网页截图根目录：`E:/DevCache/nikke-ui-polish-v0.3/output/playwright`：
- `before-binding-valid-mobile.png` / `after-binding-valid-mobile.png`
- `before-binding-expired-mobile.png` / `after-binding-expired-mobile.png`
- `before-popup-mobile.png` / `after-popup-mobile.png`
- 上述每组均另有 `-desktop.png`（1280×900）；手机 viewport 为390×844。
- `popup-pending-mobile.png`、`popup-success-mobile.png`、`popup-error-mobile.png` 为静态 DOM 状态展示，不是服务器绑定结果。
- HTML 预览禁用提交脚本；真实扩展处理逻辑通过 Node 隔离测试。浏览器检查仅访问 127.0.0.1。

## MOBILE / QQ PREVIEW FINDINGS

- 100%：已查看 c010、c010_03、满12 OL槽、缺失/未知 OL、长中英文名、全 fallback、Profile、Roster、Campaign、Raid、Summary。人物头发和脚部保留，未见示例数值跨栏或徽章碰撞。
- 50%：主要值、OL 百分比和三行关联可读；名单对齐，长名称不再覆盖等级。
- 30%：角色名、战力、三值及高对比 OL 百分比仍可辨识，但次级标签、页脚、Raid 范围和较长 Campaign 名称仍需点开原图。这是明确剩余限制，不将缩略图检查等同全部细节阅读通过。
- 合成 120×1600 / 1600×250 轮廓保持比例、完整且居中；极端图必然留白，未拉伸填满。它们不是另一款真实角色资源证据。
- 手机绑定页 content width=390，与 viewport 相同；正文不会横向溢出。扩展输入标签和按钮清楚；状态可换行，按钮禁用可见。
- 未发送 QQ 图片，也未宣称实际 QQ 压缩、送达或阅读效果已现场验证。

## RENDER PERFORMANCE

Windows Python 3.10.11，同环境相同 fixture，各5次，表中为含 PNG 保存的中位数 ms。无网络耗时；不是生产基准或冷下载性能。原始样本与图片哈希均在 before/after 的 measurements.json。

| 样本 | Before ms | After ms | 变化 |
| --- | ---: | ---: | ---: |
| character-c010 | 281.6 | 228.2 | -19.0% |
| character-c010_03 | 285.8 | 228.6 | -20.0% |
| character-full-ol | 298.6 | 218.7 | -26.8% |
| character-missing-ol | 309.6 | 202.4 | -34.6% |
| character-long-name | 380.9 | 232.8 | -38.9% |
| character-fallback | 237.3 | 184.8 | -22.1% |
| character-tall | 249.6 | 173.5 | -30.5% |
| character-wide | 247.4 | 176.8 | -28.6% |
| profile | 85.4 | 69.9 | -18.1% |
| roster | 185.4 | 102.2 | -44.9% |
| summary | 61.4 | 62.1 | 1.2% |
| campaign | 117.3 | 104.9 | -10.5% |
| campaign-unavailable | 48.8 | 40.0 | -18.0% |
| raid | 34.9 | 27.1 | -22.2% |

未引入模糊或高开销特效；主要收益来自去冗余绘制、有界字体复用和紧凑表格。短任务有毫秒级噪声，不据此作生产 SLA 承诺。

## REGRESSION RESULTS

- Issue #73 当前为 CLOSED（只读核验）；新增展示断言 .1322→13.22%、.8537→85.37%；现有 builder registry/fallback 小数合同测试保留且通过。
- 新增四位置×三空槽、残留词条不显示、empty/unknown/verified 区分。
- 默认/非默认 c010/c010_03 已用已有 idle 图视觉复查；现有版本路由与 idle resolver 测试通过，provider/runtime 文件未改。
- Costume assets 未改；40 verified/138 unresolved 不增删映射；现有 static_registry/Voice costume 测试保留。
- 别名 resolver、正式显示名、HP/ATK/DEF、Voice ja/audio-only/missing emits nothing、Daily/CDK、存储和资源并发代码均未修改，相关全套测试通过。
- 绑定页面不回显 request URL；扩展不回显账号标识；共享辅助文字对比≥4.5:1 测试通过。

## TEST RESULTS

- 练度 renderer + card builder + 新 UI 回归：27 passed。
- 完整 pytest：575 passed、452 subtests passed；仅第三方 faiss/numpy 的既有 DeprecationWarning。
- Node extension tests：4 passed，包含既有跨域拒绝、切换账号上下文及新增 UI 状态/隐私断言。
- `python -m compileall -q .`、分别 `node --check extension/background.js` / `node --check extension/popup.js`、`git diff --check` 均成功。
- 实际浏览器：390×844 与1280×900，有效/失效/扩展页面和扩展三状态截图；未使用真实凭据。
- 没有新增独立 web 构建系统；HTML/CSS 用真实 Chromium 检查，绑定逻辑保留现有 Python 测试。
- 本轮没有创建 PR 或启动云 CI，不能声称 Python3.11–3.13 云矩阵已重新通过。
- 本地目录不等于包名，pytest 启动时只将本工作树注册为 `astrbot_plugin_nikke`，未引用旧工作树。

复现：
```powershell
E:\DevCache\nikke-test-venv\Scripts\python.exe scripts/preview_ui_v03.py --tag before --repeat 5 --baseline 1047984db31d31d91f66bc14343852fca530fb05
E:\DevCache\nikke-test-venv\Scripts\python.exe scripts/preview_ui_v03.py --tag after --repeat 5
E:\DevCache\nikke-test-venv\Scripts\python.exe -c "import sys,types,pathlib,pytest; p=types.ModuleType('astrbot_plugin_nikke'); p.__path__=[str(pathlib.Path.cwd())]; sys.modules[p.__name__]=p; raise SystemExit(pytest.main(['-q']))"
node --test tests/extension.test.cjs
```

## FILES CHANGED

- `.gitignore`：忽略本地视觉证据/浏览器记录。
- `card_theme.py`、`character_card_renderer.py`、`renderer.py`、`profile_card_renderer.py`、`campaign_history_renderer.py`、`union_raid_renderer.py`。
- `guide_registry.py`、`web_service.py`、`extension/popup.html`、`extension/popup.js`。
- `tests/test_ui_v03.py`、`tests/extension.test.cjs`。
- `scripts/preview_ui_v03.py`、`docs/UI_AUDIT_V03.md`、`docs/UI_HANDOFF_V03.md`。

## BACKEND FILES TOUCHED

- `web_service.py`：仅 bind_page 的 HTML/CSS/提示文字与移除正文 URL 回显，属于用户明确要求的绑定页展示。有效性判断和全部提交方法无 diff。
- `guide_registry.py`：仅 caption 换行，无索引、白名单、文件或授权逻辑变化。
- 除上述内嵌 UI 以外，没有改 backend。前端 popup.js 仅可见状态、按钮反馈和成功文案，协议代码未变。

## REMAINING UI ISSUES

1. 30% 缩略图不能完整阅读全部次级文本；九项以上 OL 汇总仍较密，需要原图。
2. CharacterCardData 当前没有可直接展示的已解析服装名称；本轮不猜名字、不加后端字段。服装仍由实际 Spine 外观体现。
3. Summary 缺结构化状态输入，未匹配明确前缀的文本不自动着色；不为配色而修改 Daily 合同。
4. 极端长正式名称采用省略，不冒充换成别名；超宽/超高轮廓为了完整性会留白。
5. Browser 截图不是安装后真实绑定结果；QQ 阅读效果仅离线模拟。

## BRANCH / FINAL COMMIT SHA

分支：`feat/ui-polish-v0.3`，本地独立工作树 `E:/DevCache/nikke-ui-polish-v0.3`。
最终完整 SHA 见交接消息（提交包含本报告，避免在提交内自引用自身哈希）。
停止在已自审 UI 分支；没有自动合并或部署。
