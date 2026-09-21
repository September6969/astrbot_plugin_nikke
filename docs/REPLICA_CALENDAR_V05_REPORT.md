# 案例角色卡与日程 v0.5 规格及验证报告

## 基线与边界

- 实施分支：`feat/character-replica-calendar-v05`；main 基线 `4c1caa272302051771040fc353504897bd7ce02b`。
- 原 `feat/progression-overview-v1` 位于 `c858149`，原工作区未修改、未合并。本次没有生产部署、账号写操作、发群消息或远端推送。
- 本规格替代旧横版、左右分区和禁止玻璃拟态要求。

## 单角色卡合同

- 复用原指令及 HTML/T2I，输出 1600×2400 PNG。全幅等比立绘、顶部毛玻璃身份栏、橙色等级、战力、身份图标；底部四行汇总、2×2 装备、右侧三技能。无独立属性面板、装饰标题或页脚。
- `character_card_layout=replica` 默认启用；classic 及渲染失败使用原 Pillow。其他页面继续遵循 `ui_renderer`。
- 顶部为所有已确认阶数的简单整数加和；未知阶数不记为零，显示“已知词条合计”。按稳定效果 ID 聚合，按阶数和降序、效果 ID 升序取前四组，不足四组保留空白。四件装备各保留三个槽位，区分未装备、空槽和未知效果。
- 案例可见阶数实际为 **80**：19+18+17+15+11。旧计划的 83 是算术错误，不硬编码补三阶。
- 同效果、同阶数、同原始值先合并，再以 Decimal ROUND_HALF_UP 计算已验证的弹药／蓄力收益；阶数总和不代表有效收益。基础蓄力 1 秒的条件测试得到 11.00%；官方 c471 基础为 120 厘秒，当前卡得到 10.83%。基础弹药 6 发时，132.83% 对应 +8。
- 无已验证基础值时省略弹药附加发数，蓄速标记“纸面合计”；其他属性不推测收益公式。
- 官网武器资料覆盖现有角色主表 200 项，技能图标去重 238 项，保存公开源 URL 与哈希。模板版本、角色、皮肤及完整 DTO 指纹进入渲染载荷。

## Spine Face Anchor

- 离线 `prepare_face_anchors.py` 调用 `extract_spine_face_anchor.mjs`：优先可见 eye attachment，其次 face、head attachment，最后 head bone；排除眉毛、睫毛及高光候选。
- 使用匹配骨架版本的 Spine Core、idle 动画第 0 帧，结合渲染边界、画布、裁切框与 padding 转换为最终 PNG 坐标。
- metadata 按正式角色／皮肤资源 ID 保存锚点、范围、骨架／atlas／PNG 哈希、像素哈希、尺寸、动画与变换。同一皮肤支持多个已验证分辨率。
- 运行时 `face_anchor.py` 只消费 metadata 和 PNG，校验身份、尺寸和像素哈希，不解析 Spine。缺失／不匹配时等比完整显示，不猜坐标、不使用默认皮肤锚点。
- 可选 `framing.target=[x,y]` 与 `framing.extent_width` 提供角色／皮肤级构图校准；默认眼部范围宽 256px，锚点落在画布 (760,550)。
- 当前覆盖 c010、c010_02、c010_03、c017、c234、c330、c352、c471 共 8 项。c471 已离线导出 2474×3548 高清透明 PNG 并更新资源清单；不等于全角色／全皮肤已校准。

## 日程合同

- 请求参数保持原合同；扩展 `key_visual_url`、`image_urls`、`activity_kind`，旧 schema 1 缓存可读。
- 按 big_picture → image_list → picture 保存并去重候选；支持列表、嵌套对象、JSON 字符串和空白分隔多 URL。原 banner 字段保留兼容语义。
- 429／5xx／连接超时执行有界退避重试，日志使用脱敏工具。
- 默认预取当前及未来 30 天活动，最多 16 项、并发 3，单图限制 12MiB／3000 万像素，转换 WebP。独立 visuals 目录及 visual_cache.json，不复用立绘缓存。
- 优先保留本轮选中项；未选中项 7 天未用清理，超过 64 项按最近使用时间淘汰。读取和删除均验证目录边界。
- 结构化快照先校验、原子落盘，再替换内存；保存失败返回失败且保留旧快照。图片失败不使已保存快照失败，新候选失败可保留旧图。
- 服务暴露本地图片路径解析接口；日程页面布局保持原状。

## 验证记录

- 全仓初次回归：798 通过、1 失败（新增配置未登记到配置合同）；已修正配置文档及测试。新增大小／像素限制、5xx、16 项／并发 3、选中保留和锚点变体测试。
- 修正后定向回归：16 通过，22 子测试通过。高清立绘替换后更新原固定尺寸断言，资源与锚点回归 17 通过。
- 临时集成工作区基于练度总览 c858149，三方补丁应用无冲突；整套测试 **812 通过，491 子测试通过**。临时组合不改变两个分支历史。
- 数值测试覆盖同分、超过四种、空装备、缺失阶数／基础值、半入舍入、数据与皮肤缓存指纹。
- 10 项预览覆盖白雪公主、拉毗两皮肤、宽／高人物、其他阵营、长名字、空装备、未知皮肤；姓名／汇总／数值无横向溢出。导出原尺寸、50% 和 30% 缩略图，以及叠加、左右对照、两张局部图。
- GameKee 真实只读请求：120 行、120 有效、0 畸形、0 重复、120 含候选；当前窗口选中 3 项，3 项成功下载转换，0 失败。采样存在 image_list 为空的记录，picture 回退仍保留。证据见 `output/calendar-live-report.json`。第二次真实同步 3 项全部命中本地缓存、无重新下载，见 `output/calendar-live-repeat.json`。

## 复现与交付文件

预览及布局检查位于 `output/playwright/replica/`：snow-white.png、overlay.png、comparison.png、detail-header.png、detail-equipment.png、layout-audit.json。预览使用案例装备 fixture 与公开角色资源，不代表真实账号快照。

```powershell
# 匹配版本官方 Spine Core 仅在离线脚本中使用。
python scripts/prepare_face_anchors.py --manifest assets/spine_manifest.json --png-dir assets/spine-rendered --bundle-dir <骨架目录> --runtime-40 <4.0/index.js> --runtime-41 <4.1/index.js>
python scripts/render_spine_preview.py --runtime <spine-core.js> --webgl-runtime <spine-webgl.js> --bundle-dir <骨架目录> --render-id c471 --output <输出PNG路径>
# 截图环境需要本地 Playwright 和 Chromium。
python scripts/preview_replica.py --manifest output/high-resolution/spine_manifest.json --png-dir output/high-resolution --reference <用户案例.jpg>
```

## 未满足的视觉验收

当前交付可运行复刻版本，**没有宣称像素级一比一通过**。案例数码字体、研究等级徽章、装备角标与收藏品星级外观仍有差异；idle 第 0 帧与案例动画帧可能不同。现有 8 份锚点不是全角色／全皮肤覆盖。QQ 送达和远端 AstrBot 渲染尚未现场验收。

字体 ReplicaSans.otf 来自仓库 NotoSansHans-Medium.otf 子集，保留字体内部许可信息；原字体保持不变。技能与立绘使用公开游戏资源，没有将案例截图作为模板背景。
