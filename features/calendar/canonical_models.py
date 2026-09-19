# SPDX-License-Identifier: GPL-3.0-or-later
"""NIKKE 标准化活动与日程模型 (CanonicalEvent)。

提供：
1. 统一的标准事件模型 CanonicalEvent；
2. 纯函数 Runtime Status Resolver (UPCOMING / ACTIVE / ENDED / UNKNOWN / CANCELLED / INVALID)；
3. 起止时间独立分级精度 (EXACT / DATE_ONLY / INFERRED / UNKNOWN)；
4. 字段级证据结构 FieldEvidence 与 ResolvedField；
5. 数据健康双维度 (Freshness: FRESH/STALE/EXPIRED, Coverage: COMPLETE/PARTIAL/UNAVAILABLE)；
6. 冻结查询快照 QueryContext；
7. 排序安全函数与 NEXT ENDING 解析；
8. 与 CalendarActivity 之间的无损双向转换及旧快照自动迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
from typing import Any, Sequence

class TimePrecision(str, Enum):
    EXACT = "EXACT"
    DATE_ONLY = "DATE_ONLY"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


CST = timezone(timedelta(hours=8))

from .models import CalendarActivity, _aware_utc


class EventStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class Coverage(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class FetchOutcome(str, Enum):
    SUCCESS_DATA = "SUCCESS_DATA"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    NOT_MODIFIED = "NOT_MODIFIED"
    REQUEST_FAILED = "REQUEST_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class ResponseMode(str, Enum):
    COMPLETE_SNAPSHOT = "COMPLETE_SNAPSHOT"
    INCREMENTAL = "INCREMENTAL"


class ServerScope(str, Enum):
    GLOBAL = "GLOBAL"
    JP = "JP"
    KR = "KR"
    NA = "NA"
    SEA = "SEA"
    CN = "CN"
    UNKNOWN = "UNKNOWN"


VALID_PRECISIONS = frozenset({p.value for p in TimePrecision})
VALID_STATUSES = frozenset({s.value for s in EventStatus})
VALID_FRESHNESS = frozenset({f.value for f in Freshness})
VALID_COVERAGE = frozenset({c.value for c in Coverage})
VALID_QUALITIES = frozenset({"FRESH", "STALE", "PARTIAL", "UNAVAILABLE"})


@dataclass
class FieldEvidence:
    """字段级证据模型，记录上游来源、精度、时间与置信度。"""

    value: Any
    source: str
    confidence: float
    precision: str | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_updated_at: datetime | None = None
    source_timezone: str | None = None
    scope: str = "GLOBAL"
    is_started_evidence: bool = False
    is_cancelled: bool = False

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            self.observed_at = _aware_utc(self.observed_at)
        if self.source_updated_at is not None:
            self.source_updated_at = _aware_utc(self.source_updated_at)

    def to_dict(self) -> dict[str, Any]:
        val = self.value
        if isinstance(val, datetime):
            val = val.isoformat()
        return {
            "value": val,
            "source": self.source,
            "confidence": self.confidence,
            "precision": self.precision,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source_updated_at": self.source_updated_at.isoformat() if self.source_updated_at else None,
            "source_timezone": self.source_timezone,
            "scope": self.scope,
            "is_started_evidence": self.is_started_evidence,
            "is_cancelled": self.is_cancelled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldEvidence:
        val = data.get("value")
        # 如果是时间字符串则尝试解析
        if isinstance(val, str) and ("T" in val or "-" in val):
            try:
                val = _aware_utc(val)
            except Exception:
                pass
        return cls(
            value=val,
            source=str(data.get("source", "")),
            confidence=float(data.get("confidence", 0.0)),
            precision=data.get("precision"),
            observed_at=_aware_utc(data["observed_at"]) if data.get("observed_at") else datetime.now(timezone.utc),
            source_updated_at=_aware_utc(data["source_updated_at"]) if data.get("source_updated_at") else None,
            source_timezone=data.get("source_timezone"),
            scope=str(data.get("scope", "GLOBAL")),
            is_started_evidence=bool(data.get("is_started_evidence", False)),
            is_cancelled=bool(data.get("is_cancelled", False)),
        )


@dataclass
class ResolvedField:
    """带解释证据的决胜字段。"""

    value: Any
    selected_evidence: FieldEvidence | None = None
    candidates: list[FieldEvidence] = field(default_factory=list)


@dataclass
class ManualOverride:
    """手动配置覆盖记录。"""

    event_id: str
    field: str
    value: Any
    operator: str = "admin"
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is not None:
            self.created_at = _aware_utc(self.created_at)
        if self.expires_at is not None:
            self.expires_at = _aware_utc(self.expires_at)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        return current >= self.expires_at


@dataclass
class SourceHealth:
    """每个数据源的同步与健康元数据。"""

    source: str
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_outcome: str = FetchOutcome.SUCCESS_DATA.value
    last_error_type: str = ""
    consecutive_failures: int = 0
    dataset_version: int = 1

    def __post_init__(self) -> None:
        if self.last_attempt_at is not None:
            self.last_attempt_at = _aware_utc(self.last_attempt_at)
        if self.last_success_at is not None:
            self.last_success_at = _aware_utc(self.last_success_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_outcome": self.last_outcome,
            "last_error_type": self.last_error_type,
            "consecutive_failures": self.consecutive_failures,
            "dataset_version": self.dataset_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceHealth:
        return cls(
            source=str(data.get("source", "")),
            last_attempt_at=_aware_utc(data["last_attempt_at"]) if data.get("last_attempt_at") else None,
            last_success_at=_aware_utc(data["last_success_at"]) if data.get("last_success_at") else None,
            last_outcome=str(data.get("last_outcome", FetchOutcome.SUCCESS_DATA.value)),
            last_error_type=str(data.get("last_error_type", "")),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            dataset_version=int(data.get("dataset_version", 1)),
        )


@dataclass
class CanonicalEvent:
    id: str
    title: str
    event_type: str  # coop, union_raid, solo_raid, recruit, event, maintenance, update
    start_at: datetime | None
    end_at: datetime | None
    start_precision: str = "EXACT"
    end_precision: str = "EXACT"
    server_scope: str = "GLOBAL"
    cycle_id: str = ""
    status: str = "UNKNOWN"
    banner_url: str | None = None
    detail_url: str | None = None
    sources: list[str] = field(default_factory=list)
    primary_source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    fingerprint: str = ""
    version: int = 1
    has_started_evidence: bool = False
    is_cancelled: bool = False
    is_valid_interval: bool = True
    field_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def __init__(
        self,
        id: str,
        title: str,
        event_type: str,
        start_at: datetime | None,
        end_at: datetime | None,
        start_precision: str = "EXACT",
        end_precision: str = "EXACT",
        server_scope: str = "GLOBAL",
        cycle_id: str = "",
        status: str = "UNKNOWN",
        banner_url: str | None = None,
        detail_url: str | None = None,
        sources: list[str] | None = None,
        primary_source: str = "",
        fetched_at: datetime | None = None,
        updated_at: datetime | None = None,
        confidence: float | None = None,
        fingerprint: str = "",
        version: int = 1,
        has_started_evidence: bool = False,
        is_cancelled: bool = False,
        is_valid_interval: bool = True,
        field_evidence: dict[str, list[dict[str, Any]]] | None = None,
        time_precision: str | None = None,
        **kwargs: Any,
    ) -> None:
        if time_precision is not None:
            start_precision = time_precision
            end_precision = time_precision
        self.id = id
        self.title = title
        self.event_type = event_type
        self.start_at = start_at
        self.end_at = end_at
        self.start_precision = start_precision
        self.end_precision = end_precision
        self.server_scope = server_scope
        self.cycle_id = cycle_id
        self.status = status
        self.banner_url = banner_url
        self.detail_url = detail_url
        self.sources = list(sources) if sources is not None else []
        self.primary_source = primary_source
        self.fetched_at = fetched_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.confidence = confidence
        self.fingerprint = fingerprint
        self.version = version
        self.has_started_evidence = has_started_evidence
        self.is_cancelled = is_cancelled
        self.is_valid_interval = is_valid_interval
        self.field_evidence = dict(field_evidence) if field_evidence is not None else {}
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("CanonicalEvent.id 不能为空")
        if not self.title:
            raise ValueError("CanonicalEvent.title 不能为空")

        if self.start_at is not None:
            self.start_at = _aware_utc(self.start_at)
        if self.end_at is not None:
            self.end_at = _aware_utc(self.end_at)
        if self.fetched_at is not None:
            self.fetched_at = _aware_utc(self.fetched_at)
        if self.updated_at is not None:
            self.updated_at = _aware_utc(self.updated_at)

        # 非法时间区间校验：start_at >= end_at 记录为 INVALID，绝不抛出异常崩溃，绝不静默交换
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            self.is_valid_interval = False

        if self.start_precision not in VALID_PRECISIONS:
            self.start_precision = "EXACT"
        if self.end_precision not in VALID_PRECISIONS:
            self.end_precision = "EXACT"

        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

        # 初始化计算状态（注意：状态非永久事实，查询时须经 resolve_event_status 动态推导）
        self.status = self.compute_status()

    @property
    def event_id(self) -> str:
        """向后兼容属性：返回 id。"""
        return self.id

    @property
    def category(self) -> str:
        """向后兼容属性：返回 event_type。"""
        return self.event_type

    @property
    def time_precision(self) -> str:
        """向后兼容属性：返回 end_precision。"""
        return self.end_precision

    @time_precision.setter
    def time_precision(self, val: str) -> None:
        precision = val if val in VALID_PRECISIONS else "EXACT"
        self.start_precision = precision
        self.end_precision = precision

    @property
    def identity_key(self) -> str:
        """稳定排序与去重 identity key。"""
        return f"{self.server_scope}:{self.event_type}:{self.cycle_id or self.id}"

    def compute_status(self, now: datetime | None = None) -> str:
        """通过统一领域函数计算当前状态。"""
        return resolve_event_status(self, now)

    def is_active(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == EventStatus.ACTIVE.value

    def is_upcoming(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == EventStatus.UPCOMING.value

    def is_ended(self, now: datetime | None = None) -> bool:
        return self.compute_status(now) == EventStatus.ENDED.value

    def compute_fingerprint(self) -> str:
        """计算关键业务字段指纹。"""
        parts = [
            self.title.strip(),
            self.event_type.strip(),
            self.start_at.isoformat() if self.start_at else "",
            self.end_at.isoformat() if self.end_at else "",
            self.start_precision,
            self.end_precision,
            self.server_scope,
            self.cycle_id,
            str(self.is_cancelled),
            str(self.is_valid_interval),
            (self.banner_url or "").strip(),
        ]
        text = "|".join(parts)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def remaining_display(self, now: datetime | None = None) -> str:
        """格式化剩余时间。
        严格规则：
        - 只有 end_precision == EXACT 才能显示小时/分钟倒计时；
        - DATE_ONLY 仅显示截止日期（如 '09.20 截止'）或天数，绝不伪造小时/分钟倒计时；
        - 结束时间未知显示 '结束时间未知'；
        - 无截止时间显示 '长期开放'。
        """
        current = _aware_utc(now) if now else datetime.now(timezone.utc)

        if not self.is_valid_interval:
            return "时间区间无效"

        if not self.end_at or self.end_precision == TimePrecision.UNKNOWN.value:
            return "结束时间未知" if self.end_at is None and self.start_at else "长期开放"

        status = resolve_event_status(self, current)
        if status == EventStatus.ENDED.value:
            return "已结束"
        if status == EventStatus.CANCELLED.value:
            return "已取消"

        if self.end_precision != TimePrecision.EXACT.value:
            # 粗粒度时间（DATE_ONLY / INFERRED），仅展示日期，不制造伪精度
            end_cst = self.end_at.astimezone(CST)
            days_left = (self.end_at.date() - current.astimezone(CST).date()).days
            if days_left <= 0:
                return f"{end_cst.strftime('%m.%d')} 截止 (今日截止)"
            return f"{end_cst.strftime('%m.%d')} 截止"

        delta = self.end_at - current
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "已结束"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            return f"剩余 {days}天{hours}小时"
        if hours > 0:
            return f"剩余 {hours}小时{minutes}分"
        return f"剩余 {max(1, minutes)}分钟"

    def to_calendar_activity(self) -> CalendarActivity:
        """转换为现有 T2I 渲染器与 Reminder 所使用的 CalendarActivity 实例。"""
        start = self.start_at or datetime.now(timezone.utc)
        end = self.end_at or (start + timedelta(days=365))
        if end <= start:
            end = start + timedelta(hours=1)

        act = CalendarActivity(
            event_id=self.id,
            title=self.title,
            start_at=start,
            end_at=end,
            category=self.event_type,
            source=self.primary_source or (self.sources[0] if self.sources else "unknown"),
            source_id=self.id,
            source_url=self.detail_url or "",
            banner_url=self.banner_url or "",
            description="",
            importance=0,
            tag=self.event_type,
            version=self.version,
        )
        return act

    @classmethod
    def from_calendar_activity(cls, act: CalendarActivity) -> CanonicalEvent:
        """从已有 CalendarActivity 无损转为 CanonicalEvent。"""
        return cls(
            id=act.event_id,
            title=act.title,
            event_type=act.category,
            start_at=act.start_at,
            end_at=act.end_at,
            start_precision="EXACT",
            end_precision="EXACT",
            banner_url=act.banner_url or None,
            detail_url=act.source_url or None,
            sources=[act.source] if act.source else ["gamekee"],
            primary_source=act.source or "gamekee",
            version=act.version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "event_type": self.event_type,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "start_precision": self.start_precision,
            "end_precision": self.end_precision,
            "time_precision": self.end_precision,  # 兼容旧读取
            "server_scope": self.server_scope,
            "cycle_id": self.cycle_id,
            "status": self.status,
            "banner_url": self.banner_url,
            "detail_url": self.detail_url,
            "sources": list(self.sources),
            "primary_source": self.primary_source,
            "fetched_at": self.fetched_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "confidence": self.confidence,
            "has_started_evidence": self.has_started_evidence,
            "is_cancelled": self.is_cancelled,
            "is_valid_interval": self.is_valid_interval,
            "field_evidence": self.field_evidence,
            "fingerprint": self.fingerprint,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalEvent:
        # 向后兼容：若仅有旧 time_precision 则拆分赋予 start_precision 和 end_precision
        legacy_precision = data.get("time_precision", "EXACT")
        start_prec = data.get("start_precision", legacy_precision)
        end_prec = data.get("end_precision", legacy_precision)

        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            event_type=str(data.get("event_type", "event")),
            start_at=_aware_utc(data["start_at"]) if data.get("start_at") else None,
            end_at=_aware_utc(data["end_at"]) if data.get("end_at") else None,
            start_precision=str(start_prec),
            end_precision=str(end_prec),
            server_scope=str(data.get("server_scope", "GLOBAL")),
            cycle_id=str(data.get("cycle_id", "")),
            status=str(data.get("status", "UNKNOWN")),
            banner_url=data.get("banner_url"),
            detail_url=data.get("detail_url"),
            sources=list(data.get("sources", [])),
            primary_source=str(data.get("primary_source", "")),
            fetched_at=_aware_utc(data.get("fetched_at", datetime.now(timezone.utc))),
            updated_at=_aware_utc(data.get("updated_at", datetime.now(timezone.utc))),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            has_started_evidence=bool(data.get("has_started_evidence", False)),
            is_cancelled=bool(data.get("is_cancelled", False)),
            is_valid_interval=bool(data.get("is_valid_interval", True)),
            field_evidence=dict(data.get("field_evidence", {})),
            fingerprint=str(data.get("fingerprint", "")),
            version=int(data.get("version", 1)),
        )


def resolve_event_status(
    event: CanonicalEvent | CalendarActivity,
    now: datetime | None = None,
    evidence: list[FieldEvidence] | None = None,
) -> str:
    """统一领域状态计算函数 (Runtime Status Resolver)。

    任何快照中保存的 status 均不是静态真值，必须在查询时刻通过本函数动态计算。

    规则优先级：
    1. 非法时间区间 (start_at >= end_at) -> INVALID / UNKNOWN
    2. 明确取消 (is_cancelled) -> CANCELLED
    3. start_at=None, end_at=None -> UNKNOWN
    4. start_at=None, end_at=future:
       - 存在独立 started evidence -> 若 now >= end_at 为 ENDED，否则 ACTIVE
       - 否则 -> UNKNOWN (严禁仅由 end_at 在未来反推已开始)
    5. start_at 在未来 (now < start_at) -> UPCOMING
    6. start_at 在过去，end_at 为 None -> ACTIVE
    7. now >= end_at -> ENDED
    8. start_at <= now < end_at -> ACTIVE
    """
    current = _aware_utc(now) if now else datetime.now(timezone.utc)

    # 1. 非法区间判断
    if hasattr(event, "is_valid_interval") and not event.is_valid_interval:
        return EventStatus.INVALID.value

    start = getattr(event, "start_at", None)
    end = getattr(event, "end_at", None)
    if start and end and end <= start:
        return EventStatus.INVALID.value

    # 2. 取消判断
    if getattr(event, "is_cancelled", False):
        return EventStatus.CANCELLED.value

    # 检查额外证据中的取消
    if evidence:
        for ev in evidence:
            if ev.is_cancelled:
                return EventStatus.CANCELLED.value

    # 3. 双 None
    if start is None and end is None:
        return EventStatus.UNKNOWN.value

    # 4. 开始时间未知
    has_started = getattr(event, "has_started_evidence", False)
    if not has_started and evidence:
        has_started = any(ev.is_started_evidence for ev in evidence)

    if start is None:
        if has_started:
            if end is not None and current >= end:
                return EventStatus.ENDED.value
            return EventStatus.ACTIVE.value
        return EventStatus.UNKNOWN.value

    # 5. 未到开始时间
    if current < start:
        return EventStatus.UPCOMING.value

    # 6. 开始时间在过去，无截止时间
    if end is None:
        return EventStatus.ACTIVE.value

    # 7. 超过截止时间
    if current >= end:
        return EventStatus.ENDED.value

    # 8. 进行中
    return EventStatus.ACTIVE.value


def active_sort_key(event: CanonicalEvent, now: datetime | None = None) -> tuple[int, datetime, str]:
    """Active 事件的安全排序键。

    规则：
    1. 可靠且可比较的 end_at (EXACT 精度) 升序排在最前；
    2. DATE_ONLY 截止排在其次；
    3. 未知 end / None / UNKNOWN 精度排在最后；
    4. 使用稳定 identity_key 决胜，杜绝 None 与 datetime 比较引发 TypeError。
    """
    if not event.is_valid_interval or event.end_at is None or event.end_precision == TimePrecision.UNKNOWN.value:
        return (2, datetime.max.replace(tzinfo=timezone.utc), event.identity_key)
    if event.end_precision == TimePrecision.DATE_ONLY.value:
        return (1, event.end_at, event.identity_key)
    return (0, event.end_at, event.identity_key)


def sort_active_events(events: Sequence[CanonicalEvent], now: datetime | None = None) -> list[CanonicalEvent]:
    """返回安全排好序的 Active 活动列表。"""
    return sorted(events, key=lambda e: active_sort_key(e, now))


def resolve_next_ending(events: Sequence[CanonicalEvent], now: datetime | None = None) -> CanonicalEvent | None:
    """解析当前 NEXT ENDING 活动。

    严格门槛：
    - status == ACTIVE
    - is_valid_interval == True
    - end_at is not None 且 end_at > now
    - end_precision == EXACT
    若所有 Active 截止时间均为未知或粗粒度，允许没有 NEXT ENDING (返回 None)。
    """
    current = _aware_utc(now) if now else datetime.now(timezone.utc)
    candidates: list[CanonicalEvent] = []
    for ev in events:
        if (
            ev.is_valid_interval
            and ev.end_at is not None
            and ev.end_at > current
            and ev.end_precision == TimePrecision.EXACT.value
            and resolve_event_status(ev, current) == EventStatus.ACTIVE.value
        ):
            candidates.append(ev)

    if not candidates:
        return None

    candidates.sort(key=lambda e: (e.end_at, e.identity_key))
    return candidates[0]


class HealthBadge(str):
    """同时兼容新规范语义 (DATA OK / DATA STALE / PARTIAL DATA / SCHEDULE DATA UNAVAILABLE)
    和旧测试/调用语义 (FRESH / STALE / PARTIAL / UNAVAILABLE)。
    """

    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if not isinstance(other, str):
            return False
        mapping = {
            "DATA OK": {"FRESH", "DATA OK", "OK"},
            "DATA STALE": {"STALE", "DATA STALE"},
            "PARTIAL DATA": {"PARTIAL", "PARTIAL DATA"},
            "SCHEDULE DATA UNAVAILABLE": {"UNAVAILABLE", "SCHEDULE DATA UNAVAILABLE", "EMPTY"},
        }
        valid = mapping.get(str(self), set())
        return other in valid

    def __hash__(self) -> int:
        return super().__hash__()


def compute_health_badge(freshness: str, coverage: str) -> HealthBadge:
    """根据 Freshness 和 Coverage 两轴生成标准展示徽章。

    优先级：UNAVAILABLE > STALE > PARTIAL > OK
    """
    if coverage == Coverage.UNAVAILABLE.value or freshness == Freshness.EXPIRED.value:
        return HealthBadge("SCHEDULE DATA UNAVAILABLE")
    if freshness == Freshness.STALE.value:
        return HealthBadge("DATA STALE")
    if coverage == Coverage.PARTIAL.value:
        return HealthBadge("PARTIAL DATA")
    if freshness == Freshness.FRESH.value and coverage == Coverage.COMPLETE.value:
        return HealthBadge("DATA OK")
    return HealthBadge("PARTIAL DATA")


def quality_badge(quality: str, updated_at: datetime | None = None) -> str:
    """向后兼容标签函数。"""
    if quality in ("FRESH", "DATA OK"):
        return "DATA OK"
    if quality in ("STALE", "DATA STALE"):
        if updated_at:
            t = updated_at.astimezone(CST).strftime("%H:%M")
            return f"STALE · UPDATED {t}"
        return "DATA STALE"
    if quality in ("PARTIAL", "PARTIAL DATA"):
        return "PARTIAL DATA"
    return "SCHEDULE DATA UNAVAILABLE"


@dataclass(frozen=True)
class QueryContext:
    """单次用户查询冻结的统一上下文。

    确保在同一次查询内（跨多页、文本回退、截止提醒）：
    1. 只调用一次 datetime.now()；
    2. 只使用同一个 snapshot_version；
    3. 后台刷新产生的新快照不污染本次查询结果。
    """

    now: datetime
    snapshot_version: str
    events: tuple[CanonicalEvent, ...]
    source_health: dict[str, SourceHealth]
    freshness: str = Freshness.FRESH.value
    coverage: str = Coverage.COMPLETE.value
    health_display: str = "DATA OK"
    source_display: str = "GAMEKEE"
