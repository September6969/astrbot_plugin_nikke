# Spine 技术预研验收

基线：`origin/main` `bada0b3aafcd7127d07ca40f554808b0433540f8`。

## 当前验证

- 本地 Python 3.10.11：`python -m pytest -q` → 265 passed，2 warnings，53 subtests passed。
- Spine 专项：`python -m pytest tests/test_spine_spike.py` → 9 passed。
- 扩展行为：`node --test tests\\extension.test.cjs` → 3 passed。
- `python -m compileall -q .` 与 `git diff --check` 通过。
- 本次文档修订前的代码检查点为 `137b931`，对应 CI run `34115112516`；文档提交后的最终 head 与 CI 必须重新查询，不能在此处自引用未来提交。

## 本次已完成

- [x] 新增独立 `SpineEvidenceReport`，把预检查和真实运行结果分开。
- [x] 预检查暴露本地输入、bundle 完整性、观测版本及未执行证据层。
- [x] 队列保留 per-key 去重、容量上限和 1～2 worker 约束。
- [x] 队列支持显式启动、`wait_idle()`、状态查询和不遗留 sentinel 的优雅停止。
- [x] 任务总预算在进入队列前即开始计时；过期任务回调 `None` 且不调用 runner。
- [x] 队列入口拒绝布尔/非整数容量、空白任务标识、路径型 `cache_key` 和异常预算类型，避免异常数值或路径语义穿透。
- [x] 增加合成 atlas/JSON、队列去重/满载/预算/生命周期行为测试。
- [x] 未修改生产出卡默认路径，未安装或执行 Spine runtime。

## 仍未完成或需要现场/人工决定

- [ ] 许可明确的测试 Spine bundle。
- [ ] 选定并授权具体 runtime 与版本兼容表。
- [ ] Linux headless 真实加载和多纹理测试。
- [ ] 真实透明 RGBA render、crop、PNG cache 写入证据。
- [ ] queue/load/parse/texture/render/crop/encode/cache 的现场 benchmark。
- [ ] 生产接线、超时降级和产品 readiness 决策。

## 验证边界

本地测试只使用临时目录中的自创建文本 fixture 和 Python/Pillow 行为；没有访问真实账号、生产资源、消息发送或部署环境。因此本文件的已完成项不能表述为真实联调、产品完成或资源授权。
