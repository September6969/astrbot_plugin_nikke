# 夜间研究证据（2026-09-05）

本记录区分公开匿名读取、源码观察、人工 fixture 和尚未验证的真实账号行为。
没有使用真实 Cookie、OpenID、QQ、game_uid，没有执行账号写入或 QQ 消息发送。
外部完整 JS 与公告正文只保存在工作区外用于研究，不随仓库分发。

## 正式公告 CMS：已解除来源阻塞

来源：

- 官网：<https://nikke-en.com/>
- 官网配置：<https://nikke-en.com/assets/aix-05184733.js>
- 官网调用与详情链接：<https://nikke-en.com/assets/cms-e647af88.js>
- 官网引用 SDK：<https://sg-gpts.playerinfinite.com/comm/assets/lib/cmssdk.min.js>

配置实际声明 gameid=16、areaid=na、source_type=pc_web，英文站 language=en。
语言站映射 en/ja/ko/th/de/fr 来自官网配置；本次仅英文真实匿名联调成功，其他语言为离线合同测试。

匿名 POST 基址：
`https://na-community.playerinfinite.com/api/gpts.information_feeds_svr.InformationFeedsSvr/`

| 方法 | 已验证请求 | 已验证响应字段 |
| --- | --- | --- |
| GetLabelList | `{}` | code=0、data.result=0、primary_label_list |
| GetContentByLabel | language、gameid、offset、get_num、ext_info_type_list、primary_label_id、secondary_label_id、content_class | info_content、next_offset、total_num |
| GetContentInfoById | content_id | content_id、title、content、pub_timestamp、result |

请求头为 X-GameId=16、X-AreaId=na、X-Source=pc_web、X-Language=en，无账号头。
official_news 栏目本次返回 primary=309、default_secondary=496，代码动态解析而非固定栏目 ID。
先读列表后读全文，不用 content_part 建立日程。接口返回全文后按 HTML 解析为文本。
SDK 默认 v1 为无需签名的只读链路；未调用 ReportUserAction、LikeOper 等写入方法。

真实适配器匿名运行 `InformationFeedsSource(max_pages=1, page_size=1).fetch()`：
返回 1 条记录，正文非空。测试 fixture 仅保留实际结构和协议常量，内容 ID/标题/正文替换为合成文本；不是完整原始报文。

限制：默认英文、NEWS 栏目最多两页共 10 条，不代表完整公告历史或全部 NOTICE 栏目。
其他语言未逐站联调。主源失败尝试旧 GetAnnouncements，再失败保留缓存。
Deadline 仍为启发式 MVP，当前仅识别数字年月日时间，不保证解析英文自然日期。
未接自动群推送；查询、同步、缓存、版本和去重 API 已具备。

## BlaBlaLink 前端及 Raid

固定观察来源：

- <https://www.blablalink.com/assets/nikke/version/default/assets/index-CLXejj5I.js>
- <https://www.blablalink.com/assets/nikke/version/default/assets/union-ZKlhOzNG.js>
- <https://www.blablalink.com/assets/nikke/version/default/assets/union-raid-Bxg9CvXu.js>
- <https://www.blablalink.com/assets/nikke/version/default/assets/v4-cyK3GP1S.js>

前端显示使用 level_info.at(0)，但这不能证明多轮返回的选择规则。
攻击记录按 openid 分组、按 day 筛选；未发现可以证明最近一刀的精确时间字段。
官网成员资料链接使用 area + member_id，不足以证明与 participate_data.openid 的 join。
同名不能当作同人，当前排名不做 nickname join，不估计剩余攻击次数。

历史赛季端点在前端有明确调用：
GetUnionRaidDataOfGuildSeason、GetUnionRaidLevelDataOfGuildSeason，
参数为 area_id、guild_id、season_id。已增加只读客户端方法及 mock 合同测试；真实响应/分页仍待验证。

重要冲突：当前前端 union store 对登录 openid 做 split，而已有项目抓包合同要求完整透传。
本次保留完整透传，不擅自推翻已有合同。需真实只读诊断区分 canonical 与 x-common 身份。
不能仅凭前端截断代码宣称玩家身份匹配已解决。

排名范围明确为 CURRENT_RESPONSE，当前按产品要求按总伤害并列排名；不是官网赛季排名的完全复刻。
匿名语义 fixture 保留身份相等关系、day/level/step/slot、伤害比例，不保留真实数值与身份。

## 公共静态数据：已验证可读取

前端 getGameJsonResource 与既有 AssetManager.game_resource_url 合同一致。
以下逻辑路径均在前端出现，匿名读取 HTTP 200：

| 逻辑路径 | 结果与使用边界 |
| --- | --- |
| /stage/stage_list.json | 4417 行；Normal/Hard 的明确 STAGE/BOSS 标签导入 3572 项，Story/EX 排除 |
| /tower/tower_list.json | tower_type、floor、stage_id、standard_battle_power；只能说明静态层数据，不代表玩家进度 |
| /character/RecycleResearchStatTable.json | 9 个研究分类，与 QueryKeys 交叉核实后用于 Profile 名称 |
| /character/character_id_map.json | resource_id/name_code/id 等映射存在；不作为未知资源推导公式 |
| /character/AttractiveLevelTable.json | attractive_level/attractive_point 等数值存在；不包含问答正文 |
| /equip/favorite_rare_map.json | R/SR/SSR 珍藏品 ID 分类；未推导玩家拥有情况 |
| /equip/en/cube_1000301.json | 单魔方属性数组；不推断其它魔方属性或养成收益 |
| /character/en/nikke_list_en_v2.json | 角色目录、resource_id、name_code 等字段存在 |

关卡实际地址：<https://sg-tools-cdn.blablalink.com/xx-97/b32816a11f83865b09bcf95e67ca83ae.json>
来源元数据见 assets/campaign_stages.source.json；哈希针对下载后规范化 JSON，不声称为 HTTP 原始字节哈希。
复现导入：`python scripts/import_campaign_stages.py <downloaded-stage-list.json> assets/campaign_stages.json`。
不根据 chapter_id 计算显示章节，因为公开记录的内部章节键与显示标签不同。

研究枚举：<https://www.blablalink.com/assets/nikke/version/default/assets/setting-BatENrLx.js>
确认 Personal=1001、Attacker/Defender/Supporter=1101/1102/1103、厂商=1201..1205。
前端明确按 researches.tid 匹配这些 QueryKeys，故本次可以接线；未知 tid 名称仍为 None。

Advise/Tower/Cube/Collection/Skill 的数据可达性不再是整体 BLOCKED，
但完整产品服务、问答索引、技能数值解释、完整魔方表仍未实现，状态为 DEFERRED（后续离线开发），不是伪装成需要用户抓包。
前端还声明 /roledata/{id}-v2-{locale}.json 与 /attractscene/{scene_id}-{locale}.json，
本次未把不完整路径实例化为接口合同，也未复制未授权问答/攻略正文。

## Daily 点赞与浏览

公开 SDK 有 LikeOper 和 ReportUserAction；端点存在并不能证明它们满足 DailyTask 完成条件。
目前没有单次写入后状态前后变化的真实证据，不增加循环写入或猜测任务奖励链路。
已将签到的模糊结果改为单次写入后只读检查；未确认时 UNKNOWN_AFTER_ACTION。
真实只读诊断可以读取状态，但按设计不能验证点赞/浏览写入闭环，仍需单独授权的后续实验。

## Spine、语音与攻略

Spine 官方许可：<https://en.esotericsoftware.com/spine-runtimes-license>、
<https://us.esotericsoftware.com/spine-editor-license>。
公开资源可见不等于具备运行时集成授权。有效 Editor 许可决定运行时集成权利，trial 不等同运行时授权。
本次未下载运行时、未进行真实 PNG spike 或 Linux 性能基准。NEEDS_HUMAN_DECISION：运行时许可与部署预算。

语音过滤依据：<https://github.com/botuniverse/onebot-11/blob/master/event/notice.md>，
AstrBot 文档：<https://docs.astrbot.app/dev/star/resources/astr_message_event.html>，
并检查本地 AstrBot Record.fromFileSystem 和 aiocqhttp poke 转换代码。
实现默认关闭、本地授权索引、缓存、可选 ffmpeg、mock sender；真实 QQ 播放仍 NEEDS_LIVE_EVIDENCE。
官网前端存在 GET_VOICE_URL 和 voice_map，尚未确认可分发音频授权，未批量下载游戏语音。

攻略 registry 要求来源、作者、许可、版本、日期、路径；没有导入第三方攻略内容。
NEEDS_HUMAN_DECISION：提供可使用的攻略/语音内容或授权范围。

公开 GitHub 检索还核查 ExiaProject/ExiaInvasion（a6e653691d6a6d685f89c54694fadbf800e5d4b2，GPL-3.0），
以及 Nikke-db/nikke-db-vue（7f0f302e1531a2c199a81d03b51009a461b236f8）的文件树。
发现 Exia 14 项魔方名称映射，但没有把名字映射当作图标/属性映射替换原表。
