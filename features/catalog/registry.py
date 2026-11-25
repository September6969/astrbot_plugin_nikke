# SPDX-License-Identifier: GPL-3.0-or-later
"""统一功能目录注册表（Phase 3）。

只使用标准库定义全量功能元数据、双入口归属（公共大厅 / 指挥官工作台 / QQ 原生）、
权限门禁与一键复制命令模板。公共页面与个人页面消费同一数据源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CategorySpec:
    id: str
    name: str
    summary: str
    order: int


@dataclass(frozen=True, slots=True)
class FeatureEntry:
    id: str
    name: str
    category: str
    summary: str
    qq_commands: tuple[str, ...]
    example_command: str
    entry_mode: str  # "hall" | "workspace" | "both" | "qq_only"
    requires_binding: bool = False
    admin_only: bool = False
    supports_group_feedback: bool = False
    web_tab: str = ""
    feature_flag: str = ""
    aliases: tuple[str, ...] = ()
    note: str = ""


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec("account", "账号", "绑定与个人档案", 1),
    CategorySpec("growth", "养成", "角色资料、练度与养成工具", 2),
    CategorySpec("arena", "竞技场", "解队与阵容分析", 3),
    CategorySpec("raid", "突袭", "联盟与单人突袭", 4),
    CategorySpec("guide", "攻略", "战役、塔层与一图流攻略", 5),
    CategorySpec("event", "活动", "日程、卡池、公告与订阅", 6),
    CategorySpec("welfare", "福利", "签到、社区任务与兑换", 7),
    CategorySpec("social", "互动", "塔罗、本命九宫格与语音", 8),
    CategorySpec("admin", "管理", "运行维护与会话控制", 9),
)


FEATURES: tuple[FeatureEntry, ...] = (
    # ---- 双入口自身 ----
    FeatureEntry(
        id="portal.hall",
        name="公共功能大厅",
        category="互动",
        summary="无需登录即可使用的公开导航、口令复制、日程卡池、塔罗占卜与静态工具；从群内进入时支持推送日程/塔罗结果回群。",
        qq_commands=("/妮姬 大厅",),
        example_command="/妮姬 大厅",
        entry_mode="hall",
        supports_group_feedback=True,
        web_tab="overview",
        aliases=("大厅", "hall"),
    ),
    FeatureEntry(
        id="portal.workspace",
        name="个人指挥官工作台",
        category="账号",
        summary="一次性短时会话入口：自助绑定、按需加载个人档案/练度、竞技场与单人突袭五队编组、个性化设置及可控回群分享。",
        qq_commands=("/妮姬 工作台",),
        example_command="/妮姬 工作台",
        entry_mode="workspace",
        requires_binding=False,
        supports_group_feedback=True,
        web_tab="overview",
        aliases=("工作台", "workspace", "workbench"),
    ),
    # ---- 账号与个人 ----
    FeatureEntry(
        id="account.bind",
        name="账号绑定与状态",
        category="账号",
        summary="查看当前 BlaBlaLink 绑定状态、生成 10 分钟一次性安全绑定页、开关每日汇总及解绑。",
        qq_commands=("/妮姬 账号", "/妮姬 账号 绑定", "/妮姬 账号 汇总 开|关", "/妮姬 账号 解绑"),
        example_command="/妮姬 账号",
        entry_mode="workspace",
        web_tab="binding",
        aliases=("账号", "account", "绑定", "bind"),
    ),
    FeatureEntry(
        id="account.renewal",
        name="实验性会话续期",
        category="账号",
        summary="私聊查看 Cookie 会话续期状态，或在本人明确开启后执行自动/手动续期。",
        qq_commands=("/妮姬 账号 续期 状态", "/妮姬 账号 续期", "/妮姬 账号 自动续期 开|关"),
        example_command="/妮姬 账号 续期 状态",
        entry_mode="qq_only",
        requires_binding=True,
        feature_flag="enable_daily_actions",
    ),
    FeatureEntry(
        id="profile.me",
        name="指挥官个人进度",
        category="账号",
        summary="查看昵称、战力、同步器等级、主线进度、珠宝与核心材料汇总。",
        qq_commands=("/妮姬 我的",),
        example_command="/妮姬 我的",
        entry_mode="workspace",
        requires_binding=True,
        supports_group_feedback=True,
        web_tab="profile",
        aliases=("我的", "me"),
    ),
    FeatureEntry(
        id="identity.uid",
        name="UID 边界与手工档案",
        category="账号",
        summary="说明数字 UID 与 OpenID 的安全边界；管理未绑定情况下的个人手工档案。",
        qq_commands=("/妮姬 uid <数字UID>", "/妮姬 我的妮姬 资料", "/妮姬 我的妮姬 手工 <昵称>,<等级>"),
        example_command="/妮姬 我的妮姬 资料",
        entry_mode="both",
        web_tab="settings",
        aliases=("uid", "我的妮姬"),
    ),
    FeatureEntry(
        id="growth.history",
        name="养成成长历史",
        category="账号",
        summary="按用户与游戏身份严格隔离保存战力与练度快照，展示最近同步变化并支持一键清空。",
        qq_commands=("/妮姬 养成历史", "/妮姬 养成历史 清空"),
        example_command="/妮姬 养成历史",
        entry_mode="workspace",
        requires_binding=True,
        web_tab="profile",
        aliases=("养成历史", "growth"),
    ),
    # ---- 养成与静态工具 ----
    FeatureEntry(
        id="character.roster",
        name="角色练度与单卡",
        category="养成",
        summary="查看已绑定账号已持有妮姬练度排行、T10 洗词条与单角色详卡。",
        qq_commands=("/妮姬 查询 练度", "/妮姬 查询 练度 <角色名>"),
        example_command="/妮姬 查询 练度 红莲",
        entry_mode="workspace",
        requires_binding=True,
        web_tab="roster",
        aliases=("练度", "roster"),
    ),
    FeatureEntry(
        id="character.info",
        name="妮姬公开资料",
        category="养成",
        summary="按角色名或别名查询企业、部队、武器、代码与爆裂阶段等静态资料。",
        qq_commands=("/妮姬 查询 资料 <角色名>",),
        example_command="/妮姬 查询 资料 红莲",
        entry_mode="hall",
        web_tab="tools",
        aliases=("资料", "info"),
    ),
    FeatureEntry(
        id="counsel.search",
        name="咨询答案检索",
        category="养成",
        summary="按角色与问题关键词检索已导入的合法咨询题库（缺失题库时不伪造数据）。",
        qq_commands=("/妮姬 咨询 <角色名> [关键词]",),
        example_command="/妮姬 咨询 拉毗 作战",
        entry_mode="hall",
        web_tab="tools",
        aliases=("咨询", "counsel"),
    ),
    FeatureEntry(
        id="sync.calculator",
        name="同步器升级计算",
        category="养成",
        summary="结合当前等级、目标等级、资源库存与日产量估算所需天数与资源瓶颈；支持绑定账号自动读取库存。",
        qq_commands=("/妮姬 同步器 状态", "/妮姬 同步器 计算 <当前> <目标> <三库存> <三日产>"),
        example_command="/妮姬 同步器 计算 手工 200 210 0 0 0 400 1000 100 3000 4500 1200",
        entry_mode="both",
        web_tab="tools",
        aliases=("同步器", "sync"),
    ),
    FeatureEntry(
        id="wishlist.advisor",
        name="普通招募愿望单推荐",
        category="养成",
        summary="按收集/均衡/养成策略，基于三大企业 5 槽 + 朝圣者/超标准分区的 SSR 规则生成愿望单推荐。",
        qq_commands=("/妮姬 愿望单 [均衡|收集|养成] [角色:星级,...]",),
        example_command="/妮姬 愿望单 均衡 拉毗:2,迪塞尔:0",
        entry_mode="both",
        web_tab="tools",
        aliases=("愿望单", "wishlist"),
    ),
    FeatureEntry(
        id="overload.advisor",
        name="超限洗词条建议与模拟",
        category="养成",
        summary="依据目标词条与 1–15 阶官方数值表评估保留/锁定策略、模拟洗炼并对比已绑定角色当前装备。",
        qq_commands=("/妮姬 洗词条 <目标词条> <部位,阶,词条,...>", "/妮姬 洗词条模拟 <目标词条> <部位,...>"),
        example_command="/妮姬 洗词条 攻击力增加,暴击伤害增加 头部,1,攻击力增加,15,锁",
        entry_mode="both",
        web_tab="tools",
        aliases=("洗词条", "overload"),
    ),
    # ---- 竞技场 ----
    FeatureEntry(
        id="arena.solver",
        name="竞技场解队与三队编辑",
        category="竞技场",
        summary="基于蓄力曲线与静态模板进行单队文字解队或临时网页三队编排优化。",
        qq_commands=("/妮姬 竞技场 解队 <五人>", "/妮姬 竞技场 编辑", "/妮姬 竞技场 三队"),
        example_command="/妮姬 竞技场 解队 红莲/豺狼/布兰儿/桑迪/特蕾娜",
        entry_mode="both",
        feature_flag="enable_arena",
        supports_group_feedback=True,
        web_tab="arena",
        aliases=("竞技场", "arena"),
    ),
    # ---- 突袭 ----
    FeatureEntry(
        id="raid.union",
        name="联盟突袭统计",
        category="突袭",
        summary="查看当前联盟突袭 Boss 总览、全盟贡献排行与个人出刀记录。",
        qq_commands=("/妮姬 联盟突袭", "/妮姬 突袭 排名 [页码]", "/妮姬 突袭 我的 [页码]"),
        example_command="/妮姬 联盟突袭",
        entry_mode="workspace",
        requires_binding=True,
        web_tab="profile",
        aliases=("突袭", "联盟突袭", "raid"),
    ),
    FeatureEntry(
        id="solo_raid.planner",
        name="单人突袭五队与估伤",
        category="突袭",
        summary="自动或手动编排五队并校验完整爆裂链，集成固定基准 nikke-calc@67835ca 输出可核验伤害估算。",
        qq_commands=("/妮姬 单人突袭 赛季", "/妮姬 单人突袭 编组 账号", "/妮姬 单人突袭 我的"),
        example_command="/妮姬 单人突袭 编组 账号",
        entry_mode="workspace",
        supports_group_feedback=True,
        web_tab="solo_raid",
        aliases=("单人突袭", "soloraid"),
    ),
    # ---- 攻略 ----
    FeatureEntry(
        id="campaign.clear",
        name="主线战役通关记录",
        category="攻略",
        summary="按关卡号（如 46-40、困难）查询本账号所在服务器历史低战通关阵容。",
        qq_commands=("/妮姬 战役 <关卡> [困难]",),
        example_command="/妮姬 战役 46-40",
        entry_mode="workspace",
        requires_binding=True,
        web_tab="profile",
        aliases=("战役", "campaign"),
    ),
    FeatureEntry(
        id="tower.floor",
        name="无限之塔楼层资料",
        category="攻略",
        summary="查询无限塔与企业塔各楼层战力与敌方构成静态资料。",
        qq_commands=("/妮姬 塔层 <塔名> <层数>",),
        example_command="/妮姬 塔层 无限塔 100",
        entry_mode="hall",
        web_tab="guides",
        aliases=("塔层", "tower"),
    ),
    FeatureEntry(
        id="guide.images",
        name="一图流攻略目录",
        category="攻略",
        summary="分页查看练度、红球、珍藏品、充能、洗词条与 PVP 授权攻略图。",
        qq_commands=("/妮姬 攻略", "/妮姬 攻略 <分类> [页码]"),
        example_command="/妮姬 攻略 练度",
        entry_mode="hall",
        web_tab="guides",
        aliases=("攻略", "guide"),
    ),
    # ---- 活动与资讯 ----
    FeatureEntry(
        id="calendar.schedule",
        name="活动日程总览",
        category="活动",
        summary="查询未来 7/14/30 天官方活动日程与倒计时；在群 context 打开大厅可直接回推日程图。",
        qq_commands=("/妮姬 日程 [7|14|30] [页码]", "/妮姬 日程 刷新"),
        example_command="/妮姬 日程 14 1",
        entry_mode="hall",
        supports_group_feedback=True,
        web_tab="calendar",
        aliases=("日程", "schedule"),
    ),
    FeatureEntry(
        id="calendar.board",
        name="卡池 / 皮肤 / 突袭分类板",
        category="活动",
        summary="按卡池、活动、皮肤、突袭分类展示进行中与即将开启项目及截止倒计时。",
        qq_commands=("/妮姬 卡池 [卡池|活动|皮肤|突袭]",),
        example_command="/妮姬 卡池",
        entry_mode="hall",
        web_tab="calendar",
        aliases=("卡池", "gacha"),
    ),
    FeatureEntry(
        id="calendar.subscription",
        name="个人日程截止订阅",
        category="活动",
        summary="在当前会话订阅特定活动类型的截止 @提醒。",
        qq_commands=("/妮姬 日程 订阅 <类型>", "/妮姬 日程 订阅状态", "/妮姬 日程 取消订阅"),
        example_command="/妮姬 日程 订阅 协同,签到",
        entry_mode="qq_only",
        aliases=("日程订阅",),
    ),
    FeatureEntry(
        id="announcement.view",
        name="官方公告检索",
        category="活动",
        summary="按语言、分类或关键词查询本地同步的官方公告原文。",
        qq_commands=("/妮姬 公告", "/妮姬 公告 语言 <en|zh-TW|...>", "/妮姬 公告 搜索 <关键词>"),
        example_command="/妮姬 公告",
        entry_mode="hall",
        web_tab="announcements",
        aliases=("公告", "news"),
    ),
    FeatureEntry(
        id="feeds.subscription",
        name="新闻 / 视频 / 日程订阅",
        category="活动",
        summary="独立选择订阅新闻、官方视频更新或日程；工作台与 QQ 均可管理状态。",
        qq_commands=("/妮姬 新闻", "/妮姬 新闻 订阅 新闻,视频,日程", "/妮姬 新闻 状态"),
        example_command="/妮姬 新闻 状态",
        entry_mode="both",
        web_tab="settings",
        aliases=("新闻订阅", "feeds"),
    ),
    # ---- 福利与日常 ----
    FeatureEntry(
        id="daily.checkin",
        name="社区签到与状态",
        category="福利",
        summary="查询当日签到进度，或在绑定且开启写开关时执行手动签到。",
        qq_commands=("/妮姬 签到 状态", "/妮姬 签到"),
        example_command="/妮姬 签到 状态",
        entry_mode="qq_only",
        requires_binding=True,
        aliases=("签到",),
    ),
    FeatureEntry(
        id="daily.routine",
        name="社区日常与自动执行",
        category="福利",
        summary="在私聊或本人开启后执行社区日常领奖、浏览/点赞授权任务与每日自动运行。",
        qq_commands=("/妮姬 日常", "/妮姬 日常 自动 开|关", "/妮姬 日常 任务 状态"),
        example_command="/妮姬 日常 任务 状态",
        entry_mode="qq_only",
        requires_binding=True,
        feature_flag="enable_daily_actions",
        aliases=("日常", "daily"),
    ),
    FeatureEntry(
        id="cdk.redeem",
        name="国际服 CDK 兑换",
        category="福利",
        summary="查看已知可用 CDK、个人兑换历史或在私聊提交单码/批量兑换。",
        qq_commands=("/妮姬 兑换 可用", "/妮姬 兑换 历史", "/妮姬 兑换 <CDK>"),
        example_command="/妮姬 兑换 可用",
        entry_mode="qq_only",
        requires_binding=True,
        feature_flag="enable_cdk_redemption",
        aliases=("兑换", "cdk"),
    ),
    # ---- 娱乐与互动 ----
    FeatureEntry(
        id="tarot.draw",
        name="NIKKE 塔罗占卜",
        category="互动",
        summary="使用大/小阿尔卡那 NIKKE 牌库进行单抽、三张牌阵或今日运势占卜；支持大厅一键回推群聊。",
        qq_commands=("/妮姬 塔罗 单抽", "/妮姬 塔罗 三张", "/妮姬 塔罗 今日", "/妮姬 塔罗 状态"),
        example_command="/妮姬 塔罗 单抽",
        entry_mode="hall",
        supports_group_feedback=True,
        web_tab="tarot",
        aliases=("塔罗", "tarot"),
    ),
    FeatureEntry(
        id="favorite_grid.board",
        name="本命九宫格与人气榜",
        category="互动",
        summary="按顺序选择 9 名妮姬生成统一 T2I 3x3 图片并参与本命人气榜投票。",
        qq_commands=("/妮姬 九宫格 <9名妮姬>", "/妮姬 本命榜"),
        example_command="/妮姬 本命榜",
        entry_mode="both",
        supports_group_feedback=True,
        web_tab="favorite_grid",
        aliases=("九宫格", "本命榜", "grid"),
    ),
    FeatureEntry(
        id="voice.poke",
        name="戳一戳语音互动",
        category="互动",
        summary="配置个人戳一戳角色、服装与语音语言偏好。",
        qq_commands=("/妮姬 语音", "/妮姬 语音 开|关", "/妮姬 语音 角色 <角色名>", "/妮姬 语音 语言 <ja|en|ko>"),
        example_command="/妮姬 语音",
        entry_mode="both",
        web_tab="settings",
        aliases=("语音", "voice"),
    ),
    # ---- 管理 ----
    FeatureEntry(
        id="admin.ops",
        name="运行健康与调度管理",
        category="管理",
        summary="管理员查看磁盘/数据库/Web 健康状态、设定通知群与每日任务时间。",
        qq_commands=("/妮姬 管理 健康", "/妮姬 管理 设群", "/妮姬 管理 任务时间 08:00", "/妮姬 公告 订阅"),
        example_command="/妮姬 管理 健康",
        entry_mode="qq_only",
        admin_only=True,
        aliases=("管理", "admin", "公告订阅"),
    ),
)


_FEATURE_MAP: dict[str, FeatureEntry] = {entry.id: entry for entry in FEATURES}


def all_features() -> tuple[FeatureEntry, ...]:
    return FEATURES


def get_feature(feature_id: str) -> FeatureEntry | None:
    return _FEATURE_MAP.get(feature_id)


def _is_enabled(entry: FeatureEntry, flags: Mapping[str, bool] | None) -> bool:
    if not entry.feature_flag:
        return True
    if not flags:
        return False
    return bool(flags.get(entry.feature_flag, False))


def filter_features(
    *,
    surface: str = "all",
    include_admin: bool = False,
    flags: Mapping[str, bool] | None = None,
) -> tuple[FeatureEntry, ...]:
    """按入口界面、管理员权限与开关过滤统一功能目录。"""
    results: list[FeatureEntry] = []
    for entry in FEATURES:
        if entry.admin_only and not include_admin:
            continue
        if surface == "hall":
            if entry.entry_mode not in {"hall", "both"}:
                continue
            if entry.requires_binding:
                continue
        elif surface == "workspace":
            if entry.entry_mode == "hall" and entry.id != "portal.hall":
                # 工作台也展示公共查询快捷入口元数据，但主体聚焦个人/复合工具。
                pass
        results.append(entry)
    return tuple(
        item
        for item in results
        if _is_enabled(item, flags) or surface == "all"
    )


def _serialize_entry(entry: FeatureEntry, *, enabled: bool) -> dict[str, Any]:
    return {
        "id": entry.id,
        "name": entry.name,
        "category": entry.category,
        "summary": entry.summary,
        "qq_commands": list(entry.qq_commands),
        "example_command": entry.example_command,
        "entry_mode": entry.entry_mode,
        "requires_binding": entry.requires_binding,
        "admin_only": entry.admin_only,
        "supports_group_feedback": entry.supports_group_feedback,
        "web_tab": entry.web_tab,
        "enabled": enabled,
        "note": entry.note,
    }


def public_catalog_payload(flags: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """生成公共功能大厅专用目录：不包含任何个人数据或需要个人绑定的私密入口。"""
    items = []
    for entry in FEATURES:
        if entry.admin_only or entry.requires_binding:
            continue
        if entry.entry_mode not in {"hall", "both"}:
            continue
        items.append(_serialize_entry(entry, enabled=_is_enabled(entry, flags)))
    return {
        "surface": "hall",
        "categories": [
            {"id": c.id, "name": c.name, "summary": c.summary, "order": c.order}
            for c in CATEGORIES
            if c.id != "admin"
        ],
        "features": items,
    }


def workspace_catalog_payload(
    flags: Mapping[str, bool] | None = None, *, include_admin: bool = False
) -> dict[str, Any]:
    """生成个人指挥官工作台目录：涵盖绑定、个人档案、五队编组与个性化工具。"""
    items = []
    for entry in FEATURES:
        if entry.admin_only and not include_admin:
            continue
        items.append(_serialize_entry(entry, enabled=_is_enabled(entry, flags)))
    return {
        "surface": "workspace",
        "categories": [
            {"id": c.id, "name": c.name, "summary": c.summary, "order": c.order}
            for c in CATEGORIES
            if include_admin or c.id != "admin"
        ],
        "features": items,
    }
