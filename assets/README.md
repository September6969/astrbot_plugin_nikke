# 单角色卡素材

素材按 `data/nikke/cache/`、本目录、远端、程序生成的占位图依次查找。缓存损坏会继续查找后续来源；远端失败会在五分钟后再试。Builder 和数据模型中不保存图片路径。

本地覆盖使用透明 PNG，可按以下目录放置图片：

- `portraits/<resource_id>.png`，也可用 `<name_code>.png` 覆盖特定角色。
- `equipment/<equipment_id>.png`，`slots/head.png`、`torso.png`、`arm.png`、`leg.png`。
- `favorite/<tid>.png`、`cube/<tid>.png`。
- `element/fire.png`、`water.png`、`wind.png`、`electric.png`、`iron.png`。
- `corporation/<小写企业名>.png`、`weapon/<小写武器名>.png`、`burst/<小写阶段名>.png`。

`sources.json` 可为相同相对路径指定 HTTPS 图片地址。未知装备、收藏品和魔方不会猜测 TID 对应的图片；未登记资源时使用抽象占位图。占位图不代表装备品级或属性。

`registry_manifest.json` 为 `equipment.json`、`cubes.json` 和 `favorite_items.json` 提供来源字段、核验日期与 SHA-256。运行时只接受符合 registry 合同的精确 ID；manifest 或映射损坏时对应 registry 失效并回退占位图，不从相邻 ID 推断资源。

通用立绘、企业、武器和爆裂图片来自 [Nikke-DB 图片目录](https://github.com/Nikke-db/Nikke-db.github.io/tree/main/images)。爱丽丝使用 `images/FB/c191_00.png`。小红帽立绘来自 [NIKKE Wiki](https://nikke-goddess-of-victory-international.fandom.com/wiki/Red_Hood/Gallery)，其地址在 `sources.json` 中明确登记。

这些游戏美术属于 SHIFT UP 及相关权利方，不属于本项目 GPL 代码许可证。仓库只记录资源定位信息，不将远端下载缓存纳入版本控制。
