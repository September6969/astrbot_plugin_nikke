# 单角色练度卡最终版验收

状态：`READY_OFFLINE`（2026-09-08）。预览来自脱敏 fixture 与公开静态 FB，不代表真实账号联调、QQ 送达、部署或素材权利方授权。

## 数据合同

- `CharacterDetails → client → builder → CharacterCardData → renderer` 保留 `resource_id` 与 `costume_id`，立绘统一走静态 FB 主链。
- HP/ATK/DEF 只显示响应中的已确认整数；缺失显示 `—`，不由等级或战力反推。
- 四个装备槽固定存在；未装备不显示残留词条。
- 未确认的 OL 类型显示“未识别词条 / 待确认”，不猜单位，也不进入确认单位汇总。

## 视觉合同

- 画布固定 1800×1000，静态全身像为最大单一视觉主体。
- 主题从立绘非透明像素提取 dominant/secondary/dark；企业色仅弱混合，属性色只作约 5% accent。
- 企业 Logo 在养成区作为 7% alpha 水印；装备图标由 56×56 放大到 72×72。
- Abnormal 使用深紫黑背景并轻微偏移水印，不复制 Renderer 或引入角色特判。
- 长中英文名使用真实字宽缩放/省略，透明边缘先裁切，人物超高部分在面板底部自然裁切。

## 实际预览

脚本 `scripts/preview_character_cards.py --remote` 已生成并逐张查看 Red Hood、Alice、Missilis/Water、Elysion/Wind 长名称、Abnormal 和全 fallback 六张合成预览。检查结果：人物未横向拉伸，长名称未覆盖等级区，四装备槽顺序稳定，unknown OL 可见，fallback 可完整出卡。

预览保存在工作区外 `E:\_codex_previews\nikke-character-card-final-v1`，不提交生成物。

## 请求预算与证据缺口

角色卡由 `resolve_character_assets()` 固定提交一项 portrait 与十项独立图标任务；没有按装备词条循环发网络请求，同键下载保持 single-flight。Spine 只消费已有 L2D 索引，命中版本化 PNG 时可作为 portrait 来源；未命中时只在明确匹配 runtime 的后台队列预热，当前请求继续静态 FB/占位回退，不同步等待。

`NEEDS_LIVE_EVIDENCE`：当前真实 CharacterDetails 是否在所有区域返回 HP/ATK/DEF、实际 costume ID 对照、真实 QQ 发送尺寸/清晰度。最小现场动作是一次获准的只读角色详情抓取与一次人工触发的测试群发送；本 PR 不执行。

CI 说明：本分支为 stacked branch，必须在 PR #47 合并后保留本 PR 的卡片提交；当前 Draft PR 目标为 `main` 以触发仓库 Python/Node CI，合并顺序仍为 #47 → #48。
