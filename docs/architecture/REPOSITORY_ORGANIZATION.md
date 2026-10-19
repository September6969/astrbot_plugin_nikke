# 仓库结构与迁移

此次整理以 `de54408543b21d32d278c177450019f69752ccf9` 为基线，保持业务分层、命令行为、界面模板和素材质量。

```text
astrbot_plugin_nikke/
├── main.py / __init__.py / container.py / metadata.yaml / _conf_schema.json
├── adapters/ application/ core/ features/ integrations/ ui/
├── assets/
│   ├── fonts/                 字体、来源及许可证
│   ├── blablalink/            受控内置素材
│   ├── manifests/blablalink/  受控上游清单
│   ├── data/ mappings/ icons/ …
├── templates/                运行模板
├── extension/ runtime/spine_worker/ deploy/
├── scripts/                  分类实现及旧命令兼容入口
├── tests/fixtures/            独立固定输入与来源哈希
├── docs/
│   ├── architecture/ contracts/ acceptance/ ui/ operations/ research/
│   └── archive/evidence/ archive/reports/
└── output/                   忽略的本地生成输出
```

## 迁移映射

| 原路径 | 当前路径 |
| --- | --- |
| `fonts/` | `assets/fonts/` |
| `data/nikke/blabla-assets/` | `assets/blablalink/` |
| `data/nikke/blabla-manifests/` | `assets/manifests/blablalink/` |
| `docs/evidence/` | `docs/archive/evidence/` |
| 根 `eunhwa-tactical-upgrade/` | `docs/archive/evidence/eunhwa-tactical-upgrade/` |
| 受控 `reports/` | `docs/archive/reports/` |
| `scripts/<工具>` | `scripts/<分类>/<工具>`，原命令仍可使用 |

资源与工具的[逐项映射](repository_organization_moves.json)、历史资料的[逐文件哈希清单](../archive/MIGRATION_MANIFEST.json)、测试输入的[来源清单](../../tests/fixtures/repository_organization_sources.json)分别记录迁移范围。只迁移 Git 跟踪的内置内容；宿主数据库、Cookie、用户配置、secret.key、缓存及下载目录不属于本次迁移。

## 路径与兼容

`core.paths` 由源码位置确定插件根目录。字体、素材和清单优先读取新内置位置；旧插件内置目录只作只读回退，不自动探测宿主的 AstrBot 数据目录。显式传入的素材根目录、清单路径和工具输出路径继续有效。

旧清单内的 `data/nikke/blabla-assets/` 相对路径通过图片缓存解析器映射到新内置素材。生成工具的默认素材输出使用 `assets/`，报告和预览使用忽略的 `output/`；需要仓库外新目录的候选批次工具继续保持原有约束。归档只作历史读取输入，不接收新生成报告。

Python 旧命令通过 `scripts/shared/compat.py` 在当前进程执行分类实现，传递原始参数与退出状态，并沿用取消信号；Shell 旧命令通过 `exec` 转发；PowerShell 和 ES 模块保留相应的薄入口。内部调用、CI 和当前文档使用分类路径。[工具索引](../../scripts/README.md)列出所有实现。

根 `container.py` 兼容接口以及 AstrBot 根入口保留；`extension/`、`runtime/spine_worker/`、`deploy/` 保持原位置。未迁移为 `src` 布局，也未批量调整业务模块导入。

## 验证范围

完整性核对以迁移前受控文件的 SHA-256 为准；资源清单的必要路径变化与原始素材分开记录。归档原始文件不改写。固定合成样本通过生产 DTO、payload、模板加载器和渲染器重放，比较文字、尺寸、素材解码及图像像素，并查看原图与 432 像素手机缩图。

本地 Chromium 验证不等同 AstrBot 原生验收；此次不操作真实账号、不发送消息、不合并或部署。公开角色资料与管理员日常汇总的文本表现由既有回归持续约束。
