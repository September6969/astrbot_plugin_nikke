# 来源和许可

| 来源 | 用途 | 使用依据 | 状态 |
|---|---|---|---|
| 本仓库角色目录与别名 | 规范身份、本地名称、资源映射 | 项目已有经核验资产及 GPL-3.0-or-later 代码 | 已复用 |
| Arena Planner app/data/characters.json | RL 静态曲线及多语言查询名称 | 上游 MIT 许可，锁定 c7948fb | 已保存转换快照 |
| Arena Planner app/data/templates.json | 候选模板及社区克制声明 | 上游 MIT 许可，锁定 c7948fb | 作为参考模板 |
| PvP Counter chainOf | 爆裂顺序参考与黄金对照 | 上游 MIT 许可，锁定 60f8ac5 | 已留版权与许可 |
| nikkeari.cc | 指定赛事历史对位 | 用户于 2026-11-17 确认已咨询并获准使用 | 离线同步工具，运行时默认关闭 |
| NIKKE DECK | 原项目额外速度变体 | 当前没有为本插件核实的独立许可记录 | 本插件未引入其附加速度表 |
| nikke.top | 逐帧参数 | 本轮仅核对公开入口 | P7 待验证 |
| NIKKE Synergy | 原项目日期及机制参考 | 本轮没有复制原项目的混合导出数据 | 待后续逐源核实 |

Arena Planner 及 PvP Counter 的完整许可分别保存在 assets/data/arena/LICENSE-planner.txt 和 LICENSE-counter.txt。转换后的 rules.json 记录原始文件 SHA-256、来源 commit、显式身份映射、映射方式和未映射清单。

scripts/arena/build_snapshot.py 从锁定的本地源快照重建数据。脚本支持精确资源号和精确英文名匹配，遇到重复规范身份会拒绝构建。每种珍藏变体保留基础身份键。

scripts/arena/sync_history.py 只读取指定赛事、服务器和登记阶段，最多重试一次。生成文件保留站位、角色键、聚合胜负、有效对位中的角色出场次数和来源元数据。零个有效对位时保留现有快照。普通 QQ 查询不会触发该工具。

四个源端点在 2026-11-17 的成功响应中都未提供 ETag 或 Last-Modified。一次手动同步只访问四个端点，每个响应最多 8 MiB，每个端点最多两次请求。HTTP 429 立即结束本次同步，短暂故障仅重试一次。上游要求等待超过五秒时结束本次同步，未完成的同步不会替换当前快照。部署时先生成候选文件并复核赛事、登记阶段和有效样本数，再保留当前运行快照并原子替换。需要回滚时恢复前一版本快照并重启，或关闭历史统计开关并重启。

## 原始来源

- [Arena Planner 源码](https://github.com/williamchong/nikke-arena-planner)
- [PvP Counter 源码](https://github.com/SakuranoAphrodite/nikke-pvp-counter)
- [nikkeari 关于与使用说明](https://nikkeari.cc/about)

站点关于页说明统计来自玩家截图，覆盖晋级的 64 位及冠军对抗赛的 8 位玩家，具有选择偏差。历史结果显示服、赛季、补丁、样本数和区间。同步使用完整对局明细，展示按 5/5、4/5、3/5 同站位分档。

GLOBAL 赛事 175 在 `legacy` 登记阶段返回 64 位玩家、63 场系列赛和 62 项角色统计。聚合端点用于核对响应及登记阶段。对位端点返回 315 条分阵容记录，快照基于可映射的 305 条对位构建，计数同时包含进攻和防守方的五个站位。

从已授权快照中另选 24 条真实对位，用于离线对照。样本保存在工作区忽略目录 `output/baseline-assets-qa-v3/arena-golden-global-175.json`，包含规范角色键、攻守站位、胜负计数、来源和快照哈希。镜像、再入、轴外支持、珍藏变体及条件爆裂标签按阵容结构标注。实际胜负来自赛事记录，结构标签不用于归因。

2026-11-17 复核公开站点说明与 [robots.txt](https://nikkeari.cc/robots.txt)。该路径返回 HTTP 200，此次响应仅包含说明注释。关于页限制商业复制、转载和再分发，并要求个人公开引用注明出处。离线工具的使用依据为用户确认的站方许可。赛事目录的 `has_match_data` 标记需要结合同一登记阶段的对位响应判断。
