# 历史资料归档索引

这些文件保留历史调查、截图、样本、验收报告及当时的工具路径，不代表当前版本已经通过原生集成验收。归档内容按原始字节保留；同名目录合并前逐文件比较，内容相同可去重，内容不同保留独立名称。

| 原位置 | 归档位置 |
| --- | --- |
| `docs/evidence/` | [evidence/](evidence/) |
| 根 `eunhwa-tactical-upgrade/` | [evidence/eunhwa-tactical-upgrade/](evidence/eunhwa-tactical-upgrade/) |
| Git 跟踪的根 `reports/` | [reports/](reports/) |

[逐文件迁移清单](MIGRATION_MANIFEST.json)记录原位置、新位置、Git 原始字节 SHA-256、Git blob 标识、Windows 原检出字节哈希及合并处理。原报告内的旧命令或绝对路径作为历史记录保留，请从[开发工具导航](../../scripts/README.md)查找现行入口。

CI 所需 10 份固定输入位于 `tests/fixtures/spine/` 、`tests/fixtures/costume/` 与 `tests/fixtures/character/`，共 1,584,776 字节。它们来自归档中的原始 JSON，与来源 Git blob 字节一致、跨平台固定 LF；[来源表](../../tests/fixtures/repository_organization_sources.json)保留来源提交、归档路径、大小及 SHA-256。CI 使用这些独立输入，不读取完整历史证据目录。

`evidence/` 和 `reports/` 在 `.gitattributes` 中标记为 `export-ignore`，因此保留在 GitHub 与 Git 历史里，但不进入 `git archive` 发行包。此安排不会减少已有 Git 历史的克隆体积。字体、素材、模板和许可证仍随发行包提供。
