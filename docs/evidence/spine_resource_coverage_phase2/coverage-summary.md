# Post-Refactor Spine Resource Coverage Audit

- Generated from HEAD: `eb30aa7d387be5cf81aa01ac2219b4768660e86f`
- Nikke-db snapshot commit: `6e6ee77ff76ec6f9003953fbcdb3768248cbda04`
- Character resources / render consumers: `200` / `378`
- Upstream L2D IDs / complete root bundles: `558` / `558`
- Manifest / bundled PNG / valid manifest PNG: `38` / `39` / `38`
- Face Anchors / valid identities / trusted semantic Core Axis: `39` / `39` / `2`
- Missing manifest / orphan / invalid PNG / undeclared PNG: `340` / `0` / `0` / `1`
- Render Asset Gap / unsupported: `340` / `0`
- Manual visual/source review required: `340`
- Undeclared PNG review categories: `{'VERIFIED_MANIFEST_CANDIDATE': 0, 'VALID_VARIANT_NEEDS_REVIEW': 0, 'HISTORICAL_OR_TEST_ONLY': 0, 'STALE_OR_ORPHAN_FILE': 0, 'INVALID_ASSET': 1}`

## Definitions

- Missing Manifest: 当前生产 resolver 可解析且 upstream bundle 完整的 render_id 未在 manifest 声明；不包含 upstream 不完整或 identity 未解析的项目。
- Orphan Manifest: manifest render_id 不被任何当前默认角色或已验证 Costume 的生产 resolver 消费；Costume/alternate render identity 不会仅因不等于默认 ID 被判 orphan。
- Render Asset Gap: 生产 resolver 可解析、snapshot 存在完整 upstream bundle，但没有完整性通过的 manifest PNG，且没有显式 unsupported 分类的 render_id。
- Manual Review: 每个 Render Asset Gap 的 production identity 消费者与原因，需人工视觉/来源复核；未进行自动图像生成、Face Anchor 推测或 Core Axis 推测。
- Unsupported: 仅统计 CharacterMaster 明确标记 spine_support_status=unsupported 且提供 spine_support_reason 的默认角色；当前无此类记录。

## c018

- `resource_id=18 → c018`; upstream L2D `True`, FB `False`.
- Spine runtime `4.1` (skeleton evidence `4.1.20`); verified PNG `True` at `[2536, 3830]`.
- Face Anchor `anchor_available_head_only`; Core Axis `unavailable` (`upper_torso_unavailable`).
