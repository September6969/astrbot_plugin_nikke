# 日志隐私 V1 验收记录

## 范围

本主题只处理插件自身写入的 Python 日志调用点，不改变 AstrBot 或宿主日志系统的全局配置，也不访问真实账号或线上日志。

## 合同

- 异常文本在进入插件日志前必须经过 `safe_exception_message`。
- 脱敏摘要保留异常类型，换行被压平，长度默认不超过 240 个字符。
- `token`、`cookie`、`authorization`、密码、密钥、`openid`、账号标识、Cookie 字段、查询参数凭据及邮箱值不得出现在摘要中。
- 资源键和 Spine 缓存键等动态日志字段使用同一脱敏器并限制长度。
- 仅为记录异常而使用的 `logger.exception` 不再输出原始 traceback；日志保留异常类型和安全摘要，避免 traceback 中的外部文本绕过脱敏。
- 诊断回调仍只记录接口名、请求字段名、业务码和响应字段名；本主题不把合成测试称作真实联调。

## 实现

- 新增 `log_privacy.py`，集中实现日志文本脱敏和异常摘要。
- 主流程、公告缓存、素材管理、Spine 预渲染及延迟反馈的动态日志已接入。
- 公告同步失败返回给命令调用方的错误摘要也使用相同边界，避免把异常原文回显。

## 离线验证

- `tests/test_log_privacy.py` 验证普通键值、JSON 字符串/数字标量、查询参数、邮箱、异常长度上限、联盟突袭用户错误摘要，以及公告同步实际 logger 输出均不包含敏感值。
- 专项日志隐私测试：7 passed；公告服务回归：15 passed、24 subtests；JSON 形式的 `game_token`、`game_gameid` 与 `x-common-params` 也会遮盖。
- 仅使用合成异常和本地日志捕获；没有真实账号、真实 Cookie、公开资源授权或部署证据。
- 现有 PR CI run `34146296068` 已完成 Python 3.10/3.11/3.12 与 Node 检查，四项均为 SUCCESS。

## 当前补充验证（2026-09-07）

- 工作分支：`feat/log-privacy-v1`；基线：`origin/main@bada0b3aafcd7127d07ca40f554808b0433540f8`；Draft PR：#26；当前 head：`bc426ac`。
- 在本地 Python 3.10.11 + AstrBot 4.14.6 环境运行 `pytest -q`：`262 passed, 43 subtests passed, 2 warnings`。
- 同一环境的 `python -m compileall -q .`、`node --test tests/extension.test.cjs`（3 passed）和 `git diff --check` 均通过。
- 两个 warning 分别来自 FAISS/NumPy 依赖和当前基线仍使用的 `register_star` 弃用提示；没有日志隐私断言失败。
- 证据仍仅限本地合成异常/日志捕获和 CI，不包含真实账号、真实线上日志、消息发送、部署或生产迁移。
