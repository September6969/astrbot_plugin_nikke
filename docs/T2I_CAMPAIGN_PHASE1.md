# Campaign 原生 T2I：Phase 1 历史记录

本文记录已验收的第一阶段；当前七页实现与真实资产结果见 [完整交接](T2I_FRONTEND_HANDOFF.md)。以下测试数字和占位图说明仅属于当时的阶段状态。

实现基线：`ebbb18f8c32ca5cf27ba3fb3ceb1255fe6acabb5`，工作分支 `feat/t2i-campaign-phase1`。视觉依据为用户提供的 v0.8 REPO ALIGNED 总规范。本阶段仅实现公共基础设施和 Campaign；没有修改其他页面、业务接口、Builder、Resolver 或领域 DTO。

## 接线与配置

`main.campaign` → 原有 Client → 原有 CampaignHistoryBuilder / CampaignStageResolver → StageClearRecord → `_render_campaign_record` → CampaignT2IPayloadBuilder → JSON-like payload → 自包含模板 → 注入的 `Star.html_render()` → `event.image_result`。

`ui_renderer` 默认 `pillow`，设为 `t2i` 后仅改变 Campaign 图片路径。原生调用在 30 秒内未完成、返回无效结果、模板或适配器失败时，用同一个已经建立的 DTO 调用原有 Pillow renderer；没有第二次业务请求。取消任务直接向上传播，不启动回退。原有 ERROR / RATE_LIMITED 的命令文本响应保留；预览中的错误图片只验证展示组件，不代表命令改成错误图片。

T2IRenderer 不继承 Star，不启动浏览器，不指定端点或 local / remote。PNG 参数增加 `quality=None`，用来覆盖已检查 AstrBot 网络策略的 JPEG `quality=40` 默认值，避免 PNG 参数冲突。

## 模板与资产

- TemplateLoader 只接受已支持的页面名，组装本地共享 CSS、可信宏和页面为单个字符串；远程端不需要文件系统、include 或 import。
- 整份模板显式 `autoescape true`；用户/API 字符串无 `safe`，格式化在 Python。HTML 不含 JavaScript、远程字体、远程图片或本地文件引用。CSP 限制图片为 Data URI、样式为内联，禁用脚本与其他资源加载。
- AssetManager 的 `get_lineup_portrait` 是明确的待接入边界，在 Phase 1 验收时返回 None。未知 canonical identity 不请求头像；已知身份也不会调用 Spine 大立绘链，不猜任何资源文件名或 Costume。
- T2IAssetResolver 接受本地 Path / PIL；先检查文件与像素上限、缩放为不超过 272×236 的 PNG，再编码 Data URI。LRU 默认最多 32 项、8 MiB，键包括源像素 hash、源尺寸、目标尺寸和格式，缓存访问带锁。
- 头像失败保留名字、等级、精确战力；未知名字显示“身份未确认”，不泄露 TID。单张资产失败不影响其他成员。

## Campaign 合同

画布 1600×880；Stage / Mode 第一视觉，五人阵容第二视觉，右上 TOTAL CP 为重要数字。五列固定对应 Builder 排好的 Slot 1–5。名称、LV、成员 combat 均从 DTO 取得，总战力只使用 `record.total_combat`，不建立第二套业务合计。NORMAL / HARD 有明确文字和不同强调色。

没有推荐战力、Delta、通关时间、星级等 DTO 不存在的字段。UPDATED 仅表示 DTO 的 fetched_at，标注 UTC+8。没有内部 Stage ID、TID、OL、装备、技能或面板三维。

合成常规 fixture 五人值为 232,663 / 258,765 / 260,154 / 265,133 / 269,885，总计 1,286,600；不是账号数据或官方战力事实。`partial-data` 表示身份解析缺失，仍有完整五人 combat；没有新增业务 Partial 状态。所有正常预览使用中性占位，不能当作正式头像验收。

为避免固定画布静默截断，超过当前可读版面预算的角色名（36 字符）、成员战力（9 位十进制数）或指挥官名（80 字符）会使 T2I 适配失败，使用原 DTO 回退 Pillow。这只是展示能力边界，不是 API / DTO 数值上限；不修改、缩写或删掉真实数据。后续扩大预算必须带完整字号和截图验收。

## 复现与验证

离线测试使用 fake html_render，不访问公开 T2I。测试覆盖原生参数、JSON 序列化、自包含模板、显式转义、NORMAL / HARD、五槽位、精确数字、已知与未知身份、PIL / Path 预处理、有界缓存、局部资产失败、超时、取消、默认 Pillow、原生成功，以及命令级失败仅请求一次 API、同一 DTO 回退。

预览命令（在包根目录，使用已安装 AstrBot / Jinja2 / Pillow 的 Python）：

```text
python scripts/preview_t2i_ui.py --output-dir <输出目录> --fixture all
```

只导出离线 HTML / payload 时加 `--html-only`。脚本复用生产 adapter、loader、asset resolver 和 CSS；原生截图调用 `Star.html_render(..., return_url=False)`，不构造 NikkePlugin、不启动账号服务。它只发送仓库内合成 fixtures。输出包括原始 PNG、50% / 30% 检查图、HTML 与 JSON；PNG 尺寸不是 1600×880 时直接报错。

本次本地证据目录：`E:\DevCache\nikke-t2i-phase1\preview`。8 组 fixtures 为 normal、hard、long-text、missing-asset、partial-data、empty、error、max-density；全部生成原生 PNG。已人工检查代表性原图与缩略图：未见文字裁切、卡片溢出或破图；30% 可识别页面、Stage / Mode、五人结构、TOTAL CP 和状态，50% 可读主要队伍数据，100% 可读细节。没有要求 30% 读清成员名字和全部数字。

此外，另一已安装 AstrBot 环境生成 `preview313/normal.png`，确认其原生接口可用。截图中字体由 AstrBot 渲染环境提供；其他部署环境仍需检查中文字体和实际输出。

## 真实边界与下一阶段

1. Phase 1 验收时尚未集成正式 compact official portrait resolver。当时中性占位符合该阶段授权，不能声称已完成官方头像资源链。
2. 已检查的 AstrBot 实现将 custom HTML 委派给 network_strategy，local_strategy 的自定义 HTML 尚未实现。因此本次原生截图由 AstrBot 管理的网络渲染路径生成；插件没有添加本地浏览器或覆盖框架策略。离线 local HTML 能力属于框架边界，不能声称已验证。
3. 某已安装 AstrBot 版本会预处理 HTML 并注入代码高亮脚本；插件模板自身没有 JS，CSP 禁止脚本执行。已验证无外部资源引用与实际出图，但公开服务没有返回浏览器网络追踪，因此没有独立网络 trace 证据。页面无需任何外部资源；与原生渲染服务本身的通信不是图片子资源加载。
4. v0.8 部分旧验收文字提到“可靠星级”，但当前 StageClearRecord 没有星级；依照用户指定的真实代码优先原则隐藏，不补字段。其他页面中的旧描述不在本阶段改写。
5. 该阶段基础设施随后用于 Calendar 实现，但 Calendar 必须重新按现有 CalendarService 的 7 / 14 / 30 天、默认 14 天、Ending Soon / Active / Upcoming 合同建立适配器，不能套用旧 Active-only 描述。本阶段没有开始 Calendar 实现。

本地验证不等同于 GitHub CI、部署或 QQ 实机验收；本阶段未推送、提交 PR、部署或发送消息。

## 本次验证结果

- Python 3.13 全量 pytest：697 passed，485 subtests passed；日志 `E:\DevCache\nikke-t2i-phase1\full-tests313-final.log`。
- 既有浏览器绑定扩展测试：4 passed；日志 `E:\DevCache\nikke-t2i-phase1\extension-tests.log`。
- Python 3.10 编译检查通过；原生截图在已安装的两个 AstrBot 环境成功。Python 3.10 测试环境缺少 pytest-asyncio，首次定向测试的 12 项异步用例未执行成功，随后改用已有完整 Python 3.13 环境验证，没有删除或弱化异步测试，也没有声称运行完整 Python 版本矩阵。
- 原有配置合同测试新增 `ui_renderer` 的预期键，并同步配置文档，保留精确键集合校验。
- 未运行与本改动无关的 Spine Docker 构建和真实 QQ 验收；未声称 GitHub Actions 已通过。
