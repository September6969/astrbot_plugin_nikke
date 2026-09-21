# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 内容质量策略。

这个模块只负责“内容是什么、展示时应排在什么位置、两个来源是否可能是
同一个事件”这类纯函数策略。它不改变 CanonicalEvent 的运行时状态，也不
发起网络请求，方便解析器、合并器和离线测试共同使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
import re
import unicodedata
from typing import Any, Iterable


class DisplayTier(str, Enum):
    """Operations Feed 的展示层级。"""

    CORE = "CORE"
    SUPPORTING = "SUPPORTING"
    META = "META"


class IdentityDecision(str, Enum):
    """跨来源身份判断结果。"""

    MATCH = "MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    DISTINCT = "DISTINCT"


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


@dataclass(frozen=True)
class IdentityMatch:
    """跨来源身份评分及解释。"""

    score: int
    decision: IdentityDecision
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
        }


# 对外保留别名表，避免各适配器继续维护一份不一致的关键词。
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "coop": ("协同作战", "协同", "coordinated operation", "co-op", "coop"),
    "solo_raid": ("单人突袭", "solo raid"),
    "union_raid": ("联盟突袭", "union raid"),
    "special_arena": ("特殊竞技场", "special arena"),
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
    "pass": ("mission pass", "pass", "任务通行证"),
}

_CATEGORY_ORDER = (
    "coop",
    "solo_raid",
    "union_raid",
    "special_arena",
    "recruit",
    "double_reward",
    "maintenance",
    "update",
    "pass",
)
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


def normalize_title(value: Any) -> str:
    """归一化跨来源标题，保留月份、Season、角色名和数字。

    仅移除装饰性包装和公告语气，不把角色名、期数或季数当作噪声。
    """

    text = _fold(value)
    text = re.sub(r"第\s*(\d+)\s*[期季]", r" season \1", text)
    text = re.sub(r"[\[\]【】()（）<>《》{}]", " ", text)
    aliases = (
        ("coordinated operation", "coop"),
        ("co op", "coop"),
        ("solo raid", "solo_raid"),
        ("union raid", "union_raid"),
        ("special arena", "special_arena"),
        ("special recruit", "recruit"),
        ("特殊招募", "recruit"),
        ("招募", "recruit"),
        ("recruitment", "recruit"),
        ("pick up", "recruit"),
        ("pickup", "recruit"),
        ("mission pass", "pass"),
        ("full burst", "double_reward"),
        ("fullburst", "double_reward"),
        ("co-op", "coop"),
        ("协同作战", "coop"),
        ("单人突袭", "solo_raid"),
        ("联盟突袭", "union_raid"),
        ("特殊竞技场", "special_arena"),
        ("任务通行证", "pass"),
    )
    for source, target in aliases:
        text = text.replace(_fold(source), target)

    # 公告型包装词不承担事件身份；Season、月份、角色名和数字保留。
    decorative = {
        "new",
        "notice",
        "announcement",
        "opening",
        "starts",
        "start",
        "ends",
        "end",
        "deadline",
        "available",
        "event",
        "activity",
        "活动",
        "公告",
        "开启",
        "开始",
        "截止",
    }
    tokens = [token for token in re.split(r"[^\w\u4e00-\u9fff]+", text) if token]
    tokens = [token for token in tokens if token not in decorative]
    return " ".join(tokens)


def title_similarity(left: Any, right: Any) -> float:
    """返回 0~1 的归一化标题相似度。"""

    a = normalize_title(left)
    b = normalize_title(right)
    raw_left = _fold(left)
    raw_right = _fold(right)
    if not a or not b:
        return 1.0 if raw_left and raw_left == raw_right else 0.0
    if a == b or a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


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


def score_identity(left: Any, right: Any) -> IdentityMatch:
    """为跨来源合并提供保守的 MATCH / AMBIGUOUS / DISTINCT 决策。"""

    score = 0
    reasons: list[str] = []
    explicit_same_source = False
    cycle_exact = False
    detail_exact = False
    exact_time_window = False
    left_scope = str(getattr(left, "server_scope", "GLOBAL") or "GLOBAL")
    right_scope = str(getattr(right, "server_scope", "GLOBAL") or "GLOBAL")
    if left_scope != right_scope and "UNKNOWN" not in (left_scope, right_scope):
        return IdentityMatch(-100, IdentityDecision.DISTINCT, ("scope_conflict:-100",))

    left_cycle = str(getattr(left, "cycle_id", "") or "")
    right_cycle = str(getattr(right, "cycle_id", "") or "")
    if left_cycle and right_cycle:
        if left_cycle == right_cycle:
            score += 45
            cycle_exact = True
            reasons.append("cycle_exact:+45")
        else:
            return IdentityMatch(-100, IdentityDecision.DISTINCT, ("cycle_conflict:-100",))

    left_sources = {str(item).casefold() for item in getattr(left, "sources", [])}
    right_sources = {str(item).casefold() for item in getattr(right, "sources", [])}
    left_primary = str(getattr(left, "primary_source", "") or "").casefold()
    right_primary = str(getattr(right, "primary_source", "") or "").casefold()
    if left_primary:
        left_sources.add(left_primary)
    if right_primary:
        right_sources.add(right_primary)
    if left_sources & right_sources and getattr(left, "id", None) and getattr(right, "id", None) and getattr(left, "id", None) != getattr(right, "id", None):
        return IdentityMatch(-100, IdentityDecision.DISTINCT, ("same_source_id_conflict:-100",))
    if getattr(left, "id", None) == getattr(right, "id", None) and left_sources & right_sources:
        score += 100
        explicit_same_source = True
        reasons.append("explicit_same_source:+100")

    left_detail = str(getattr(left, "detail_url", "") or "")
    right_detail = str(getattr(right, "detail_url", "") or "")
    if left_detail and right_detail and left_detail == right_detail:
        score += 50
        detail_exact = True
        reasons.append("detail_reference:+50")

    left_type = str(getattr(left, "event_type", "event") or "event")
    right_type = str(getattr(right, "event_type", "event") or "event")
    if left_type == right_type:
        score += 20
        reasons.append("category_exact:+20")
    elif "event" in (left_type, right_type):
        score += 10
        reasons.append("category_generic:+10")
    else:
        score -= 50
        reasons.append("category_conflict:-50")

    title_score = title_similarity(getattr(left, "title", ""), getattr(right, "title", ""))
    if title_score >= 0.85:
        score += 35
        reasons.append("title_similarity:+35")
    elif title_score >= 0.65:
        score += 25
        reasons.append("title_similarity:+25")
    elif title_score >= 0.45:
        score += 10
        reasons.append("title_similarity:+10")

    start_left = getattr(left, "start_at", None)
    start_right = getattr(right, "start_at", None)
    if isinstance(start_left, datetime) and isinstance(start_right, datetime):
        start_diff = abs((start_left - start_right).total_seconds())
        if start_diff <= 600:
            score += 25
            reasons.append("start_within_10m:+25")
        elif start_diff <= 7200:
            score += 15
            reasons.append("start_within_2h:+15")

    end_left = getattr(left, "end_at", None)
    end_right = getattr(right, "end_at", None)
    if isinstance(end_left, datetime) and isinstance(end_right, datetime):
        end_diff = abs((end_left - end_right).total_seconds())
        if end_diff <= 600:
            score += 25
            reasons.append("end_within_10m:+25")
        elif end_diff <= 7200:
            score += 15
            reasons.append("end_within_2h:+15")

        # 只有标题本身不够相似且两个区间完全不重叠时，才认定时间不可能是同一事件。
        if isinstance(start_left, datetime) and isinstance(start_right, datetime):
            overlaps = max(start_left, start_right) < min(end_left, end_right)
            if not overlaps and title_score < 0.85:
                score -= 100
                reasons.append("impossible_interval:-100")
            elif start_diff <= 600 and end_diff <= 600:
                # 两端都精确对齐时，足以抵消跨语言/官方公告标题改写造成的低相似度。
                score += 10
                exact_time_window = True
                reasons.append("exact_time_window:+10")

    # 仅靠“同类别 + 同时间 + 标题看起来相似”不能覆盖两个不同角色的同时活动。
    # 自动合并必须拥有可解释的强身份证据：同源同 ID、同一周期、同一详情页，
    # 或标题高度相似且类别与完整时间窗口同时对齐。否则最高只能是 AMBIGUOUS。
    strong_title_time = title_score >= 0.85 and left_type == right_type and exact_time_window
    strong_evidence = explicit_same_source or cycle_exact or detail_exact or strong_title_time
    if strong_title_time:
        reasons.append("strong_title_time")
    if not strong_evidence:
        reasons.append("strong_identity_gate:missing")

    if strong_evidence and score >= 75:
        decision = IdentityDecision.MATCH
    elif strong_evidence and score >= 50:
        # 周期/详情引用等强证据允许略低于标题时间窗的总分，但仍不能越过
        # 前面的 scope/cycle/source ID 冲突早退保护。
        decision = IdentityDecision.MATCH
    elif score >= 50:
        decision = IdentityDecision.AMBIGUOUS
    else:
        decision = IdentityDecision.DISTINCT
    return IdentityMatch(score, decision, tuple(reasons))


_DEADLINE_KEYWORDS = (
    "时间",
    "截止",
    "结束",
    "开始",
    "开放",
    "维护",
    "deadline",
    "until",
    "ends",
    "starts",
    "opens",
    "available after",
)
_DATE_PATTERNS = (
    re.compile(r"\b20\d{2}[./-]\d{1,2}(?:[./-]\d{1,2})?\b"),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", re.I),
    re.compile(r"\b\d{1,2}月\d{1,2}日\b"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),
)


def should_parse_deadlines(title: Any, body: Any) -> bool:
    """官方公告截止日期的廉价前置过滤器。

    没有时间关键词或日期/时间形态时，不启动正文解析器，避免每次刷新扫描
    全部普通公告；过滤只影响解析开销，不会删除原始公告记录。
    """

    text = _fold(f"{title} {body}")
    has_keyword = any(_contains_alias(text, keyword) for keyword in _DEADLINE_KEYWORDS)
    has_date = any(pattern.search(text) for pattern in _DATE_PATTERNS)
    return has_keyword and has_date
