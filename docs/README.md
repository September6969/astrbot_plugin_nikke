# 文档导航

本目录区分当前使用说明、架构与接口合同，以及历史验收和取证资料。历史记录描述当时的环境与结论，不能代替当前版本验收。

## 使用与部署

- [安装、命令和配置](../README.md)
- [部署文件](../deploy/)
- [发布检查清单](operations/RELEASE_CHECKLIST.md)
- [运维资料](operations/)
- [扩展组件](../extension/)
- [Spine worker](../runtime/spine_worker/)

## 架构与开发

- [架构目录](architecture/)
- [仓库结构与迁移说明](architecture/REPOSITORY_ORGANIZATION.md)
- [开发工具及输入输出](../scripts/README.md)
- [界面渲染与交接资料](ui/)
- [前期调研](research/)
- [PR #103 重构交付记录](refactor/FINAL_DELIVERY.md)

## 当前接口合同与验收

- [接口合同目录](contracts/)
- [角色数据合同](contracts/CHARACTER_DATA_V2_CONTRACT.md)
- [公告合同](contracts/ANNOUNCEMENT_V2_CONTRACT.md)
- [动态语音合同](contracts/DYNAMIC_VOICE_V2_CONTRACT.md)
- [Spine 探测合同](contracts/SPINE_SPIKE_CONTRACT.md)
- [验收标准与阶段报告](acceptance/)
- [需求与证据矩阵](operations/REQUIREMENT_EVIDENCE_MATRIX.md)
- [社区浏览、点赞与实验性续期合同](operations/COMMUNITY_ACTIONS_AND_RENEWAL.md)
- [社区额外能力交付与验证边界](operations/COMMUNITY_ACTIONS_DELIVERY.md)

验收报告需结合记录日期、提交、环境和未验证项阅读。本地 Chromium 预览、AstrBot 原生接口、真实账号验收、部署及 CI 是不同的验证范围。

## 历史资料

- [归档索引及迁移映射](archive/INDEX.md)
- [历史证据](archive/evidence/)
- [历史报告](archive/reports/)
- [早期设计与变更](archive/)

旧 `docs/evidence/`、根 `eunhwa-tactical-upgrade/` 和受控 `reports/` 的内容保留在归档中。CI 使用的小型固定快照独立放在 [tests/fixtures](../tests/fixtures/)，来源及 SHA-256 见[固定输入来源表](../tests/fixtures/repository_organization_sources.json)。
