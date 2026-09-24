# Post-Refactor Spine Resource Coverage

本目录固定离线 coverage audit 使用的 Nikke-db upstream 文件树快照。该快照由显式维护命令读取 GitHub API 后生成；常规测试与审计只读快照，不依赖外网，也不会下载或修改角色资源。

本次资源覆盖收口是 #103 合并后的独立 follow-up。旧 #102 的提交 `0717076` 与 merge commit `771f43e` 是历史证据，不是新实现模板。c018 原始肖像 SHA-256 `045b0b3b568e7a2731ea42fb56b35b418e75f845842c889f22ac5963e58a33c5` 经 post-refactor 复算一致。

## 当前 ownership

| Responsibility | Current owner |
|---|---|
| `resource_id` → canonical Character identity | `features/character/master_resolver.py` 与 `assets/data/character_master.json` |
| Character/costume → `render_id` | `integrations/nikke_db/provider.py:NikkeDbProvider.resolve_render_id()`；Costume 映射由同 provider 校验 |
| Bundled manifest 声明与完整性验证 | `core/assets/spine_manifest.py:SpineManifestStore` |
| 静态 PNG 消费与 fail-closed | `core/assets/spine_assets.py:SpineAssetService` |
| AssetManager facade / shared resource ownership | `core/asset_manager.py:AssetManager`，委托给 `core/assets/` 组件，不自行解析或信任裸 PNG |
| Upstream Nikke-db tree 与 Spine bundle 获取 | `integrations/nikke_db/`；本任务 coverage snapshot 仅由显式维护命令从 GitHub API 刷新 |
| Spine runtime/version metadata | `integrations/spine/` 的检测器与 manifest/已验证 Face Anchor metadata |
| Face Anchor 与 framing | `features/character/face_anchor.py` 和 `assets/data/face_anchors.json` |
| Semantic Core Axis | `features/character/spine_core_axis.py` 与已验证 mappings；无可信骨骼/attachment 证据时为 unavailable |
| 白色单角色卡消费路径 | Character application → payload builder → `templates/t2i/character.html` → AstrBot `html_render` |
| 可重复 coverage audit | `scripts/audit_spine_resource_coverage.py`，默认离线只读 |

## 当前集合定义

固定 upstream 文件树来自 `Nikke-db/Nikke-db.github.io` 的 `main` commit `6e6ee77ff76ec6f9003953fbcdb3768248cbda04`，抓取时间 `2026-09-24T04:43:15.68183-07:00`。coverage refresh 需显式执行，不由测试或默认审计联网。

- Character resources：当前 Character master 中唯一的默认 `resource_id`。
- Render consumers：默认角色加当前生产 `NikkeDbProvider` 已验证的 costume 映射。
- Upstream L2D：快照中出现 `l2d/<render_id>/` 文件的唯一 ID；完整 bundle 还要求该目录根部至少有 `.skel`、`.atlas`、`.png`，纹理名允许与 skeleton 名不同。
- Missing Manifest：生产 resolver 可解析且 upstream bundle 完整，但 manifest 未声明的 render ID。
- Orphan Manifest：manifest ID 不被当前默认角色或已验证 costume 的生产 resolver 消费；costume/alternate ID 不因与默认 ID 不同而被误判。
- Render Asset Gap：生产 consumer 有完整 upstream bundle，但缺少完整性验证通过的 manifest PNG，且没有显式 unsupported 分类。
- Unsupported：仅统计 master 明确标记 `spine_support_status=unsupported` 且提供原因的默认角色。
- Undeclared PNG：`assets/spine-rendered/` 中不在 manifest 的文件；文件存在不构成信任或生产可用性。

## 本次重算摘要

| Metric | 旧 #102 快照 | post-refactor 当前值 | 对比 |
|---|---:|---:|---:|
| Character defaults | 200 | 200 | 0 |
| Canonical render consumers（新增统计） | — | 378 | — |
| Upstream L2D IDs | 558 | 558 | 0 |
| Manifest render IDs | 11 | 11 | 0 |
| Bundled PNG files（新增统计） | — | 39 | — |
| Verified manifest PNGs（新增统计） | — | 11 | — |
| Face Anchor records（新增统计） | — | 39（39 identity-valid） | — |
| Trusted semantic Core Axis（新增统计） | — | 2：c401、c581 | — |
| Missing Manifest | 191 | 367 | +176 |
| Orphan Manifest | 2 | 0 | -2 |
| Render Asset Gap | 81 | 367 | +286* |
| Manual Review Required | 191 | 367 | +176* |
| Unsupported | 0 | 0 | 0** |

`Missing Manifest` 的增加主要因为当前审计纳入了 178 个经过生产 resolver 验证的 costume render consumer；旧算法没有按完整身份链统计它们。旧 2 个 orphan 是合法 costume/variant consumer。`Render Asset Gap` 的旧算法将“默认角色未命中默认 portrait”作为 gap，新定义按完整 upstream bundle + verified manifest portrait + explicit unsupported 集合计算，`+286` 仅是算术差，不代表同一口径下的回归量。旧 Unsupported 的分类口径也不完整，因此 `0**` 只作数字对照。

coverage JSON 的 `manual_review_required` 为每个 uncovered render ID 列出当前默认/costume consumer 和原因。所有 367 个项目仍需人工视觉/来源复核；本次没有批量生成肖像、猜测 Face Anchor 或 Core Axis。

## c018 当前合同

- `resource_id=18 → canonical character neon_vision_eye → render_id=c018`。
- 当前固定 upstream snapshot：Spine/L2D 存在，FB 不存在；runtime `4.1`。
- PNG 为 manifest 声明且通过 raw SHA、尺寸和图像完整性验证；当前尺寸 `2536×3830`，alpha bbox `[64,64,2472,3766]`。
- Face Anchor 身份绑定 raw PNG SHA、RGBA pixel SHA 与尺寸；状态 `anchor_available_head_only`，framing source `eye_attachment`。本次按同一 Spine Core skeleton 的 `point_1024` 和原始渲染 alpha crop `[848,196,3256,3898]`、64 px padding 复算裁切后 face point 为 `[467.2466204157688,592.8506619118557]`；现有旧记录漏减 crop origin，已修正。回归测试验证该坐标映射及其在白卡中的目标点。
- Core Axis `unavailable`，原因 `upper_torso_unavailable`。没有由外观、alpha bbox 或画面中心推测 torso/chest/waist/pelvis。
- c401 的 verified `body_total` override 与 c581 的 verified `chest_l+chest_r` semantic axis 保持有效。
- 当前白色角色卡通过唯一生产链消费：`CharacterApplication → CharacterCardData → asset resolution → CharacterT2IPayloadBuilder → templates/t2i/character.html → AstrBot html_render`。没有旧静态卡片或并行资源 resolver。

## 可重复生成

默认 coverage 命令是离线且只读的：

```powershell
python scripts/audit_spine_resource_coverage.py `
  --output E:/DevCache/nikke-spine-resource-coverage-post-refactor/coverage-summary.json `
  --markdown-output E:/DevCache/nikke-spine-resource-coverage-post-refactor/coverage-summary.md
```

只有显式刷新 upstream 时才访问 GitHub API，并将新固定快照写回本目录：

```powershell
python scripts/audit_spine_resource_coverage.py `
  --refresh-upstream `
  --output E:/DevCache/nikke-spine-resource-coverage-post-refactor/coverage-summary.json
```

用合成 fixture 通过现行角色卡生产 renderer 生成 c018 白卡预览（不使用账号数据）：

```powershell
python scripts/preview_t2i_frontend.py `
  --page character --fixture c018 `
  --output-dir E:/DevCache/nikke-spine-resource-coverage-post-refactor/preview
```

在生成 coverage JSON 后，可用同一 CLI 生成不含绝对路径或用户身份字段的 c018 diagnostic：

```powershell
python scripts/audit_spine_resource_coverage.py `
  --output E:/DevCache/nikke-spine-resource-coverage-post-refactor/coverage-summary.json `
  --markdown-output E:/DevCache/nikke-spine-resource-coverage-post-refactor/coverage-summary.md `
  --character-card-preview E:/DevCache/nikke-spine-resource-coverage-post-refactor/preview/character/c018.png `
  --diagnostic-output E:/DevCache/nikke-spine-resource-coverage-post-refactor/c018-character-card-diagnostic.json
```

建议在最终代码 commit 完成后运行以上输出命令。JSON 中的 `generated_from_head` 会记录实际执行审计时的 HEAD；生成产物放在仓库外以避免审计输出自身改变被记录的 HEAD。仓库内 upstream snapshot 和本说明是其固定输入、口径与生成说明。
