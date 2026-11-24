# 竞技场与帮助详解

默认关闭竞技场。启用 enable_arena 后可使用单队文字分析。arena_web_enabled 独立控制临时移动端网页。arena_external_stats_enabled 只读取运行数据目录内的 arena-history.json。

## 使用

- /妮姬 帮助 详解 列出已发布教学主题。
- /妮姬 帮助 详解 日程 查看功能教学。
- /妮姬 竞技场 解队 红莲/豺狼/布兰儿/桑迪/特蕾娜 按 P1–P5 分析。群聊使用公开沙盒，私聊依据已确认持有名单过滤。
- /妮姬 竞技场 沙盒 红莲/豺狼/布兰儿/桑迪/特蕾娜 在私聊显式使用全角色范围。
- 私聊解队或三队导入可在五人后（或末行）追加 `珍藏:海伦,牡丹`，手动标记已制作专属珍藏的角色。只对基础名单已持有、且官方详情未否定的角色生效，结果标注「手动标记」。
- /妮姬 竞技场 我的 在私聊查看本人名单读取状态。
- /妮姬 竞技场 编辑 或 三队 在私聊获取一次性网页入口。
- /妮姬 竞技场 结果 在私聊回查本人最近两小时内的网页结果。
- /妮姬 竞技场 三队导入 支持一条消息内三行五人，群聊按公开沙盒计算。
- /妮姬 竞技场 数据状态 查看模型版本、来源、历史快照状态及网页和图片输出状态。

网页支持单队或三队、位置按钮、搜索、撤销、清空、粘贴、手动持有范围和三种搜索目标。用户每次修改后保存服务端草稿。新页面与旧页面发生版本冲突时提示刷新。

## 模型

使用同一个 Python 服务端内核。输入身份以插件的规范角色键为准，第三方标识通过显式映射进入。皮肤和珍藏状态共享基础角色排他约束。绑定名单只确认基础角色持有。珍藏形态按来源严格区分：

- 「官方详情确认」：网关短缓存内已有该角色的官方详情（例如刚执行过练度查询），且 `favorite_item_tid` 与带 SHA-256 清单的 favorite_items registry 中该角色的专属珍藏品一致。竞技场不为此额外发请求。
- 「手动标记」：私聊 `珍藏:角色名` 声明，或网页手动持有范围。推荐理由与风险中均标注未经官方详情确认。
- 「基础名单推测」：只持有本体、无官方详情时仅作提示，绝不计入持有范围，对应珍藏模板不会产生推荐。

每次单队最多检查 2048 个候选。各模板按五个槽位偏离首选的步数之和由近及远逐层枚举，同角色重复的分支在生成时剪除；预算按轮次在未穷举的模板间均分，小模板用剩的额度流向大模板。私聊缺槽时的同爆裂阶段替补按模板出现频次、静态充能效率、键名依次排序。三队先生成各对位的有限候选，再检查至多 30000 组三队组合，搜索循环另有一秒预算。所有输出都说明截断、未知字段和模型限制。

静态速度只反映锁定来源曲线。逐帧充能及个人技能、魔方和超频推演属于计划的可选 P7 增强。

## 更新历史快照

生产会在启动时读取 `data/nikke/arena-history.json`。同步由维护者手动触发。以下命令在 `serv` 上以当前 GLOBAL β40 的赛事 175 为例，先生成候选，不会修改在线快照。

```bash
root=/opt/nikke-bot/astrbot/data
plugin="$root/plugins/astrbot_plugin_nikke"
history="$root/nikke"
stage=$(mktemp -d "$history/.arena-history-XXXXXX")
python3 "$plugin/scripts/arena/sync_history.py" \
  --server GLOBAL --tournament-id 175 --registration-phase legacy \
  --output "$stage/arena-history.json"
printf '候选目录 %s\n' "$stage"
```

核对候选的 `server`、`seasons`、`tournament_ids`、`registration_phase`、`sample_size` 和 `rejected_rows`。确认赛事和口径后，同一终端执行下列命令。候选和线上文件位于同一文件系统。

```bash
test -s "$stage/arena-history.json" &&
  cp -p "$history/arena-history.json" "$stage/arena-history-before.json" &&
  mv -f "$stage/arena-history.json" "$history/arena-history.json" &&
  docker restart astrbot
```

保存候选目录路径用于回滚。如果更新后要恢复，执行下列命令；若只想暂时停用，可关闭 `arena_external_stats_enabled` 后重启。

```bash
test -s "$stage/arena-history-before.json" &&
  cp -p "$stage/arena-history-before.json" "$stage/arena-history-restore.json" &&
  mv -f "$stage/arena-history-restore.json" "$history/arena-history.json" &&
  docker restart astrbot
```

服务恢复后检查绑定站点 `/healthz` 与竞技场数据状态。重启会结束临时编辑会话，并清空用于 QQ 回查的内存结果。

## 文件索引

- [可行性与基线](FEASIBILITY.md)
- [来源和许可](SOURCES_AND_LICENSES.md)
- [角色字段矩阵](ROSTER_FIELD_MATRIX.md)
- [QQ 与网页交互](QQ_WEB_UX.md)
- [安全验收](WEB_SECURITY_ACCEPTANCE.md)
- [模型限制](MODEL_LIMITATIONS.md)
- [实施验收与回滚](ACCEPTANCE.md)
