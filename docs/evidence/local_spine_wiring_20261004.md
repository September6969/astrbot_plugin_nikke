# 本地 Spine 生产入口验证

基线：8ac6a5f706003618081d1f330ac8b744e683ea7e。

角色卡未命中已登记 portrait 时，优先读取服务器 `/AstrBot/data/vendor/nikke-db` 的 canonical bundle。资源经现有 resolver 校验后复制到 worker 受限缓存目录，使用实际 skeleton 版本、idle 和独立 skin 身份渲染。缓存身份包含输入内容哈希、runtime 和 renderer 版本。存在但无效的本地 bundle 返回 fallback。

2026-10-04 在 AstrBot 容器内以隔离代码副本验证 resource_id=191、默认服装：上游解析入口被设置为立即失败，实际未触发；冷渲染 1.500 秒，热缓存 0.050 秒，输出 529×980。日志分别记录 `LOCAL_SPINE_PORTRAIT: render_id=c191 result=rendered` 和 `result=cache_hit`。已实际查看生成图。

这证明本地输入和真实 worker 的渲染链路；QQ 卡片实际送达仍由用户复测。

定向测试：58 passed，8 subtests passed。compileall、扩展 JS 语法检查和 diff-check 通过。
