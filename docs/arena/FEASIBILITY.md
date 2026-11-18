# 可行性与基线

实施日期为 2026-11-17。工作目录初始为空，按用户给定计划获取目标仓库。

| 项目 | 固定版本 |
|---|---|
| astrbot_plugin_nikke | ede461f5550c67b33d2251b3025b8e19daef01a5 |
| nikke-pvp-counter | 60f8ac56b6c0660f702d74b89d36ade53ff6a8ca |
| nikke-arena-planner | c7948fb4b8778efde16320768a2159eb500e4216 |

## 已落实的集成切面

Help 的内容和渲染放在 features/help。application/commands/help.py 提供展示桥，以遵守现有 command_runtime 禁止直接导入领域实现的架构检查。分类帮助及历史别名继续进入原路由。首页调整为三条常用查询和教学入口。

Arena 领域层只依赖标准库及原有角色身份模块。角色名单通过 get_roster(include_details=False) 读取，沿用原网关 30 秒缓存、账号身份分区及并发请求合并。

Web 通过 BindingWebService.add_route_installer 注册独立路由。绑定服务只管理挂载与生命周期。原有 /bind 和 /api/bind 路由保持原来的处理过程。Arena 自行执行严格 Origin 与 CSRF 校验。

服务端草稿、会话、幂等结果均为有界内存数据。重启清空。基础文字计算不依赖 Web 会话或统计站点。

## 证据与当前缺口

已构建 20 个锁定源码的机械规则黄金样本，测试输入覆盖站位轮换、再入和条件 B1。样本声明为机械输出，未附加真实胜负标签。

初次服务器名单探测返回 CookieExpired。2026-11-17 19:58 PST，用户使用真实绑定账号确认 `竞技场 我的` 返回 同时包含已映射和未映射角色。角色映射使用 `name_code`。原始角色条目未纳入验收记录。

用户确认已咨询并获准使用 nikkeari。早期请求未带赛事登记阶段，因而返回空对位。按公开页面的口径指定 `legacy` 后，GLOBAL β40 赛事 175 返回 315 条对位，其中 305 条可映射。空响应不会覆盖已有统计快照。

用户允许使用 SSH 服务器和模拟消息代替本轮真实 QQ 会话验收。QQ 手机 WebView、原生参数分词及实际消息送达的实机结果仍待记录。

计划引用的 NIKKE_HELP_DETAIL_PLAN.md 未随文件提供，帮助细节按 V3 主文及实际可执行路由实施。
