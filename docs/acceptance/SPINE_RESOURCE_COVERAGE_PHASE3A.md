# Spine 资源覆盖 Phase 3A：小批量离线验证

## 目的与边界

Phase 3A 只为当前 canonical default character 的 Spine coverage gap 建立可重复的 20 项 dry-run：固定 upstream commit、按需抓取 skeleton/atlas/纹理页、匹配 runtime 渲染、校验 PNG、按当前 38 张 verified portrait 校准视觉异常、生成待人工复核清单和当前白色竖版角色卡 contact sheet。

本阶段不修改 `assets/spine_manifest.json`、`assets/data/spine_manifest.json`、Face Anchor 或 Core Axis；不自动生成 anchor/semantic axis，不批量提升资源。晋升 gate 只读，不写生产 manifest。PR #101 的 runtime warm/cache/远端渲染仍不属于本阶段。

普通 pytest 和 PR CI 不访问 Nikke-db 网络。`.github/workflows/ci.yml` 中现有 c010 worker smoke 与 `Spine Phase 3A candidate dry-run (manual only)` 都只在显式 `workflow_dispatch` 时运行；两者均绑定已记录的 snapshot commit。候选 snapshot、bundle 和 evidence 都写在 runner 临时目录，最终只上传 review evidence，不上传 Git object cache 或 raw Spine texture bundle。

## 固定与确定性输入

- Coverage 输入：`docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json`。
- Snapshot commit：以 JSON 内 `commit_sha` 为准；当前录入值为 `6e6ee77ff76ec6f9003953fbcdb3768248cbda04`。
- Batch 生成输入：coverage audit 的 `canonical_default_consumers`、`render_asset_gap`、`canonical_render_consumers_with_upstream_l2d` 和 `unsupported` 集合。
- 首批策略：只选默认角色，最多 20 项；按 canonical `resource_id` 升序，不含 costume。Runtime 从 skeleton 字节头检测，不按角色猜测。
- Baseline：只纳入当前 manifest 中 raw SHA-256、PNG 解码和尺寸均匹配的 verified portrait；视觉 alpha bbox 从裁切后实际 PNG 解码重算。manifest `alpha_bbox` 可能属于裁切前 Spine canvas 坐标，不能当作本地 PNG 坐标。

## 运行方式

维护者可在目标分支显式运行 GitHub Actions 的 `CI` workflow_dispatch。该人工工作流会依序：

1. 计算 38 张已核验角色图的校准分布并审计固定 coverage snapshot。
2. 确定性选择 20 个默认角色候选。
3. 创建 `blob:none` partial clone，只懒取候选 `_00` skeleton、atlas 和 atlas 明确引用的纹理页，并逐项比对 snapshot Git blob SHA 与大小。
4. 使用与 skeleton 版本匹配的官方 Spine worker，将 manifest 和 portrait 写到 runner 临时目录。
5. 通过当前 `CharacterT2IPayloadBuilder`、`templates/t2i/character.html` 和本地 headless Chromium 生成 1600×2400 白卡，再生成 review queue、Markdown 和 contact sheet。

本地具备项目正式 Spine 4.0/4.1 worker 与 Chromium 的维护环境，可按同一阶段调用：

```powershell
python scripts/spine_batch_validation.py --repo-root . --output <external-output>/verified-baseline.json
python scripts/audit_spine_resource_coverage.py --repo-root . --upstream-snapshot docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json --output <external-output>/coverage-summary.json
python scripts/build_spine_candidate_batch.py --coverage-summary <external-output>/coverage-summary.json --output <external-output>/batch-001.json --batch-id batch-001 --batch-size 20
python scripts/fetch_spine_candidate_bundles.py --batch <external-output>/batch-001.json --snapshot docs/evidence/spine_resource_coverage_post_refactor/upstream_asset_snapshot.json --checkout <external-output>/nikke-db-object-cache --output <external-output>/bundle
```

然后将 `<external-output>/bundle` 交给 `scripts/sync_spine_assets.py`，并将其 PNG、render manifest 交给 `scripts/spine_batch_review.py` 和 `scripts/render_spine_candidate_cards.py`。所有维护输出必须在仓库外；`sync_spine_assets.py` 的 manifest 路径必须明确指向外部临时文件，不能指向生产 manifest。

## 机器校验与人工复核

`PASS` 表示固定来源、文件哈希、identity、runtime、解码和渲染输出均通过，且九项 PNG 几何/alpha 指标都在 38 张基线的 p05–p95 区间内；这不是视觉验收。`PASS_WITH_FLAGS` 表示仍在已观察范围内但有指标落在中央 90% 之外，必须人工检查。超出 38 张样本 min/max 会独立标记为 `outside_verified_range`。文件、身份、来源或渲染失败为 `FAIL`，禁止晋升。

PASS sample 由 `SHA-256(batch_id + NUL + render_id + NUL + png_sha256)` 排序后确定，输入顺序不影响结果。所有项目仍须人工审核白卡构图、视觉质量、Face Anchor 与 Core Axis；无 anchor 不会被当作已验证状态。

晋升检查通过 `scripts/check_spine_candidate_promotion.py` 执行，只判断候选 evidence、review decision、anchor 图像身份及当前 production manifest SHA 是否一致。它不会写文件或修改 manifest。Phase 3A 的预期 promotion count 固定为 0。

## Evidence

人工工作流 artifact `spine-phase3a-batch-review` 至少包含：coverage summary、38 张 baseline、batch definition、sparse fetch provenance、外部 render manifest/coverage、review queue JSON/Markdown、每张候选白卡的诊断 JSON 和白卡 contact sheet。artifact 不包含 Nikke-db checkout、raw skeleton、atlas 或纹理文件。审阅结论以 artifact 中的 batch、source commit、SHA-256 和当前 run SHA 为准。
