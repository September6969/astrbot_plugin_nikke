# NIKKE Character Card Layout Module v2 离线验收

## 状态与范围

- 状态：READY_OFFLINE。
- 日期：2026-09-20。
- 本主题只处理角色练度卡的布局、面部/身体纵向 framing、摘要行和离线 Spine 锚点工具；不重做已接受的后端数值、Costume、Voice、Daily/CDK 或服务器部署合同。
- 不包含真实账号访问、Signin、QQ 消息/Record、生产部署或资源授权证明；所有预览均为本地离线 fixture/合成证据。

## 基线与工作树

- 包文档指定基线：feat/character-card-pixel-calibration-v1@fc751fefbce898b1be9611b9df8434793b23e74d。
- 实际工作树：E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke。
- 分支：feat/character-card-layout-v2。
- 实现提交：016148fe6609c1410210858952ea5cc65e0d3aa2。
- Calendar Content Quality PR #95 保持独立；本分支没有把 Calendar PR 当作父分支，也没有修改 main。

包内安装器已成功执行，安装器没有自动 commit/push。Windows 工作树的全局换行配置曾使原始字节 hash 不一致；仅在本独立、无用户改动的工作树中按包文档临时规范化相关文件为 UTF-8/LF，核对期望 hash 后安装，随后恢复本地 Git 换行配置。

## 实现合同

- CharacterCardLayout 以显式 summary_count 驱动摘要区，支持 0–4 个已确认摘要项；不把 unknown 当作 0，也不生成空摘要行。
- 四个装备位置始终保留；未装备槽位使用中性 empty state，不产生粉色/红色伪激活层。
- face/core-axis 只接受严格的 head_top + eye + breast 安全组合；breast selector 仅接受明确胸部语义，歧义或缺失会记录原因并 fail-closed，不按名称、顺序或相邻骨骼猜测。
- 生产角色卡路径只消费已生成的 JSON 锚点和现有静态 Spine PNG；Spine runtime、队列、网络下载和预渲染器只存在于离线提取/准备脚本，不进入普通卡片热路径。
- vertical_gain 保持 0.0；此次修订只调整 face-guided Y framing 和摘要/装备布局，不改变 Body X 合同。

## Face anchor 重建证据

输入是仓库现有 assets/spine_manifest.json 的 8 个显式条目：c010、c010_02、c010_03、c017、c234、c330、c352、c471。

- 输出记录总数：36。
- manifest 范围内重建：8。
- manifest 范围外原记录保留：28。
- 未生成伪造映射；unavailable：空。
- 原因统计：ok=2、breast_unavailable=4、ambiguous_head_attachment=2。
- 实际生成 core axis：c010_03、c352。
- c016（Mori）与 c191（Arcana）不在本轮显式 manifest，未猜测新的 core axis；继续使用现有 legacy face anchor/framing fallback。

c010_03 使用 head_attachment:head/face 与 pair:boob_l+boob_r；c352 使用 head_attachment:head/head 与 single:chest。其余条目只保留明确的失败原因，后续需要新输入时再重建。

## 视觉验收

已实际查看以下离线合成预览：

- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\rapi.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\rapi-vacation.png（非默认服装）
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\empty.png（summary 0、空装备）
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\wide.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\tall.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\tetra.png（c352 core-axis）
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\long-name.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\output\playwright\replica\unknown-costume.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\docs\evidence\face_guided_body_centering\c016_y_offset_compare.png
- E:\_codex_work\character-card-layout-v2-worktree\astrbot_plugin_nikke\docs\evidence\face_guided_body_centering\c191_y_offset_compare.png

preview_replica.py 生成的 11 个样本均为 overflow=[]；长名会换行，非默认立绘可见，空装备保持中性，宽/高比例与企业样本未出现裁切越界。c016/c191 的 before/after 图只证明 legacy Y offset 的离线视觉变化，不证明真实账号或生产送达。

core-axis 诊断覆盖 summary 0–4：c010_03 各摘要档位经 safe-area clamp 后满足 head/eye/breast 轴；c352 的 summary 0–3 满足轴，summary 4 按 6% 尺度限制返回 scale_limited，不强行缩放破坏卡面比例。

## 渲染性能对照

对精确基线和 v2 使用同一条命令、同一台本机、同一份离线 manifest，分别单次测量 python scripts/preview_replica.py --manifest assets/spine_manifest.json --png-dir assets/spine-rendered 的墙钟时间：

| 样本 | 墙钟时间 | 说明 |
| --- | ---: | --- |
| fc751fef 基线 | 22,845 ms | 独立 detached benchmark worktree |
| v2 | 21,059 ms | 016148f 工作树 |

这是单次本地样本，不宣称稳定 benchmark 或生产吞吐；本次没有观察到预览生成回归。临时 benchmark worktree 已移除。

## 测试与静态检查

- 角色卡/锚点/渲染定向套件：109 passed、3 subtests passed、1 warning。
- 最终唯一一次 full pytest：892 passed、491 subtests passed、1 warning，用时 52.53s。
- python -m compileall -q .：通过。
- node --check scripts/extract_spine_face_anchor.mjs：通过。
- node --check extension/background.js：通过。
- node --check extension/popup.js：通过。
- git diff --check：通过；Git 仅报告 LF 在 Windows 全局配置下未来可能转 CRLF 的提示，没有 whitespace error。

本次 full pytest 前修复了两个既有日期脆弱的测试 fixture：公告和官方维护通知从已过期的 2026 日期改为 2027 日期；生产逻辑没有改动，修复后的两个 targeted tests 均通过。

## 提交文件与后端触碰说明

本实现提交包含：

~~~text
assets/face_anchors.json
character_card_layout.py
character_replica.py
docs/evidence/face_guided_body_centering/c016_y_offset_compare.png
docs/evidence/face_guided_body_centering/c191_y_offset_compare.png
face_anchor.py
scripts/extract_spine_face_anchor.mjs
scripts/prepare_face_anchors.py
spine_core_axis.py
t2i_payloads.py
templates/t2i/character.html
tests/test_announcements.py
tests/test_calendar_v04.py
tests/test_character_card_layout_v2.py
tests/test_face_anchor_core_axis_v2.py
tests/test_prepare_face_anchors.py
tests/test_spine_core_axis.py
tests/test_t2i_frontend.py
~~~

character_replica.py、face_anchor.py、t2i_payloads.py、模板和两个新布局模块属于角色卡 presentation/rendering 链；两个 Spine 脚本只负责离线锚点提取与合并；assets/face_anchors.json 是离线生成的锚点数据。没有修改账号、Voice、Daily/CDK、存储、服务器配置或部署脚本。

## 未完成与后续边界

- 未执行生产部署、真实 QQ/NapCat 送达、Signin、真实账号读写或现场 Spine runtime 验证。
- 未为 c016/c191 制造缺乏安全证据的 core axis，也未扩大 Costume 映射；这些仍按现有 fallback/证据合同处理。
- 本分支是包指定 baseline 上的独立 UI/布局 PR；如需并入更晚的 Calendar/main 演进，应在评审后单独 rebase/解决冲突，不在本次自动完成。
