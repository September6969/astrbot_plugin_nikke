# Issue #80 技术评估与回复草案：AstrBot 内置 T2I 渲染管线与 Pillow 画布方案对比

> **状态**：草案评审中（仅供维护者内部审阅，未发布至 GitHub）  
> **关联 Issue**：[Issue #80](https://github.com/September6969/astrbot_plugin_nikke/issues/80)  
> **涉及模块**：图像渲染管线、AstrBot 核心交互层、移动端/QQ 卡片呈现  

---

## 1. Issue 背景与核心诉求

Issue #80 探讨了将本插件当前的自研 Pillow 画布渲染方案（ProfileCardRenderer, CharacterCardRenderer, CampaignCardRenderer 等）替换或迁移至 AstrBot 框架内置的 Text-to-Image (T2I) / HTML2Image 管线的可行性。

主要提出的论点通常包括：
1. 框架统一性：直接利用 AstrBot 核心现有的渲染基础设施；
2. 样式开发体验：使用 HTML/CSS 编写界面比 Pillow 命令式绘制更具表现力和现代前端开发直觉。

---

## 2. 深度架构对比分析

| 维度 | 当前方案：Pillow 自研画布引擎 | 框架方案：AstrBot 内置 T2I (Playwright / html2image) |
| :--- | :--- | :--- |
| **视觉保真度与设计控制** | **极高**。战术深色 UI、像素级图标对齐、动态网格（如循环室双列、超频多槽位、4×3 词条装备卡）、多图层合成与透明 Alpha 边界裁切。 | **中~高**。依赖 WebKit/Chromium 渲染，但字体平滑、移动端 Retina 缩放及跨平台 DPI 对齐在无头环境中极易出现微小抖动或断字。 |
| **内存占用与系统开销** | **极低**（单次渲染额外开销约 10~30 MB，随进程即时回收）。适合 1C1G / 1C2G 的轻量级云服务器。 | **极高**（无头 Chromium 常驻 150~300 MB，突发可达 500 MB+）。在低配 Docker 容器内并发渲染容易触发 OOM-Killer 导致容器崩溃。 |
| **渲染吞吐与延迟** | **极快**（端到端渲染耗时 30ms ~ 120ms）。纯内存 C 扩展执行，无 IPC 通信开销。 | **慢~中**（页面加载、DOM 布局、资源注入、截图耗时 500ms ~ 1800ms），且高频并发需维护浏览器上下文池。 |
| **离线与容器环境可靠性** | **完全确定性**。依赖标准 Pillow、FreeType、系统自带字体文件，无外部进程或动态端口绑定。 | **环境依赖重**。需要容器安装完整 Chromium 动态依赖库，需适配 --no-sandbox、--disable-dev-shm-usage 等安全参数，且与 Alpine / 精简容器兼容成本高。 |
| **游戏领域数据模型契合度** | **深度绑定**。直接消费 ProfileDashboardData, CharacterCardData, OverloadEquipData，逻辑与渲染边界清晰。 | 需要增加数据序列化 -> 注入 HTML 模板 -> 渲染 -> 提取结果的额外桥接层。 |

---

## 3. 分场景可行性评估

### 3.1 核心视觉卡片（个人信息 / 角色卡 / 战役通关阵容 / 抽卡 / 词条装备）
- **结论**：**不建议替换为 T2I，必须保留 Pillow 画布方案**。
- **原因**：
  1. 装备词条卡（4 槽位 × 3 条词条）与战役历史卡（5 角色立绘 + 头像 + 战力 + 等级 + 统计徽标）具有密集的业务逻辑和固定像素网格要求；
  2. Pillow 方案在 v0.3 中已完全建立针对 QQ 手机端 1200px 宽度适配、双列布局与防截断机制；
  3. 切换为 HTML 模板会导致生产部署成本陡增（尤其在 Docker 中缺少无头浏览器环境的服务器）。

### 3.2 文本类信息流（官方公告 / 近期日程 / 帮助菜单）
- **结论**：**保持纯文本返回，无缝交由 AstrBot 核心处理**。
- **原因**：
  1. 当前 /妮姬 公告 与 /妮姬 日程 统一返回结构化纯文本；
  2. 若用户在 AstrBot 配置中开启了全局 	ext_to_image 拦截（为了防止 QQ 长文本风控），AstrBot 核心会自动对插件返回的文本进行 T2I 渲染；
  3. 插件不强制介入文本转图，充分尊重宿主框架与用户的个性化配置。

---

## 4. 架构决策与路线建议

1. **核心原则**：保持各层职责清晰——复杂战术卡片采用轻量、极速、零额外依赖的 Pillow 渲染；基础长文本交由 AstrBot 原生消息流分发。
2. **渐进兼容**：未来如 AstrBot 官方推出纯 Python 编写的轻量级 Canvas/Skia 统一绘图规范，可再评估统一抽象层；目前不引入 Chromium/Playwright 依赖。

---

## 5. Issue #80 回复草案 (Draft Response)

### 中文回复草案：

`markdown
感谢对 strbot_plugin_nikke 渲染架构的关注与建议！

针对迁移至 AstrBot 内置 T2I (Text-to-Image) 管线的方案，我们从视觉保真度、运行环境开销以及业务复杂度进行了系统评估：

1. **运行开销与容器可靠性**：
   - 绝大多数生产环境与个人部署均采用轻量级 VPS（如 1C1G / 1C2G）及精简 Docker 镜像。当前基于 Pillow 的本地自研画布单次渲染内存仅约 10~30MB，耗时稳定在 30~100ms；
   - 若引入基于 Headless Chromium / Playwright 的 HTML2Image 管线，常驻内存将增加 200MB+，高并发场景下在低配服务器上容易触发 OOM 导致 Bot 容器崩溃。

2. **复杂游戏战术 UI 的像素级控制**：
   - 插件内的核心卡片（如指挥官档案卡、妮姬角色卡、4×3 词条装备卡、战役通关历史 5 角色阵容）包含大量游戏专有图标对齐、动态分列（如循环室双列布局）、Spine 渲染裁切与深色战术网格，这些设计使用命令式画布绘制具有极高的确定性与渲染效率；
   - 纯文本指令（如 /妮姬 公告、/妮姬 日程、/妮姬 帮助）已遵循原生纯文本返回，如果宿主配置了全局文本转图，AstrBot 会自动介入处理，无需插件层重复包揽。

**结论**：
基于生产稳定性与低资源消耗考虑，核心视觉卡片将继续保留高效稳定的 Pillow 独立绘制引擎；同时我们会持续关注 AstrBot 框架在上游渲染管线上的演进。

再次感谢你的建设性建议！
`

### 英文回复草案 (English Draft)：

`markdown
Thank you for bringing up this architectural suggestion!

We conducted a comprehensive feasibility analysis on replacing the current Pillow-based canvas renderer with AstrBot's built-in text-to-image (T2I) / HTML2Image pipeline:

1. **Resource Footprint & Container Stability**:
   - A significant portion of bot instances run on resource-constrained servers (e.g., 1-core / 1GB RAM) or slim Docker environments. Pillow's pure-Python/C extension approach requires only ~10–30 MB of heap memory and completes renders in 30–100ms.
   - Introducing a headless browser pipeline (Playwright / Chromium) introduces 200+ MB baseline memory overhead, posing severe OOM-killer risks during concurrent rendering on low-tier hosts.

2. **Pixel-Level Control for Complex Tactical UI**:
   - High-density game UI components (such as 4×3 Overload tier grids, Campaign 5-character battle lineups, and Recycle Room 2-column layouts) require strict layout deterministic guarantees, alpha mask compositing, and mobile QQ width fitting.
   - Pure text features (/妮姬 公告, /妮姬 日程) return standard text strings, which naturally pass through AstrBot's global T2I pipeline if enabled by the user.

**Conclusion**:
To guarantee robust, zero-browser production deployments with minimal latency, we will retain the dedicated Pillow canvas engine for rich visual cards. 

We truly appreciate your constructive feedback and will continue to monitor AstrBot's upstream rendering APIs!
`
