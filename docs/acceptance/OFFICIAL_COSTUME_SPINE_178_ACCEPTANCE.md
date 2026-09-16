# Official Costume / Spine 178 验收

## 范围与结论

- 官方分母：178，来源为固定 `CharacterCostumeTable` snapshot。
- 最终分类：`SUPPORTED=178`，`MAPPING_MISSING=0`，`UNRESOLVED=0`，其余不可支持状态均为 0。
- 既有 47 条映射全部冻结；新增 131 条使用 owner 分组实名 poster 与真实 Spine `idle@t=0` contact sheet 人工核验。
- 默认角色保持 200/200；官方 Costume resolver、manifest、PNG、SHA-256 与 decode 为 178/178；错误回退原皮为 0。

## 提交边界

- `implementation_head`：`103ebd3f3a881da51acaff7255dec57d370d2268`，完成 178 registry、映射、运行时审计与测试实现。
- `evidence_head`：`d258a29`，修正 official inventory 最终分类并加入跨 evidence 一致性 invariant。
- `latest_ci_head`：以 PR #79 当前最终 HEAD 的 required checks 为准；最终 run 与完整 SHA 记录在 PR body，不能沿用旧提交的 CI。
- `production_head`：runtime 实现未因本轮 evidence 修正而改变；生产只同步了 `implementation_head` 的 registry/manifest 内容，不能把后续纯 evidence/test 提交冒充为已部署代码。

## 关键证据

- `docs/evidence/costume_identity_snapshot.json`：110 个 owner 页面与 178 个实名 poster identity。
- `docs/evidence/costume_spine_candidate_matrix.json`：官方 owner、固定 Git tree bundle、冻结映射与人工核验结果。
- `docs/evidence/costume_identity_manual_validation.json`：131 条 poster/render/contact-sheet SHA-256。
- `docs/evidence/spine_runtime_resolution_audit.json`：默认 200 与官方 Costume 178 的 resolver/manifest/PNG 审计。
- `docs/evidence/spine_visual_suspects.json`：378 项结构视觉审计，suspect 0。
- `docs/evidence/official_costume_support_risk.json`：178 状态机最终台账。
- `docs/evidence/qq_costume_sampled_acceptance.json`：用户确认的最终 QQ 卡片抽样结果；不保存 QQ ID、OpenID 或任何凭据。

## 映射边界

公开 poster 的 `cXXX_YY` 仅是实名静态图 identity，不是 Spine ID。Rapi Classic Vacation 的 poster 为 `c010_02`，真实 Spine 仍为冻结映射 `c010_03`；Rapi White Promise 为 `c010_02`；Diesel Black Sunday 为 `c072_01`。测试明确保护这类编号偏移，禁止由后缀或 Costume index 推导。

## 服务器维护

固定 Nikke-db commit：`a2358b72bd1335c30737e46482a99947f3788bc7`。候选按小批量 partial clone 拉取，atlas 路径逐项验证，并始终保留 5 GiB 空间门禁。预渲染 PNG/manifest 已进入服务器持久化数据目录。提交 `103ebd3f3a881da51acaff7255dec57d370d2268` 的 GitHub CI 全绿后，178 registry 已原子同步到生产插件并重启 AstrBot；旧 registry 已单独备份。

## 当前状态

`PARTIAL`（仅等待最终 HEAD CI）。本轮 inventory 一致性修正后的本地定向测试为 17 passed，最终 full pytest 为 660 passed、484 subtests passed；compileall 与 diff check 通过。生产重启后的全量 probe 为默认 200/200、Costume 178/178、失败 0、fallback risk 0，插件启动日志无 registry 错误。用户已确认 QQ 抽样 PASS；最终 evidence HEAD CI 全绿后状态升级为 `READY_TO_MERGE` 并按正常 gate 合并 PR #79。
