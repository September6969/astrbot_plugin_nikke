# NIKKE 原生 HTML/T2I 前端交接（历史记录）

> 当前状态：本文保留旧阶段的接线记录。PR #103 退役了单角色 1800×1000 Pillow 卡；唯一生产角色卡现为 1600×2400 白色竖版 T2I。渲染失败只返回明确错误，不会转入 Pillow 角色卡或重复查询。

## 工作树与范围

- 仓库：`E:\DevCache\nikke-t2i-phase1\astrbot_plugin_nikke`
- 分支：`feat/t2i-campaign-phase1`
- HEAD：`ebbb18f8c32ca5cf27ba3fb3ceb1255fe6acabb5`
- 本次实现保留为未提交工作树。未合并 main、推送、创建 PR、部署、修改账号或发送 QQ 消息。
- Gemini 资产来源：`D:\download\Compressed\nikke_docs\astrbot_plugin_nikke`，`prep/blabla-static-assets`，基线 `34786c721daf7524bed3769898dafbfa9995b276` 上的未提交成果。源工作树未修改。

## 七页接线

`ui_renderer` 默认 `pillow`；设为 `t2i` 启用以下七页。配置缺失或未知值沿用旧路径。

| 页面 | 命令 / 数据来源 | 画布 | T2I 失败行为 |
|---|---|---|---|
| Campaign | 原 Campaign 命令，CampaignHistoryBuilder → StageClearRecord | 1600×880 | 同一 DTO → Pillow |
| Calendar | `/妮姬 日程 [7/14/30]`，默认 14，CalendarService | 宽 1400，动态高 | 同一窗口数据 → 原文本 |
| Union Overview | `/妮姬 联盟突袭`，UnionRaidBuilder | 1600×900 | 同一 DTO → Pillow |
| Union Records | `/妮姬 联盟突袭 排行`，既有 build_ranking | 宽 1500，动态高 | 同一 DTO → 原文本 |
| Union Member | `/妮姬 联盟突袭 我的`，既有 build_member_ranking | 宽 1500，动态高 | 同一 DTO → 原文本 |
| Profile | `/妮姬 我的`，ProfileBuilder → ProfileDashboardData | 宽 1200，动态高 | 同一 DTO → Pillow |
| Character | `/妮姬 查询 练度 <角色>`，CharacterApplication → CharacterCardData | 1600×2400 | Spine/Face Anchor → CharacterT2IPayloadBuilder → `templates/t2i/character.html` → AstrBot html_render；失败明确报错 |

T2IRenderer 通过 callback 使用 `self.html_render`，不继承 Star，不启动浏览器，不创建 Node 构建链，不选择或覆盖 AstrBot 服务端点。各模板声明数值 viewport width，避免不同原生端点的默认视口改变画布；动态页仍 full_page、不截断。原生选项依据 [官方服务文档](https://github.com/AstrBotDevs/astrbot-t2i-service)。生产超时 30 秒；普通页面失败走既有回退，单角色卡失败明确报错且不回退旧 Pillow，取消直接传播，不重新查询业务 API。

Calendar 的分组从原文本逻辑抽出为 `CalendarService.group_window`，仍由 Service 决定 ENDING SOON / ACTIVE / UPCOMING、24 小时边界和 horizon。adapter 仅格式化；活动不截断。Union Records 保持 Builder 排序与真实 rank；`len(attacks)` 只标记返回记录。Member 使用 `RECORD 01` 等记录编号与 CURRENT_RESPONSE_MEMBER，保留每条精确伤害、五个成员、成员精确 combat 与真实记录字段。Overview 不放成员排名、联盟 Rank 或总伤害 KPI，不推断 Current Target。

## 已整合真实资源

| 资源 | 已验证范围 | 展示链 |
|---|---|---|
| 默认 compact | 200/200 | Master canonical identity → 既有 LineupPortraitResolver → 本地 PIL → T2IAssetResolver |
| Costume compact | 178/178 | 真实 costume_id → 同一 Resolver；不推算皮肤索引 |
| Boss | Seasons 35–40 的 30/30 encounters，23 张本地图 | 既有 BossAssetResolver → Path → Data URI |
| Character Spine | 8/8 本地 PNG；默认覆盖 6/200，另 2 张皮肤 | AssetManager 严格校验 manifest → PIL → bounded Data URI |
| Profile 资源图标 | Registry 的 8 种 | 既有 get_currency_icon / SHA 校验 → Data URI |

Boss manifest 有 52 个映射条目，包含等级变体/别名；不能将其当作 52 场已验证赛季 encounter。Seasons 41–44 的 20 个 encounter 缺真实 metadata，继续 `IDENTITY_UNRESOLVED_PENDING_LIVE_SESSION`，展示为 UNRESOLVED。已知 Boss 的战斗 `status=UNKNOWN` 与身份未解析是不同概念，不能用有图片推断 CURRENT/NEXT。

皮肤 10005 的 compact 索引为 2，而 Spine 为 `c010_03`。各资源分别消费自己的正式映射。T2I 不使用资源文件名算身份，不用 Spine 裁剪代替 compact，不将未知/错误皮肤降级到另一个真实角色或默认皮肤。

资源复制保持原目录 `data/nikke/blabla-assets` 与 `blabla-manifests`。`.gitignore` 仅放行这两份公开静态包，其他 runtime data 仍忽略。两个 Resolver、准备阶段测试、manifest 维护脚本和证据文件沿用源成果；没有复制其旧版 Client、Builder、main 或 Profile 业务实现。当前 AssetManager 保留既有逻辑，仅整合对应入口、本地图标优先链与 manifest 兼容。

Gemini v2 `characters` 与当前既有 v2 `assets` 两种容器均可读取，保留 SHA-256、PNG magic、decode、尺寸、路径越界、身份冲突拒绝，以及旧版本化缓存兼容逻辑。PNG 专用校验不误伤现有 SHA 校验的 WebP 货币图标。

## Profile 已确认修正

- TODAY 为唯一强业务区域。storage_fullness 仍是 0..1 ratio，只显示百分比与横向进度，不虚构 used/total；0.8、0.95 为展示警告阈值。
- Resources 四列两行，每项使用 registry 名称、真实整数和本地图标；一项失败只降级该项。
- UI 移除战术学院课程/课时；DTO、Builder 与既有后台测试保留。
- OUTPOST 展示同步器、前哨战斗、基础核心、普通/困难主线；ROSTER 展示数量、最高等级/CP、时装数量。
- Simulation 使用当前 daily record 的 display_label 与已验证 score、subseason、season；不从旧字段猜值。
- 循环室两列，优先 presentation_name / display_name，只在 EXP > 0 时展示 EXP。
- Collection 使用 Builder 已经由 registry 汇总的 memorial_summary，保留 memorial_partial；不在模板重新归类 raw memorial_counts，不重复计数。
- ACCOUNT 保留 area_id 原值，不猜服务器名称；空 area_id 显示 Unknown。
- AVAILABLE / PARTIAL / UNAVAILABLE / UNKNOWN 与真实零值区分；范围说明紧邻对应数字。完整合成 preview 提供当前已验证字段，边界 fixtures 另测缺失和部分返回。

## 模板与图片合同

全部模板由本地 CSS、可信宏与页面组成一个自包含字符串，显式 `autoescape true`。只传 JSON-like 展示字段，主要图片字段为 `portrait_data_uri`、`boss_image_data_uri`、`character_art_data_uri`、`icon_data_uri`。最终 HTML 不引用 http(s)、file、文件路径、fetch、XHR、@import 或脚本。

T2IAssetResolver 只接受 Path / PIL，限制 12 MiB 输入、20M pixels，按指定目标缩放，PNG 编码；缓存上限 32 项 / 8 MiB，带锁。Character 只裁去透明边缘，完整人物与武器保持在 Character Safe Zone；数据在独立 Data Safe Zone。阅读顺序为 Character → Name → CP → OL summary → Equipment → Secondary。装备 2×2，每件恰好 3 OL；OL semantic colors 不随 Character theme 改变，底部为次要信息带，不恢复右侧竖 rail。

## 验证与复现

本次最终结果：全量 pytest **763 passed / 490 subtests passed**；T2I 定向 **57 passed**（含资产集成 15 项）；扩展 **4 passed**；Python 3.10 compileall 与 `git diff --check` 通过。资产准备阶段的原有 29 项测试亦通过。数字为不同测试集合，不能相加作总数。全量日志：`E:\DevCache\nikke-t2i-phase1\full-frontend-delivery-tests.log`；定向日志：`targeted-t2i-final.log`；扩展日志：`extension-final-tests.log`，均位于同一父目录。

18 个交付图名（含同图别名），合计 54 张 100% / 50% / 30% PNG 已验证格式、尺寸与缩放比例。七页代表图已作视觉检查：页面类型、第一视觉、关键数字/状态与主要结构可识别；50% 主要业务数据可读取；100% 可读取细节。该历史阶段的 Character 图片为 1800×1000；当前唯一角色卡为 1600×2400 白色竖版。此处是本阶段实现检查，不替代后续最终美术和 QQ 实机验收。

所有 pytest 使用 fake native callback，真实截图仅由显式预览脚本运行。现有测试未删除或降低强度；Phase 1 头像占位测试升级为真实解析且继续禁止调用 Spine。

```text
python -m pytest -q
node --test tests/extension.test.cjs
python scripts/preview_t2i_ui.py --output-dir <preview>/t2i/campaign --fixture normal
python scripts/preview_t2i_ui.py --output-dir <preview>/t2i/campaign --fixture hard
python scripts/preview_t2i_frontend.py --page <page> --output-dir <preview>/t2i --fixture all
```

真实预览使用既有 Python 3.10 / AstrBot 环境，全量 pytest 使用既有 Python 3.13 环境。预览 callback 仍调用 `Star.html_render`，使用正式模板与 adapter，没有 demo-only HTML。原生服务曾返回 `no available server`、网络错误或下载超时；预览脚本验证下载图片并有限重试，预览预算为 180 秒，生产 30 秒不变。

预览目录：`E:\DevCache\nikke-t2i-phase1\preview\t2i`。各代表图有原始 PNG、`-50.png`、`-30.png` 及对应 HTML/JSON。具体文件和校验摘要见 `T2I_DELIVERY_AUDIT.json`。

## 修改文件索引

- 命令及配置：`main.py`、`_conf_schema.json`、`docs/CONFIGURATION_ACCEPTANCE.md`；`calendar_service.py` 仅提取既有分组逻辑以供两种展示共同使用。
- 展示：`t2i_assets.py`、`t2i_payloads.py`、`t2i_renderer.py`、`t2i_templates.py`、`templates/t2i/` 七页与共享 CSS/宏。
- 资产接线：`asset_manager.py`、两个复用 Resolver、`assets/spine_manifest.json`、两份 `data/nikke/blabla-*` 公开目录与 `.gitignore` 精确例外。
- 复现：`scripts/preview_t2i_ui.py`、`preview_t2i_frontend.py`、`t2i_preview_fixtures.py`、原有 Spine manifest 维护脚本。
- 测试：`tests/test_t2i_campaign.py`、`test_t2i_frontend.py`、`test_t2i_asset_integration.py`、三个资产准备测试、合成 fixture、配置键精确校验。
- 证据：两套准备阶段 evidence；`T2I_ASSET_IMPORT_PROVENANCE.json` 记录 570 个逐字节一致的导入文件与 8 张复用 PNG；`T2I_DELIVERY_AUDIT.json` 提供完整改动路径与截图 hashes。

## 回退覆盖

- 普通异常、超时、无效 native 返回值、取消传播、默认 Pillow、原生成功。
- 命令层同一 DTO 回退，确认不重复业务请求；Calendar 保留原 Service 文字合同。
- 单角色练度卡没有视觉回退分支：已取得 DTO 的白色竖版 T2I 渲染失败时向用户返回明确错误，不重查详情、不调用 Pillow 角色卡。
- 单头像缺失/损坏、错误角色皮肤、未知身份，保留名字/LV/combat，其他成员不受影响。
- Boss 已知/未解析；缺图不伪造身份、HP、元素或状态。
- Spine 错 hash、缺 hash、坏 PNG、缺文件、路径越界、身份冲突及未知角色安全降级。
- Profile 未知、零值、部分、不可用；图标单项失败；storage 普通/警告/强警告/Unknown。

## 最终视觉复核交接

后续模型在当前未提交工作树继续，不重做资源解析和页面架构。优先检查本次真实 PNG：30% 识别页面类型、第一视觉、关键数字/状态；50% 读取主要数据；100% 读取全部细节。只在验证结构后调字号、间距、颜色、中文字体和长文本。任何业务字段/排序/分组/范围变化应回到既有 DTO 与已验证来源，不从图片或示例推断。

剩余技术债：Seasons 41–44 metadata 待真实 payload；本地 Spine 覆盖有限；最终像素调整；不同原生环境 CJK 字体差异；超长标题、更多 OL summary、更多动态记录的版面压力测试。Campaign 已有超出展示预算时整页回退，不静默截断。原生服务可用性属于环境依赖，本地测试不等于 GitHub CI 或 QQ 验收。

本阶段不把未来资源扩容和视觉优化作为阻塞，也不自动进入部署或 QQ 验收。

当前实现阻塞：**无**。后续接手检查清单：确认分支与未提交工作；读取审计 JSON；先看七页原图与缩略图；保留范围、排序和资源身份合同；仅做用户授权的最终视觉调整；提交、PR、部署与 QQ 验收依后续明确指令执行。
