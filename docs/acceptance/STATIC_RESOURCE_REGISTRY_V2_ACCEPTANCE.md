# 静态资源 Registry V2 验收

## 状态

`READY_OFFLINE`：registry 加载、manifest 完整性、精确 ID 校验、重复键拒绝和 costume 空映射已由离线测试覆盖。

`NEEDS_LIVE_EVIDENCE`：Nikke-DB/CDN 的完整资源覆盖、实际 HTTP 路径、游戏资源授权和现场渲染仍需在有明确 bundle/账号与网络证据时核验。

## 当前合同

- `equipment.json`、`cubes.json`、`favorite_items.json` 和 `costumes.json` 均由 `registry_manifest.json` 登记来源、核验日期、SHA-256 和许可边界。
- `costumes.json` 当前有意为空；没有 API costume ID 到 Nikke-DB asset ID 的来源证据时，不新增映射。
- costume key 只接受显式的小写标识，value 只接受 `cNNN` 或 `cNNN_MM` 形式的 Nikke-DB asset ID。
- unknown、invalid、未登记和 manifest/hash/JSON 损坏不会推导相邻 ID，也不会静默回退到默认 costume。
- registry 只记录标识元数据，不分发游戏美术、Spine bundle 或玩家私有资源。

## 验收证据

- `tests/test_static_registry.py` 覆盖精确 ID、空 costume registry、hash mismatch、重复键、目录穿越和 bool ID。
- 本 PR 的 CI 必须通过定向 Python 测试、完整 pytest、`compileall`、Node extension tests 和 `git diff --check`。
- 未来补充 costume 映射时，必须同时提交上游 URL/响应范围、核验日期、原始内容 SHA-256 和许可边界；否则保持空表并记录 `NEEDS_LIVE_EVIDENCE`。
