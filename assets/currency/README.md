# Profile currency icons

这些文件只用于 Profile v0.4 的本地静态图标路径，不在 QQ 热路径下载。

核验日期：2026-09-12。上游固定为 Nikke-db commit `a2358b72bd1335c30737e46482a99947f3788bc7`。

| API type | 文件 | SHA-256 | 固定来源 |
| --- | --- | --- | --- |
| 1000 | `credit.png` | `85f242e863eab4a9f30391907843073c889f0fb7607fb530d12e7a15cc6a7035` | `images/credit.png` |
| 2000 | `battledata.png` | `dbea9945e42a5e6904e1d26cb8c136fb5947269b72b9fb14344565134f390486` | `images/battledata.png` |
| 3000 | `coredust.png` | `e0cf067c4b6443a736b8169568e858c99ee75340553974801ed35e6a8b931034` | `images/coredust.png` |
| 99 | `gem.webp` | `f99ae40780266faa746ac7bd9be44b4fd53e50c0d054caee9f5010f6f59d0700` | 用户提供图标 + 同日 Profile 数量对照图 |
| 5100 | `recruit_voucher.webp` | `330449dd8a7241af8195b200d7526144d6d8b6ffc83f81561e7eb542ce344f91` | 用户提供图标 + 同日 Profile 数量对照图 |
| 5200 | `advanced_recruit_voucher.webp` | `3f67077cd4d65afbf489398e88f865092781d84ff1ebba2559837aab694198ba` | 用户提供图标 + 同日 Profile 数量对照图 |
| 11000 | `body_label.webp` | `e3c8e83a99501de71209309b4784db98b52c2636dbb3ced47987cfbfabd431dc` | 用户提供图标 + 同日 Profile 数量对照图 |
| 12000 | `gold_mileage_ticket.webp` | `2a91fdd916cb801d020fa506ddf77644858bedd7cd1f89ddb67a765decf395ff` | 用户提供图标 + 同日 Profile 数量对照图 |

固定 Nikke-db 文件名与用户数量对照共同确认：API type `1000` 是战斗数据辑、`2000` 是信用点；旧 registry 的两项名称已纠正。用户提供的五张 RGBA WebP 与同一张资源数量图逐项对应：珠宝、普通招募券、高级招募券、躯体标签、黄金积分券。实时只读 `type + value` 对照为 `99→10126`、`1000→130327932`、`2000→26231673`、`3000→10497`、`5100→7`、`5200→5`、`11000→637`、`12000→140`；图片中的同类数值允许因截图时间不同而小幅变化。未登记的 type `98→16` 继续显示“未知资源”，不猜名称或图标。

这些图片属于上游游戏资源；本项目只记录来源与完整性，不声明为项目原创，也不把项目代码许可证解释为游戏美术授权。
