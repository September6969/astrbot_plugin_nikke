# Post-Refactor Spine Resource Coverage — Phase 2

本目录记录 PR #105 合并后的 bundled Spine 资源复核。基线为 `main` 的 `c3c7dba1de3c5b804a076b20cf8f3ecc472f5a51`；审计不含 PR #101 的 runtime warm/cache 工作，也不触碰线上服务或账号。

## 结论

- 固定 Nikke-db 快照：`6e6ee77ff76ec6f9003953fbcdb3768248cbda04`。只核验本次范围内 28 个 skeleton、28 个 atlas 及 atlas 引用页；校对 Git blob SHA-1、文件大小和 generation metadata 中的 SHA-256。网络数据未写入仓库。
- 27 个 PNG 的 identity、图像完整性、Face Anchor generation record、Spine runtime 与 pinned skeleton/atlas 输入记录一致，已显式加入两个同步 manifest。分类结果本身不会自动提升资源。
- `c191` 保持拒绝：skeleton 匹配，但 atlas 的 generation record SHA-256 为 `bc1aab5ade310ce5a6c3276e7417b82e34cf7bad32f8f5381921dee9aae5254d`，当前固定上游 atlas SHA-256 为 `ecebe8eafd7b0cba693eb60e4f6aab490c0bd80a22f773f50abc8abbb7195be9`。它不在 manifest，生产 loader 不会信任其 PNG。
- 历史 generation metadata 没有独立记录渲染器二进制 SHA-256；本次不声称证明了渲染器可执行文件身份。证据覆盖固定源文件、generation 参数/运行时记录、输出 PNG/像素哈希与 anchor 绑定。
- 未下载、生成或自动登记 340 个缺失资源；它们继续等待逐项人工来源与 framing 审核。

## Promotion inventory

已登记的 27 个 render ID：

`c011`, `c012`, `c016`, `c070`, `c072`, `c080`, `c082`, `c100`, `c101`, `c102`, `c110`, `c111`, `c120`, `c140`, `c161`, `c170`, `c172`, `c180`, `c181`, `c220`, `c221`, `c222`, `c224`, `c233`, `c270`, `c310`, `c400`。

`c191` 为唯一 source-mismatched PNG，未登记。`assets/spine_manifest.json` 与其默认镜像 `assets/data/spine_manifest.json` 必须保持相同内容；本轮两者均为 38 项。

## Coverage snapshot

“旧 #102”列复述 2026-09-23 历史审计数值；它与 post-refactor canonical 数据和新集合定义并非完全同口径。Phase 2 delta 列只比较本分支登记前后、同一审计器/快照。

| Metric | 旧 #102 历史值 | Phase 2 登记前 | Phase 2 当前 | Phase 2 delta |
|---|---:|---:|---:|---:|
| Canonical Character resources | 200 | 378 | 378 | 0 |
| Upstream L2D IDs | 558 | 558 | 558 | 0 |
| Manifest render IDs | 11 | 11 | 38 | +27 |
| Bundled PNG IDs | n/r | 39 | 39 | 0 |
| Face Anchor IDs | n/r | 39 | 39 | 0 |
| Trusted semantic Core Axis IDs | n/r | 2 | 2 | 0 |
| Upstream-complete IDs missing from manifest | 191 | 367 | 340 | -27 |
| Orphan manifest IDs | 2 | 0 | 0 | 0 |
| Render asset gap | 81 | 367 | 340 | -27 |
| Unsupported | 0 | 0 | 0 | 0 |
| Undeclared bundled PNGs | n/r | 28 | 1 | -27 |

集合定义：

- `Missing Manifest`: 固定快照中拥有完整 upstream L2D bundle、由当前 canonical consumer 使用，但缺少 manifest entry 的 render ID。
- `Orphan Manifest`: manifest entry 经默认与 costume/alternate consumer 检查后，找不到任何当前 canonical consumer 的 render ID。
- `Render Asset Gap`: 上述 `Missing Manifest` 集合；要求 upstream 完整 L2D bundle，但当前没有经 manifest 验证的 bundled portrait。
- `Unsupported`: 明确分类为不支持的当前 canonical render identity；未将待审资源或缺图伪装成 unsupported。
- `Undeclared PNG`: 磁盘有 PNG，但不在 manifest。当前唯一值为 `c191`，并由测试确认 `SpineManifestStore` 拒绝加载。

当前快照计数：378 个 canonical consumer、558 个 upstream complete bundle、38 个 manifest、39 个 PNG、38 个 verified manifest PNG、39 个 anchor、2 个 trusted semantic Core Axis、340 个 missing manifest/render gap、0 个 orphan、0 个 unsupported；另有 1 个未声明且无效的 `c191`。

## 保持的 framing 合同

- `c018`: `resource_id=18 → render_id=c018`；L2D 存在、FB 不存在；Spine 4.1；PNG SHA-256 `045b0b3b568e7a2731ea42fb35b35b418e75f845842c889f22ac5963e58a33c5`，2536×3830；Face Anchor `anchor_available_head_only`；Core Axis `unavailable`。不推测躯干/核心语义轴。
- `c401` Sin 与 `c581` Arcana 保持已验证 semantic framing，不降级为 generic head-only。
- 验收图只经过当前白色竖版 T2I 角色卡路径。图像由 sanitized fixture 产生，不使用真实账号或游戏数据。

## Evidence files

- `render-source-verification.json`: 28 个候选的 pinned source 核验；其中 27 个 generation inputs 匹配，`c191` 不匹配。
- `undeclared-png-audit.json`: 提升 manifest 前，对 28 个 PNG 的穷尽分类；27 个候选、1 个无效资源。
- `coverage-summary.json`: 当前 manifest 下的可复现完整集合报告。
- `c018-character-card-diagnostic.json`: c018 portrait、anchor/framing 和白卡预览哈希/尺寸诊断。
- `c011-character-card.png`, `c018-character-card.png`, `c401-character-card.png`, `c581-character-card.png`: 当前 renderer 生成的 1600×2400 白色竖版卡片预览。

在仓库根目录重新生成当前审计与 c018 诊断：

```powershell
python scripts/audit_spine_resource_coverage.py `
  --output docs/evidence/spine_resource_coverage_phase2/coverage-summary.json `
  --undeclared-png-output docs/evidence/spine_resource_coverage_phase2/undeclared-after-phase2.json `
  --markdown-output docs/evidence/spine_resource_coverage_phase2/coverage-summary.md `
  --character-card-preview docs/evidence/spine_resource_coverage_phase2/c018-character-card.png `
  --diagnostic-output docs/evidence/spine_resource_coverage_phase2/c018-character-card-diagnostic.json
```

可离线复跑的审计输入是仓库内 pinned upstream snapshot；普通测试/审计不访问外网。只有明确传入 `--refresh-upstream` 才会调用 GitHub API。
