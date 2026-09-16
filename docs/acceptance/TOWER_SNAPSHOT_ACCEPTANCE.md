# 塔层静态快照合同验收

## 范围

本主题从 `origin/main` 的 `bada0b3` 独立建立。它只加固 `/妮姬 塔层` 所读取的仓库静态快照合同，不更新塔层数据，不请求公开来源，不读取账号，也不发送消息。

## 已验证行为

- 当前内置快照的 7,350 条记录可以完整通过元数据、键、唯一 `stage_id` 与正整数战力校验。
- 缺失/损坏元数据、非规范日期或 hash、重复 JSON 键、错误键、布尔战力、重复 `stage_id` 会在加载时拒绝。
- 损坏快照在命令层安全返回“塔层静态资料暂不可用”，不会显示局部记录或猜测数据。
- 塔名和层数只接受明确语义；非字符串、带符号、全角数字或前导零层号不会被静默归一化。
- 正常命令仍能查询已登记的静态塔层；未知但语义有效的层数仍明确说明未收录。

## 本地证据

```text
python -m pytest -q tests/test_tower_registry.py
5 passed, 2 warnings, 11 subtests passed

python -m pytest -q
259 passed, 2 warnings, 54 subtests passed

node --test tests/extension.test.cjs
3 passed

python -m compileall -q .
git diff --check
通过
```

还使用内置快照实际读取了 `极乐净土 1`：输出为 `7,740` 标准战力和 `2026-09-05` 快照日期，并保留“不是通关保证，也不代表你的进度”的边界提示。

全量 pytest 的标准输出在外部 AstrBot/SQLAlchemy 导入阶段包含 Windows native access-violation trace，但进程最终退出码为 0，所有 259 个断言通过；该环境噪声不作为产品运行时证据。

## 边界与后续

本验收只证明内置静态文件和离线命令行为。它不证明来源仍可访问、快照最新、素材或数据授权，也不证明真实账号塔层进度。更新数据时应保留来源、采集日期和规范化来源 hash，并重新运行本合同测试。
