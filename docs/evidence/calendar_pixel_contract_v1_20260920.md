# Calendar / Schedule Operations Feed 像素契约验收

状态：`READY_OFFLINE`（合成 fixture + 本机 Chromium DOM 证据；未执行部署或真实账号联调）

基线：`origin/main@10c2997ee2a424bae72c9c7e05c9f28eacae38fa`

工作分支：`feat/calendar-pixel-contract-v1`

## 根因

旧实现把 item 后的 gap 计入 item 高度，且 Python 的 `PANEL_OVERHEAD=178` 没有计入 panel 上下 1px border。浏览器中的 Active 内容又因字体、padding 和进度条产生真实内容高度，导致 7 Active + 4 Next 的 Python 预算小于 DOM 盒高；`.panel-body { overflow: hidden }` 最终把第 4 行 Next 裁到了 footer 下方。

## CSS / Python 几何合同

- 面板固定开销：`28 + 70 + 10 + 6 + 44 + 20 + 2 = 180px`；2px 为 panel 上下 border，所有尺寸按 `border-box` 解释。
- Section header：`32px`，其后 `8px`；Active 与 Next 之间 `12px`。
- Active：卡片 `68 / 80 / 92px`（normal / long / oversize），相邻 gap `5px`，padding `6px 14px`。
- Next：行 `44 / 58px`（normal / long），相邻 gap `7px`，padding `6px 16px`。
- `measure_active_section()` 与 `measure_next_section()` 分别计算 item 高度和相邻 gap；`measure_page_content()` 只组合 section/header/gap，不再把 gap 嵌入 item。
- 保留 `1600px` base max、竖版 KV source-extended 上限及 `2400px` absolute cap；未修改动态分页和背景 cover-crop 规则。

## 字体调整

| 元素 | 旧值 | 新值 |
| --- | ---: | ---: |
| 主标题 | 32px | 34px |
| Section 标题 | 13px | 14px |
| Active 标题 | 15px | 17px |
| Active 时间 | 11px | 12px |
| Remaining label/value | 9px / 17px | 10px / 19px |
| Active 分类 / badge | 10px / 9px | 11px / 10px |
| Next 时间 / 标题 / starts | 12px / 13px / 12px | 13px / 15px / 13px |
| Next 分类 | 10px | 11px |
| Footer | 12px | 13px |

## 生产形态 fixture 与 DOM 结果

`realistic-7-active-4-next` 包含 7 Active、4 Next、EXACT 进度、`NEXT ENDING`、维护活动、中文标题和长英文标题。

- 单页：是；canvas `1600 × 1247`；panel 高度 `1077px`。
- Active：7；Next：4；最后一行 Next bottom 到 footer top 的安全间距：`6px`。
- `.panel-body`：`scrollHeight=913`、`clientHeight=913`。
- Active/Next list：均无 scroll overflow；所有 Active 子元素 bottom 均不超过所属 card bottom（1px 测量容差内）。
- `large-font-long-title-mix`：canvas 高度 `1024px`，长标题与 3 行 Next 全部可见。

## 前后 artifact

以下文件是本机生成的忽略目录取证，不是产品资源或线上证据：

- Before（origin/main 旧布局）：`E:\_codex_work\calendar-pixel-contract-v1-worktree\astrbot_plugin_nikke\output\calendar-current-7a4n.png`
- After（7 Active + 4 Next）：`E:\output\calendar-after-realistic-7-active-4-next.png`
- After（大字体长标题混合）：`E:\output\calendar-after-large-font-long-title-mix.png`
- After（原 7+4 动态 fixture）：`E:\output\calendar-after-dynamic-7-active-4-next.png`

视觉检查确认：旧图的 Next 内容被 footer 裁切；新图完整显示 4 行 Next，长标题以省略号收束但保留完整 `title` tooltip，footer 不遮挡列表。

## 渲染性能

同一台 Windows 本机、同一 Chromium、同一合成 payload，计时范围为 `set_content + document.fonts.ready + screenshot + DOM measurement`，7 次取中位数：

- origin/main 模板：中位数 `226.67ms`，范围 `192.94–275.27ms`。
- 本分支模板：中位数 `237.80ms`，范围 `202.12–246.51ms`。
- 差异约 `+4.9%`，主要来自字体增大；未引入网络请求或循环渲染。

## 测试与限制

- 定向：`84 passed`（calendar、T2I frontend、visual contracts）。
- 浏览器几何单测：`1 passed`（最终 CSS 修正后重跑）。
- 最终全量：`1018 passed, 2 skipped, 653 subtests passed, 1 warning`。
- `python -m compileall -q .`：通过。
- `node --check extension/background.js`：通过。
- `node --check extension/popup.js`：通过。
- `git diff --check`：通过；仅有 Windows 换行提示。

本轮只修改 Calendar T2I payload geometry、Calendar 模板、Calendar preview fixture 与 Calendar 测试；没有修改 Runtime Status Resolver、TimePrecision、FieldEvidence、Freshness、Coverage、GameKee/Official/Manual Override/LKG/Reminder、Character/Profile/Raid/Tarot 或其他 T2I 模块。未部署、未声明 live evidence，GitHub CI 仍由 PR 检查负责跨版本回归。
