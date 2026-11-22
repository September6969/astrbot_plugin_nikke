# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 内容质量策略。

这个模块只负责“内容是什么、展示时应排在什么位置”这类纯函数策略；
跨来源身份评分与模糊去重已随停用的 GameKee/官方公告源在 PR-6B 删除。它不改变 CanonicalEvent 的运行时状态，也不
发起网络请求，方便解析器、合并器和离线测试共同使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
import unicodedata
from typing import Any, Iterable


class DisplayTier(str, Enum):
    """Operations Feed 的展示层级。"""

    CORE = "CORE"
    SUPPORTING = "SUPPORTING"
    META = "META"


@dataclass(frozen=True)
class DisplayRelevance:
    """可解释的展示相关性结果。"""

    score: int
    tier: DisplayTier
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier.value,
            "reasons": list(self.reasons),
        }


# 对外保留别名表，避免各适配器继续维护一份不一致的关键词。
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "login": ("签到", "簽到", "login event", "log in event", "check in"),
    "free_reward": ("免费领取", "免費領取", "免费招募", "免費招募", "免费获得", "免費獲得", "免费获取", "free recruit", "free recruitment", "free costume", "free nikke", "free reward", "distribution event"),
    "story_event": ("支线", "支線", "剧情活动", "劇情活動", "story event"),
    "coop": ("协同作战", "协同", "coordinated operation", "co-op", "coop"),
    "solo_raid": ("单人突袭", "个人突袭", "個人突襲", "solo raid"),
    "union_raid": ("联盟突袭", "union raid"),
    "special_arena": ("特殊竞技场", "special arena"),
    "mini_game": ("小游戏", "mini game", "mini-game"),
    "limited_stage": ("限时通关", "limited stage", "trail marker"),
    "costume_gacha": (
        "costume gacha",
        "时装转盘",
        "服装转盘",
        "转盘抽奖",
        "转盘",
    ),
    "limited_costume": ("limited costume", "限定时装", "限定服装"),
    "recruit": ("招募", "pick up", "pickup", "recruitment", "special recruit", "recruit"),
    "double_reward": (
        "full burst",
        "fullburst",
        "双倍",
        "2倍",
        "double reward",
        "double drop",
    ),
    "maintenance": ("维护", "maintenance"),
    "update": ("版本更新", "客户端更新", "update"),
    "announcement": ("公告", "announcement", "notice"),
    "package": ("礼包", "package", "bundle"),
    "pass": ("mission pass", "pass", "任务通行证"),
}

_CATEGORY_ORDER = (
    "login",
    "free_reward",
    "story_event",
    "coop",
    "solo_raid",
    "union_raid",
    "special_arena",
    "mini_game",
    "limited_stage",
    "costume_gacha",
    "limited_costume",
    "recruit",
    "double_reward",
    "maintenance",
    "update",
    "announcement",
    "package",
    "pass",
)
ACTIVITY_CATEGORIES = frozenset(
    {
        "event",
        "login",
        "free_reward",
        "story_event",
        "pass",
        "mini_game",
        "limited_stage",
        "coop",
        "solo_raid",
        "union_raid",
        "special_arena",
        "double_reward",
    }
)
META_CATEGORIES = frozenset({"maintenance", "update", "announcement", "package"})
DISPLAY_GROUP_ORDER = {
    "activity": 0,
    "recruit": 1,
    "costume_gacha": 2,
    "limited_costume": 3,
    "meta": 4,
}
_UPDATE_DESCRIPTION_ALIASES = (
    "版本更新",
    "客户端更新",
    "更新公告",
    "version update",
    "client update",
    "update notice",
    "patch update",
    "patch notes",
)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _contains_alias(text: str, alias: str) -> bool:
    alias = _fold(alias)
    if not alias:
        return False
    # 中文不需要词边界；英文需要，避免 pass 命中 compass 等普通单词。
    if any("\u4e00" <= char <= "\u9fff" for char in alias):
        return alias in text
    pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _category_hit(category: str, text: str, *, field: str) -> bool:
    aliases = CATEGORY_ALIASES[category]
    for alias in aliases:
        # 描述里的“updated rewards”不是版本更新，不能因普通英语出现 update
        # 就把内容提升为 update。标题、标签和 activity_kind 则保留完整别名表。
        if category == "update" and field == "description":
            if alias == "update":
                continue
            if alias not in _UPDATE_DESCRIPTION_ALIASES:
                continue
        if _contains_alias(text, alias):
            return True
    return False


def classify_explicit_title(title: str) -> tuple[str, float, str] | None:
    """按标题中的明确语义分类，优先于 tag/activity_kind/description。"""

    text = _fold(title)
    if not text:
        return None

    explicit_rules = (
        ("login", CATEGORY_ALIASES["login"], "explicit_title:login"),
        ("free_reward", CATEGORY_ALIASES["free_reward"], "explicit_title:free_reward"),
        ("story_event", CATEGORY_ALIASES["story_event"], "explicit_title:story_event"),
        ("limited_costume", ("limited costume", "限定时装", "限定服装"), "explicit_title:limited_costume"),
        (
            "costume_gacha",
            ("costume gacha", "时装转盘", "服装转盘", "转盘抽奖", "转盘"),
            "explicit_title:costume_gacha",
        ),
        ("mini_game", ("mini game", "mini-game", "小游戏"), "explicit_title:mini_game"),
        (
            "limited_stage",
            ("limited stage", "限时通关", "trail marker"),
            "explicit_title:limited_stage",
        ),
        (
            "pass",
            ("mission pass", "活动pass", "任务通行证", "通行证"),
            "explicit_title:pass",
        ),
        (
            "recruit",
            ("special recruit", "pick up", "pickup", "recruitment", "招募"),
            "explicit_title:recruit",
        ),
        ("coop", ("coordinated operation", "协同作战", "协同"), "explicit_title:coop"),
        ("solo_raid", ("solo raid", "单人突袭", "个人突袭", "個人突襲"), "explicit_title:solo_raid"),
        ("union_raid", ("union raid", "联盟突袭"), "explicit_title:union_raid"),
        ("special_arena", ("special arena", "特殊竞技场"), "explicit_title:special_arena"),
        ("double_reward", ("double reward", "double drop", "full burst", "双倍"), "explicit_title:double_reward"),
        ("maintenance", ("maintenance", "维护"), "explicit_title:maintenance"),
        ("update", ("version update", "client update", "版本更新", "客户端更新"), "explicit_title:update"),
        ("announcement", ("announcement", "notice", "公告"), "explicit_title:announcement"),
        ("package", ("package", "bundle", "礼包"), "explicit_title:package"),
    )
    for category, aliases, reason in explicit_rules:
        if any(_contains_alias(text, alias) for alias in aliases):
            return category, 1.0, reason

    # SSR 标题是明确的招募语义；只在标题中识别，避免描述里的奖励文字误分类。
    if re.search(r"(?<![a-z0-9])ssr(?![a-z0-9])", text):
        return "recruit", 1.0, "explicit_title:ssr_recruit"
    return None


def classify_category(
    title: str,
    tag: str = "",
    activity_kind: str = "",
    description: str = "",
) -> str:
    """用统一权重把活动归类。

    标题、标签和结构化 activity kind 的权重明显高于描述，防止描述里的
    “奖励更新”之类营销文案改变真正的活动类型。
    """

    explicit = classify_explicit_title(title)
    if explicit is not None:
        return explicit[0]

    description_text = _fold(description)
    # 仅认定明确的免费获取方式；普通招募中提到免费宝石不属于免费活动。
    if re.search(
        r"\blog in (?:during|throughout) (?:the )?event to (?:receive|claim|obtain)\b|"
        r"(?:登录|登入|登錄).{0,16}(?:即可|即送|领取|領取)|"
        r"(?:obtain|claim|receive).{0,60}\bfor free\b",
        description_text,
    ):
        return "free_reward"
    if (
        _contains_alias(description_text, "new character packages")
        or (
            _contains_alias(description_text, "available after")
            and _contains_alias(description_text, "maintenance")
        )
    ):
        return "package"

    fields = (
        ("title", _fold(title), 100),
        ("tag", _fold(tag), 70),
        ("activity_kind", _fold(activity_kind), 70),
        ("description", _fold(description), 20),
    )
    scores = {category: 0 for category in _CATEGORY_ORDER}
    for field, text, weight in fields:
        if not text:
            continue
        for category in _CATEGORY_ORDER:
            if _category_hit(category, text, field=field):
                scores[category] += weight

    best = max(_CATEGORY_ORDER, key=lambda category: (scores[category], -_CATEGORY_ORDER.index(category)))
    return best if scores[best] > 0 else "event"


def canonical_event_title(value: Any) -> str:
    """去除确定属于展示包装的标题前后缀，保留事件核心身份。"""

    text = _fold(value)
    if not text:
        return ""

    # 只剥离标题最前面的包装块；角色名、Season、月份、编号不会被按位置猜测删除。
    bracket_prefix = re.compile(r"^\s*(?:\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）)\s*")
    while True:
        stripped = bracket_prefix.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped

    # 签到天数和 Pass 角色备注属于结构化包装，不能参与跨语言活动名称比较。
    text = re.sub(r"^\d+\s+day login event\s*[:：–—-]?\s*", "", text)
    text = re.sub(r"\s*\(\d+日\)$", "", text)
    text = re.sub(r"(?<=pass)\s*\([\u4e00-\u9fff·\s]+\)$", "", text)
    wrapper_prefixes = (
        "new story event",
        "story event",
        "limited costume",
        "costume gacha",
        "mini game",
        "mission pass",
        "activity pass",
        "活动pass",
        "任务通行证",
        "limited stage",
        "ssr",
        "special recruit",
    )
    for prefix in wrapper_prefixes:
        before = text
        pattern = rf"^{re.escape(_fold(prefix))}(?:\s*[:：-]\s*|\s+)"
        text = re.sub(pattern, "", text, count=1)
        if text != before:
            break

    # Event/Activity 是包装后缀；核心名称内的同名词不在这里处理。
    text = re.sub(r"\s+(?:event|activity)$", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def category_family(category: Any) -> str:
    """返回 Operations Feed 使用的稳定分类族。"""

    normalized = _fold(category).replace(" ", "_")
    if normalized in ACTIVITY_CATEGORIES:
        return "activity"
    if normalized in {"recruit", "recruitment"}:
        return "recruit"
    if normalized == "costume_gacha":
        return "costume_gacha"
    if normalized == "limited_costume":
        return "limited_costume"
    if normalized in META_CATEGORIES:
        return "meta"
    return "unknown"


def operations_display_group(event_or_category: Any) -> int:
    """返回 Operations Feed 的展示组序号，META 始终位于最后。"""

    if isinstance(event_or_category, str):
        category = event_or_category
    else:
        category = _event_value(
            event_or_category,
            "event_type",
            _event_value(event_or_category, "category", "event"),
        )
    family = category_family(category)
    # 未知分类保留在活动区，避免新来源字段导致内容静默消失。
    return DISPLAY_GROUP_ORDER.get(family, DISPLAY_GROUP_ORDER["activity"])


def _precision_rank(value: Any) -> int:
    normalized = str(getattr(value, "value", value) or "UNKNOWN").upper()
    return {"EXACT": 0, "DATE_ONLY": 1}.get(normalized, 2)


def _datetime_sort_key(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.max.replace(tzinfo=timezone.utc)


def _stable_identity(event: Any) -> str:
    return str(
        getattr(
            event,
            "identity_key",
            getattr(event, "id", getattr(event, "event_id", "")),
        )
        or ""
    )


def operations_display_sort_key(event: Any, status: str) -> tuple[Any, ...]:
    """按业务展示组排序，不改变 canonical_models.active_sort_key。"""

    status_value = str(getattr(status, "value", status) or "").upper()
    group = operations_display_group(event)
    stable_id = _stable_identity(event)
    if status_value == "ACTIVE":
        end_at = getattr(event, "end_at", None)
        return (
            group,
            _precision_rank(getattr(event, "end_precision", "UNKNOWN")),
            _datetime_sort_key(end_at),
            -get_display_relevance(event).score,
            stable_id,
        )
    start_at = getattr(event, "start_at", None)
    return (group, _datetime_sort_key(start_at), stable_id)


def sort_operations_display_events(events: Iterable[Any], status: str) -> list[Any]:
    """按 Operations Feed 的分类族和时间契约稳定排序。"""

    return sorted(events, key=lambda event: operations_display_sort_key(event, status))


def _event_value(event: Any, name: str, default: Any = None) -> Any:
    value = getattr(event, name, default)
    if value is not None:
        return value
    metadata = getattr(event, "metadata", {})
    return metadata.get(name, default) if isinstance(metadata, dict) else default


def _metadata(event: Any) -> dict[str, Any]:
    value = getattr(event, "metadata", {})
    return value if isinstance(value, dict) else {}


def _has_official_evidence(event: Any) -> bool:
    if "official" in {str(item).casefold() for item in getattr(event, "sources", [])}:
        return True
    evidence = getattr(event, "field_evidence", {})
    if isinstance(evidence, dict):
        return any(
            isinstance(item, dict) and str(item.get("source", "")).casefold() == "official"
            for values in evidence.values()
            if isinstance(values, list)
            for item in values
        )
    return False


class RelevancePolicy:
    """集中定义展示评分、阈值和稳定排序。"""

    BASE_SCORES = {
        "solo_raid": 45,
        "union_raid": 45,
        "coop": 40,
        "recruit": 40,
        "special_arena": 35,
        "event": 30,
        "pass": 30,
        "double_reward": 25,
        "maintenance": 10,
        "update": 5,
    }
    TIER_RANK = {
        DisplayTier.CORE: 3,
        DisplayTier.SUPPORTING: 2,
        DisplayTier.META: 1,
    }

    @classmethod
    def classify_tier(cls, score: int) -> DisplayTier:
        if score >= 55:
            return DisplayTier.CORE
        if score >= 30:
            return DisplayTier.SUPPORTING
        return DisplayTier.META

    @classmethod
    def score(cls, event: Any) -> DisplayRelevance:
        category = str(_event_value(event, "event_type", _event_value(event, "category", "event")) or "event")
        score = cls.BASE_SCORES.get(category, cls.BASE_SCORES["event"])
        reasons: list[str] = [f"category:{category}:{cls.BASE_SCORES.get(category, 30):+d}"]

        start_precision = str(getattr(event, "start_precision", "UNKNOWN"))
        end_precision = str(getattr(event, "end_precision", "UNKNOWN"))
        exact_start = start_precision == "EXACT" and getattr(event, "start_at", None) is not None
        exact_end = end_precision == "EXACT" and getattr(event, "end_at", None) is not None
        if exact_start:
            score += 8
            reasons.append("exact_start:+8")
        if exact_end:
            score += 8
            reasons.append("exact_end:+8")
        if exact_start and exact_end:
            score += 4
            reasons.append("exact_interval:+4")

        primary_source = str(getattr(event, "primary_source", "") or "").casefold()
        if primary_source == "gamekee":
            score += 5
            reasons.append("gamekee_primary:+5")
        if _has_official_evidence(event):
            score += 12
            reasons.append("official_evidence:+12")

        metadata = _metadata(event)
        image_urls = metadata.get("visual_candidates") or metadata.get("image_urls") or ()
        if getattr(event, "banner_url", None) or metadata.get("key_visual_url") or image_urls:
            score += 5
            reasons.append("key_visual:+5")

        try:
            importance = int(metadata.get("importance", 0) or 0)
        except (TypeError, ValueError):
            importance = 0
        importance_bonus = min(10, max(0, importance))
        if importance_bonus:
            score += importance_bonus
            reasons.append(f"importance:+{importance_bonus}")

        text = _fold(f"{getattr(event, 'title', '')} {metadata.get('description', '')}")
        penalty = 0
        if any(_contains_alias(text, phrase) for phrase in ("available after", "维护后", "礼包", "package", "bundle")):
            penalty = -20 if any(_contains_alias(text, phrase) for phrase in ("available after", "维护后")) else -15
        if penalty:
            score += penalty
            reasons.append(f"descriptive_package:{penalty}")

        tier = cls.classify_tier(score)
        return DisplayRelevance(score=max(0, score), tier=tier, reasons=tuple(reasons))

    @classmethod
    def rank_key(cls, event: Any, status: str) -> tuple[Any, ...]:
        relevance = get_display_relevance(event)
        tier_rank = cls.TIER_RANK[relevance.tier]
        stable_id = str(getattr(event, "identity_key", getattr(event, "id", getattr(event, "event_id", ""))))
        if status == "ACTIVE":
            end_at = getattr(event, "end_at", None)
            end_key = end_at.timestamp() if isinstance(end_at, datetime) else float("inf")
            # ACTIVE 先看结束紧迫度，再看相关性；不让低优先级长活动挤走快结束项目。
            return (end_key, -tier_rank, -relevance.score, stable_id)
        start_at = getattr(event, "start_at", None)
        start_key = start_at.timestamp() if isinstance(start_at, datetime) else float("inf")
        return (-tier_rank, -relevance.score, start_key, stable_id)


def score_display_relevance(event: Any) -> DisplayRelevance:
    return RelevancePolicy.score(event)


def get_display_relevance(event: Any) -> DisplayRelevance:
    stored = _metadata(event).get("display_relevance")
    if isinstance(stored, dict):
        try:
            tier = DisplayTier(str(stored.get("tier", "META")))
            return DisplayRelevance(int(stored.get("score", 0)), tier, tuple(stored.get("reasons", ())))
        except (TypeError, ValueError):
            pass
    return score_display_relevance(event)


def apply_display_relevance(event: Any) -> DisplayRelevance:
    relevance = score_display_relevance(event)
    metadata = getattr(event, "metadata", None)
    if isinstance(metadata, dict):
        metadata["display_relevance"] = relevance.to_dict()
    return relevance


def sort_display_events(events: Iterable[Any], status: str) -> list[Any]:
    return sorted(events, key=lambda event: RelevancePolicy.rank_key(event, status))


def calendar_display_title(title: str) -> str:
    """仅翻译明确的玩法词和标题包装，保留活动专名与角色名。"""
    replacements = (
        (r"\bCoordinated Operation\b", "协同作战"),
        (r"\bUnion Raid\b", "联盟突袭"),
        (r"\bSolo Raid\b", "个人突袭"),
        (r"\bFULL BURST DAY(?: Event)?\b", "限时双倍"),
        (r"\b(\d+)[- ]Day Login Event\b", r"\1日签到"),
        (r"\b(?:New )?Story Event\s*[:：-]?\s*", "支线活动 · "),
        (r"\bSpecial Recruit\b", "Pick Up"),
        (r"\bCostume Gacha\b", "转盘时装"),
        (r"\bFree Recruit(?:ment)?(?: Event)?\b", "免费招募"),

    )
    for pattern, replacement in replacements:
        title = re.sub(pattern, replacement, title, flags=re.I)
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    for month, name in enumerate(months, 1):
        title = re.sub(rf"\b{name} Mission Pass\b", f"{month}月 Pass", title, flags=re.I)
    return title


def include_calendar_event(event: Any) -> bool:
    """按用户范围排除宣传页及普通限时时装，转盘和免费奖励仍保留。"""
    title = str(getattr(event, "title", ""))
    category = str(getattr(event, "event_type", ""))
    if category in {"package", "update", "announcement", "special_arena"}:
        return False
    if re.search(r"\bpackages?\b|\bbundles?\b|礼包|禮包|temporary participation|simulation room.{0,8}overclock|临时参战|臨時參戰|角色试用|角色試用", title, re.I):
        return False
    if "四周年情报站" in title or "四週年情報站" in title:
        return False
    if category == "costume_gacha" or classify_category(title) == "costume_gacha":
        return True
    if category == "free_reward":
        return True
    return category != "limited_costume" and classify_category(title) != "limited_costume" and not any(
        word in title for word in ("限时时装", "限時時裝", "限时服装", "限時服裝")
    )
