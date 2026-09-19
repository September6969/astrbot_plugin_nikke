# SPDX-License-Identifier: GPL-3.0-or-later
"""统一日程服务 (ScheduleService)。

核心架构（完全遵循规范 v2）：
1. 抓取与查询解耦：用户命令只读本地不可变查询快照，不现场等待远程网络；
2. 状态查询时计算：status 不持久化为长期真值，统一由 resolve_event_status 运行时推导；
3. 每源 Last Known Good (LKG)：各源独立维护成功数据集，单源失败不误删历史数据；
4. 字段级证据与仲裁：Manual > Official (>=0.90) > GameKee > Fallback；
5. 手动覆盖层 (Manual Override Layer)：Base Evidence -> Base Resolved -> Override Layer -> Effective Event；
6. 跨源 Identity：基于 Server Scope、Event Type、Cycle/Season 与时间窗口，杜绝不同期次/区服误合并；
7. 时间与健康分离：content_updated_at、last_success_at、last_attempt_at 分离持久化，正确处理 304；
8. 起止时间精度贯穿：精确 start/end 精度控制倒计时、Urgency 与 Reminder 门槛；
9. 100% 兼容既有 CalendarService 的查询与分组接口。
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from .models import CalendarActivity, _aware_utc
from .visuals import CalendarVisualCache
from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    FieldEvidence,
    ResolvedField,
    resolve_field,
    SourceRole,
    FetchOutcome,
    ResponseMode,
    TimePrecision,
    EventStatus,
    Freshness,
    Coverage,
    SourceHealth,
    ManualOverride,
    QueryContext,
    resolve_event_status,
    active_sort_key,
    sort_active_events,
    safe_datetime_key,
    resolve_next_ending,
    compute_health_badge,
    quality_badge,
    CST,
)
from ...integrations.blablalink.fetch_client import FetchClient
from ...core.privacy import safe_exception_message
from astrbot_plugin_nikke.features.calendar.schedule_adapters import (
    BaseScheduleAdapter,
    GameKeeScheduleAdapter,
    OfficialAnnouncementScheduleAdapter,
    ManualOverrideScheduleAdapter,
    FetchResult,
)

logger = logging.getLogger("nikke.schedule.service")

CAT_LABELS = {
    "coop": "协同",
    "union_raid": "联盟突袭",
    "solo_raid": "单人突袭",
    "recruit": "招募",
    "maintenance": "维护",
    "update": "更新",
    "event": "活动",
}


class _ActivitiesDict(dict):
    """支持测试用例与旧代码直接对 _activities 进行字典操作的双向同步字典。"""

    def __init__(self, service: ScheduleService, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._service = service

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if hasattr(self, "_service") and self._service is not None:
            if isinstance(value, CanonicalEvent):
                self._service._events[key] = value
                self._service._base_events[key] = value
            elif isinstance(value, CalendarActivity):
                ev = CanonicalEvent.from_calendar_activity(value)
                self._service._events[key] = ev
                self._service._base_events[key] = ev

    def pop(self, key: str, default: Any = None) -> Any:
        res = super().pop(key, default)
        if hasattr(self, "_service") and self._service is not None:
            self._service._events.pop(key, None)
            self._service._base_events.pop(key, None)
        return res

    def clear(self) -> None:
        super().clear()
        if hasattr(self, "_service") and self._service is not None:
            self._service._events.clear()
            self._service._base_events.clear()


def _title_similarity(a: str, b: str) -> float:
    """计算两个活动标题的相似度。"""
    ca = "".join(c for c in a.casefold() if c.isalnum() or '\u4e00' <= c <= '\u9fff')
    cb = "".join(c for c in b.casefold() if c.isalnum() or '\u4e00' <= c <= '\u9fff')
    if not ca or not cb:
        return 0.0
    if ca == cb or ca in cb or cb in ca:
        return 1.0

    seq_ratio = difflib.SequenceMatcher(None, ca, cb).ratio()
    set_a, set_b = set(ca), set(cb)
    char_overlap = len(set_a & set_b) / max(1, min(len(set_a), len(set_b)))
    ba = {ca[i:i+2] for i in range(len(ca)-1)}
    bb = {cb[i:i+2] for i in range(len(cb)-1)}
    jaccard = (len(ba & bb) / len(ba | bb)) if (ba and bb) else 0.0
    return max(seq_ratio, char_overlap, jaccard)


def _build_identity_key(ev: CanonicalEvent) -> str:
    """构建事件跨源身份标识 (Identity)。

    优先顺序：
    1. Scope + EventType + Cycle/Season（针对突袭、协同等周期性活动）
    2. Scope + Source + ID
    """
    scope = ev.server_scope or "GLOBAL"
    if ev.cycle_id:
        return f"{scope}:{ev.event_type}:{ev.cycle_id}"
    return f"{scope}:{ev.primary_source or 'event'}:{ev.id}"


def _is_same_identity(a: CanonicalEvent, b: CanonicalEvent) -> bool:
    """跨源身份匹配：
    1. Scope 必须一致；
    2. 若两方均有 cycle_id，cycle_id 必须相同；
    3. 类型兼容（或一方为通用 event）；
    4. 时间窗口吻合且标题相似度 >= 0.35，或标题高度相似 >= 0.65。
    """
    scope_a = a.server_scope or "GLOBAL"
    scope_b = b.server_scope or "GLOBAL"
    if scope_a != scope_b and "UNKNOWN" not in (scope_a, scope_b):
        return False

    if a.cycle_id and b.cycle_id and a.cycle_id != b.cycle_id:
        return False

    if a.event_type != b.event_type and "event" not in (a.event_type, b.event_type):
        return False

    time_matched = False
    if a.start_at and b.start_at and a.end_at and b.end_at:
        start_diff = abs((a.start_at - b.start_at).total_seconds())
        end_diff = abs((a.end_at - b.end_at).total_seconds())
        if start_diff <= 7200 and end_diff <= 7200:
            time_matched = True
        else:
            return False

    similarity = _title_similarity(a.title, b.title)
    if time_matched and similarity >= 0.35:
        return True

    return similarity >= 0.65


_is_same_event = _is_same_identity


def _merge_two_events(base: CanonicalEvent, incoming: CanonicalEvent) -> CanonicalEvent:
    """字段级多源仲裁合并：
    - title: resolve_field("title", ...) -> GameKee (地道中文) > Official > 其他
    - banner_url / detail_url: resolve_field(...) -> GameKee > Official > 其他
    - start / end: 分别独立调用 resolve_field("start", ...) 和 resolve_field("end", ...)
      Official (置信度 >= 0.90) > GameKee > Official (< 0.90)
    - cancellation: 取消证据高优先级
    - event_type: Official (非通用 event) > GameKee > 其他
    - 记录合并后的完整证据链
    """
    merged_evidence: dict[str, list[dict[str, Any]]] = {k: list(v) for k, v in base.field_evidence.items()}
    for field_name, ev_list in incoming.field_evidence.items():
        merged_evidence.setdefault(field_name, []).extend(ev_list)

    def _collect_candidates(field_name: str, attr_name: str | None = None) -> list[Any]:
        attr = attr_name or field_name
        cands = list(merged_evidence.get(field_name, []))
        if not cands:
            for ev in (base, incoming):
                val = getattr(ev, attr, None)
                if val is not None and val != "":
                    src = ev.primary_source or (ev.sources[0] if ev.sources else "unknown")
                    conf = ev.confidence or 0.8
                    prec = getattr(ev, f"{field_name}_precision", None) or getattr(ev, f"{attr}_precision", None)
                    cands.append(FieldEvidence(
                        value=val,
                        source=src,
                        confidence=conf,
                        precision=prec,
                    ).to_dict())
        return cands

    # 1. 标题仲裁
    title_res = resolve_field("title", _collect_candidates("title"), default=incoming.title or base.title)
    title = title_res.value or incoming.title or base.title

    # 2. 宣传图与详情页仲裁
    banner_res = resolve_field("banner_url", _collect_candidates("banner_url"), default=incoming.banner_url or base.banner_url)
    banner = banner_res.value

    detail_res = resolve_field("detail_url", _collect_candidates("detail_url"), default=incoming.detail_url or base.detail_url)
    detail = detail_res.value

    # 3. 起止时间独立仲裁 (严格杜绝单端覆写造成缺失)
    start_res = resolve_field("start", _collect_candidates("start", "start_at"), default=base.start_at or incoming.start_at)
    end_res = resolve_field("end", _collect_candidates("end", "end_at"), default=base.end_at or incoming.end_at)

    start_at = start_res.value
    end_at = end_res.value

    # 精度决胜
    if start_res.selected_evidence and start_res.selected_evidence.precision:
        start_prec = start_res.selected_evidence.precision
    else:
        start_prec = incoming.start_precision if incoming.start_at == start_at else base.start_precision

    if end_res.selected_evidence and end_res.selected_evidence.precision:
        end_prec = end_res.selected_evidence.precision
    else:
        end_prec = incoming.end_precision if incoming.end_at == end_at else base.end_precision

    # 4. 事件类型仲裁
    type_res = resolve_field("event_type", _collect_candidates("event_type"), default=incoming.event_type or base.event_type)
    event_type = type_res.value or incoming.event_type or base.event_type

    # 5. 取消状态与独立开始证据
    cancel_res = resolve_field("cancellation", _collect_candidates("cancellation", "is_cancelled"), default=base.is_cancelled or incoming.is_cancelled)
    is_cancelled = bool(cancel_res.value)
    has_started = base.has_started_evidence or incoming.has_started_evidence

    # 6. 区间合法性
    is_valid = True
    if start_at and end_at and end_at <= start_at:
        is_valid = False

    combined_sources = list(dict.fromkeys(base.sources + incoming.sources))
    primary_source = "gamekee" if "gamekee" in combined_sources else ("official" if "official" in combined_sources else (base.primary_source or incoming.primary_source or "unknown"))
    confidence = max(base.confidence or 0.0, incoming.confidence or 0.0)
    event_id = base.id if base.primary_source == "gamekee" else (incoming.id if incoming.primary_source == "gamekee" else (base.id or incoming.id))

    merged = CanonicalEvent(
        id=event_id,
        title=title,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        start_precision=start_prec,
        end_precision=end_prec,
        server_scope=base.server_scope or incoming.server_scope,
        cycle_id=base.cycle_id or incoming.cycle_id,
        banner_url=banner,
        detail_url=detail,
        sources=combined_sources,
        primary_source=primary_source,
        confidence=confidence,
        is_cancelled=is_cancelled,
        has_started_evidence=has_started,
        is_valid_interval=is_valid,
        field_evidence=merged_evidence,
        version=max(base.version, incoming.version),
    )
    return merged


class ScheduleService:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        visual_cache: CalendarVisualCache | None | bool = None,
        fetch_client: FetchClient | None = None,
        announcement_service: Any = None,
        ttl_seconds: float = 300.0,
        **kwargs: Any,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 持久化文件规范
        self.events_path = self.data_dir / "schedule_events.json"
        self.health_path = self.data_dir / "schedule_health.json"
        self.cache_path = self.data_dir / "calendar_cache.json"  # 100% 兼容文件
        self.overrides_path = self.data_dir / "schedule_overrides.json"

        self.fetch_client = fetch_client or FetchClient()
        self.announcement_service = announcement_service
        self.ttl_seconds = ttl_seconds

        # 视觉缓存
        if visual_cache is False:
            self.visual_cache = None
        elif isinstance(visual_cache, CalendarVisualCache):
            self.visual_cache = visual_cache
        else:
            self.visual_cache = CalendarVisualCache(self.data_dir)

        # 每源 LKG 数据集 (source -> list[CanonicalEvent])
        self._source_datasets: dict[str, list[CanonicalEvent]] = {}
        # 每源健康元数据 (source -> SourceHealth)
        self._source_health: dict[str, SourceHealth] = {}
        # 手动覆盖层记录
        self._manual_overrides: list[ManualOverride] = []

        # 聚合存储与双向活动字典
        self._base_events: dict[str, CanonicalEvent] = {}
        self._events: dict[str, CanonicalEvent] = {}
        self._activities: _ActivitiesDict = _ActivitiesDict(self)
        self._has_snapshot: bool = False
        self.migrated_from_merged_snapshot: bool = False

        # 时间戳与版本分离
        self.content_updated_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_attempt_at: datetime | None = None
        self.last_updated_at: str | None = None  # 向后兼容字符串
        self._last_batch_hash: str = self._compute_batch_hash([])
        self._snapshot_version: str = "v1"

        # 健康双维度
        self.freshness: str = Freshness.EXPIRED.value
        self.coverage: str = Coverage.UNAVAILABLE.value
        self.last_sync_error: str = ""
        self.last_sync_report: dict[str, int] | None = None
        self.last_visual_sync: dict[str, int] | None = None

        self._sync_lock = asyncio.Lock()

        # 默认适配器链
        self.manual_adapter = ManualOverrideScheduleAdapter(self.overrides_path)
        self.adapters: list[BaseScheduleAdapter] = [
            self.manual_adapter,
            GameKeeScheduleAdapter(self.fetch_client),
            OfficialAnnouncementScheduleAdapter(self.announcement_service),
        ]

        self._load_cache()

    @property
    def data_quality(self) -> str:
        """向后兼容属性：由 Freshness 与 Coverage 计算得到。"""
        return compute_health_badge(self.freshness, self.coverage)

    @data_quality.setter
    def data_quality(self, val: str) -> None:
        pass

    def has_snapshot(self) -> bool:
        return self._has_snapshot

    def activity_count(self) -> int:
        return len(self._activities)

    def list_activities(self) -> list[CalendarActivity]:
        return list(self._activities.values())

    def list_canonical(self) -> list[CanonicalEvent]:
        return list(self._events.values())

    def resolve_visual_path(self, activity: CalendarActivity | CanonicalEvent | str) -> Path | None:
        if self.visual_cache is None:
            return None
        event_id = activity if isinstance(activity, str) else getattr(activity, "event_id", getattr(activity, "id", ""))
        return self.visual_cache.resolve_path(event_id)

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        """只接受 7、14、30 天，默认 14 天。"""
        if value is None or value == "":
            return 14
        if type(value) is bool:
            raise ValueError("日程范围只支持 7、14、30 天")
        if type(value) is int:
            if value in (7, 14, 30):
                return value
            raise ValueError("日程范围只支持 7、14、30 天")
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return 14
            if s.isascii() and s.isdecimal():
                v = int(s)
                if v in (7, 14, 30):
                    return v
        raise ValueError("日程范围只支持 7、14、30 天")

    def _sync_internal_stores(self, events: dict[str, CanonicalEvent]) -> None:
        """同步内部有效事件与 CalendarActivity。"""
        dict.clear(self._activities)
        self._events = dict(events)
        for eid, ev in self._events.items():
            dict.__setitem__(self._activities, eid, ev.to_calendar_activity())

    def _compute_batch_hash(self, events: Sequence[CanonicalEvent]) -> str:
        parts = [e.fingerprint for e in sorted(events, key=lambda x: x.id)]
        return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()

    def reload_overrides(self) -> None:
        """重新载入手动覆盖层并重新应用到 Base 数据集，不消耗网络请求。"""
        self._manual_overrides = self.manual_adapter.load_overrides()
        if self._base_events:
            effective = self._apply_manual_overrides(self._base_events)
            self._sync_internal_stores(effective)
            self._has_snapshot = bool(effective)
            self._update_health_state()

    def _apply_manual_overrides(self, base_events: dict[str, CanonicalEvent]) -> dict[str, CanonicalEvent]:
        """应用手动覆盖层：Base Evidence -> Base Resolved -> Manual Override -> Effective Event。

        删除 Override 自动恢复 Base 真实值。
        """
        now = datetime.now(timezone.utc)
        effective: dict[str, CanonicalEvent] = {}
        for eid, ev in base_events.items():
            data = ev.to_dict()
            effective[eid] = CanonicalEvent.from_dict(data)

        for override in self._manual_overrides:
            if override.is_expired(now):
                continue
            target_ev = effective.get(override.event_id)
            if target_ev is None:
                for cand in effective.values():
                    if cand.title == override.event_id:
                        target_ev = cand
                        break

            if target_ev is not None:
                field_name = override.field
                val = override.value
                if field_name in ("start_at", "end_at") and val:
                    val = _aware_utc(val)
                if hasattr(target_ev, field_name):
                    setattr(target_ev, field_name, val)
                if field_name == "end_at":
                    target_ev.end_precision = TimePrecision.EXACT.value
                target_ev.fingerprint = target_ev.compute_fingerprint()

        return effective

    def _merge_datasets(self) -> dict[str, CanonicalEvent]:
        """将各源独立的 LKG 数据集聚合并去重仲裁。"""
        all_events: list[CanonicalEvent] = []
        for src, events in self._source_datasets.items():
            all_events.extend(events)

        merged_list: list[CanonicalEvent] = []
        for incoming in all_events:
            matched_idx = -1
            for idx, existing in enumerate(merged_list):
                if existing.id == incoming.id or _is_same_identity(existing, incoming):
                    matched_idx = idx
                    break

            if matched_idx >= 0:
                merged_list[matched_idx] = _merge_two_events(merged_list[matched_idx], incoming)
            else:
                merged_list.append(incoming)

        base_dict: dict[str, CanonicalEvent] = {}
        for ev in merged_list:
            old = self._events.get(ev.id)
            if old is not None:
                v = old.version if ev.fingerprint == old.fingerprint else old.version + 1
            else:
                v = max(1, ev.version)
            object.__setattr__(ev, "version", v)
            base_dict[ev.id] = ev

        self._base_events = base_dict
        return self._apply_manual_overrides(base_dict)

    def _update_health_state(self) -> None:
        """评估 Freshness 和 Coverage 两轴。"""
        now = datetime.now(timezone.utc)

        # Coverage
        if not self._events and not self._source_datasets:
            self.coverage = Coverage.UNAVAILABLE.value
        else:
            # 仅检查当前适配器中的源
            has_failure = False
            for ad in self.adapters:
                h = self._source_health.get(ad.source_name)
                if h and h.consecutive_failures > 0:
                    has_failure = True
                    break
            if has_failure:
                self.coverage = Coverage.PARTIAL.value
            else:
                self.coverage = Coverage.COMPLETE.value

        # Freshness
        if self.last_success_at is None:
            self.freshness = Freshness.EXPIRED.value
        else:
            delta = (now - self.last_success_at).total_seconds()
            if delta <= self.ttl_seconds:
                self.freshness = Freshness.FRESH.value
            elif delta <= 72 * 3600:
                self.freshness = Freshness.STALE.value
            else:
                self.freshness = Freshness.EXPIRED.value

        # 若所有可贡献新鲜度的主源均失败但存在本地快照，置为 STALE
        active_freshness_adapters = [ad for ad in self.adapters if getattr(ad, "contributes_to_freshness", True)]
        if active_freshness_adapters and all(
            self._source_health.get(ad.source_name) and self._source_health[ad.source_name].consecutive_failures > 0
            for ad in active_freshness_adapters
        ) and (self._events or self._source_datasets):
            self.freshness = Freshness.STALE.value

    def _load_cache(self) -> None:
        """载入本地数据并支持新旧 schema 平滑自动迁移。"""
        self._manual_overrides = self.manual_adapter.load_overrides()
        self.migrated_from_merged_snapshot = False

        events_loaded = False
        if self.events_path.is_file():
            try:
                content = self.events_path.read_text(encoding="utf-8")
                data = json.loads(content)
                schema_version = int(data.get("schema", 1))

                if schema_version >= 4 and "source_datasets" in data:
                    raw_sources = data.get("source_datasets", {})
                    by_source: dict[str, list[CanonicalEvent]] = {}
                    for src, raw_list in raw_sources.items():
                        by_source[src] = [CanonicalEvent.from_dict(item) for item in raw_list]
                    self._source_datasets = by_source
                    self.migrated_from_merged_snapshot = False
                else:
                    raw_events = data.get("events", []) or data.get("merged_snapshot", [])
                    by_source = {}
                    for item in raw_events:
                        ev = CanonicalEvent.from_dict(item)
                        src = ev.primary_source or (ev.sources[0] if ev.sources else "gamekee")
                        by_source.setdefault(src, []).append(ev)
                    self._source_datasets = by_source
                    self.migrated_from_merged_snapshot = True

                self._last_batch_hash = data.get("fingerprint", "")
                self.content_updated_at = _aware_utc(data["content_updated_at"]) if data.get("content_updated_at") else None
                events_loaded = True
            except Exception as exc:
                logger.warning("[NIKKE] 读取 schedule_events.json 失败: %s", safe_exception_message(exc))

        if self.health_path.is_file():
            try:
                hdata = json.loads(self.health_path.read_text(encoding="utf-8"))
                self.last_success_at = _aware_utc(hdata["last_success_at"]) if hdata.get("last_success_at") else None
                self.last_attempt_at = _aware_utc(hdata["last_attempt_at"]) if hdata.get("last_attempt_at") else None
                raw_health = hdata.get("source_health", {})
                self._source_health = {
                    src: SourceHealth.from_dict(info) for src, info in raw_health.items() if isinstance(info, dict)
                }
            except Exception as exc:
                logger.warning("[NIKKE] 读取 schedule_health.json 失败: %s", safe_exception_message(exc))

        # 若新文件不存在，尝试从旧 calendar_cache.json 迁移
        if not events_loaded and self.cache_path.is_file():
            try:
                content = self.cache_path.read_text(encoding="utf-8")
                data = json.loads(content)
                raw_activities = data.get("activities", [])
                by_source = {}
                for item in raw_activities:
                    if "event_type" in item:
                        ev = CanonicalEvent.from_dict(item)
                    else:
                        act = CalendarActivity.from_dict(item)
                        ev = CanonicalEvent.from_calendar_activity(act)
                    src = ev.primary_source or "gamekee"
                    by_source.setdefault(src, []).append(ev)

                self._source_datasets = by_source
                self.migrated_from_merged_snapshot = True
                up_str = data.get("updated_at")
                if up_str:
                    up_dt = _aware_utc(up_str)
                    self.content_updated_at = up_dt
                    self.last_success_at = up_dt
                    self.last_attempt_at = up_dt
                events_loaded = True
                logger.info("[NIKKE] 成功从旧 calendar_cache.json 迁移载入 %d 条活动", sum(len(v) for v in by_source.values()))
            except Exception as exc:
                logger.warning("[NIKKE] 读取旧快照失败: %s", safe_exception_message(exc))

        if events_loaded:
            effective = self._merge_datasets()
            self._sync_internal_stores(effective)
            self._has_snapshot = bool(effective)
            self.last_updated_at = self.content_updated_at.isoformat() if self.content_updated_at else None
            self._update_health_state()
        else:
            self._has_snapshot = False
            self._sync_internal_stores({})
            self._update_health_state()

    def _save_cache(self, force_events: bool = False) -> None:
        """原子落盘：大事件数据仅在内容变更时写盘，健康元数据独立写盘。"""
        # 1. schedule_health.json
        health_payload = {
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "content_updated_at": self.content_updated_at.isoformat() if self.content_updated_at else None,
            "freshness": self.freshness,
            "coverage": self.coverage,
            "source_health": {src: h.to_dict() for src, h in self._source_health.items()},
        }
        tmp_health = self.health_path.with_suffix(".json.tmp")
        with open(tmp_health, "w", encoding="utf-8") as f:
            f.write(json.dumps(health_payload, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        tmp_health.replace(self.health_path)

        # 2. schedule_events.json 与 calendar_cache.json
        if force_events or not self.events_path.is_file():
            events_payload = {
                "schema": 4,
                "content_updated_at": self.content_updated_at.isoformat() if self.content_updated_at else datetime.now(timezone.utc).isoformat(),
                "fingerprint": self._last_batch_hash,
                "source_datasets": {
                    src: [ev.to_dict() for ev in ev_list]
                    for src, ev_list in self._source_datasets.items()
                },
                "merged_snapshot": [ev.to_dict() for ev in self._events.values()],
                "events": [ev.to_dict() for ev in self._events.values()],
            }
            tmp_events = self.events_path.with_suffix(".json.tmp")
            with open(tmp_events, "w", encoding="utf-8") as f:
                f.write(json.dumps(events_payload, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
            tmp_events.replace(self.events_path)

            legacy_payload = {
                "schema": 2,
                "updated_at": self.last_updated_at or datetime.now(timezone.utc).isoformat(),
                "activities": [ev.to_dict() for ev in self._events.values()],
            }
            tmp_cache = self.cache_path.with_suffix(".json.tmp")
            with open(tmp_cache, "w", encoding="utf-8") as f:
                f.write(json.dumps(legacy_payload, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
            tmp_cache.replace(self.cache_path)

    async def refresh_schedule_data(self) -> tuple[bool, str]:
        """统一多源刷新流程 (Refresh Path)。"""
        async with self._sync_lock:
            return await self._refresh_schedule_data()

    async def _refresh_schedule_data(self) -> tuple[bool, str]:
        now_utc = datetime.now(timezone.utc)
        self.last_attempt_at = now_utc
        self._manual_overrides = self.manual_adapter.load_overrides()

        source_errors: list[str] = []
        any_success = False

        for adapter in self.adapters:
            src = adapter.source_name
            health = self._source_health.setdefault(src, SourceHealth(source=src))
            health.last_attempt_at = now_utc

            try:
                res = None
                if hasattr(adapter, "fetch_result"):
                    res = await adapter.fetch_result()
                if not isinstance(res, FetchResult):
                    if hasattr(adapter, "fetch"):
                        events = await adapter.fetch()
                        res = FetchResult(
                            outcome=FetchOutcome.SUCCESS_DATA,
                            events=events,
                            source=src,
                        )
                    else:
                        raise RuntimeError(f"Adapter {src} has neither valid fetch_result nor fetch")
            except Exception as exc:
                err = safe_exception_message(exc)
                res = FetchResult(
                    outcome=FetchOutcome.REQUEST_FAILED,
                    error_message=err,
                    source=src,
                    response_mode=getattr(adapter, "response_mode", ResponseMode.COMPLETE_SNAPSHOT),
                )

            health.last_outcome = res.outcome.value

            contributes = getattr(adapter, "contributes_to_freshness", True)

            if res.outcome == FetchOutcome.SUCCESS_DATA:
                self._source_datasets[src] = res.events
                health.last_success_at = now_utc
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            elif res.outcome == FetchOutcome.SUCCESS_EMPTY:
                if adapter.response_mode == ResponseMode.COMPLETE_SNAPSHOT:
                    self._source_datasets[src] = []
                health.last_success_at = now_utc
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            elif res.outcome == FetchOutcome.NOT_MODIFIED:
                health.last_success_at = now_utc
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            else:
                health.consecutive_failures += 1
                health.last_error_type = res.error_message or res.outcome.value
                source_errors.append(f"{src}: {health.last_error_type}")
                logger.warning("[NIKKE] 数据源 %s 同步失败，保留历史 LKG: %s", src, health.last_error_type)

        if any_success:
            self.last_success_at = now_utc

        all_not_modified = bool(self.adapters) and all(
            self._source_health.get(ad.source_name) and self._source_health[ad.source_name].last_outcome == FetchOutcome.NOT_MODIFIED.value
            for ad in self.adapters
        )

        merged_effective = self._merge_datasets()
        new_batch_hash = self._compute_batch_hash(list(merged_effective.values()))
        content_changed = (new_batch_hash != self._last_batch_hash) and not all_not_modified

        if content_changed:
            self._last_batch_hash = new_batch_hash
            self.content_updated_at = now_utc
            self.last_updated_at = now_utc.isoformat()
            self._snapshot_version = f"v{int(time.time())}"

        self._sync_internal_stores(merged_effective)
        self._has_snapshot = bool(merged_effective)
        self.last_sync_error = "; ".join(source_errors) if source_errors else ""
        self._update_health_state()

        try:
            self._save_cache(force_events=content_changed)
        except Exception as exc:
            logger.error("[NIKKE] 日程持久化失败: %s", safe_exception_message(exc))

        if not any_success:
            err = "; ".join(source_errors) or "全部数据源抓取失败"
            self.last_sync_error = err
            return False, err

        if self.visual_cache is not None:
            try:
                self.last_visual_sync = await self.visual_cache.sync(list(self._activities.values()))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[NIKKE] 活动宣传图缓存失败，保留结构化日程: %s", safe_exception_message(exc))

        status_msg = "ok" if not source_errors else f"partial: {self.last_sync_error}"
        return True, status_msg

    async def sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        """兼容既有 sync_from_source 接口，支持事物级失败回滚。"""
        async with self._sync_lock:
            return await self._sync_from_source(fetcher)

    async def _sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        if fetcher is None:
            return await self._refresh_schedule_data()

        # 记录旧状态以备保存异常时回滚
        old_activities = dict(self._activities)
        old_events = dict(self._events)
        old_base = dict(self._base_events)
        old_sources = {k: list(v) for k, v in self._source_datasets.items()}
        old_timestamp = self.last_updated_at
        old_content_updated_at = self.content_updated_at
        old_last_success_at = self.last_success_at
        old_batch_hash = self._last_batch_hash
        old_has_snapshot = self._has_snapshot

        try:
            res = fetcher.fetch() if hasattr(fetcher, "fetch") else fetcher()
            incoming = await res if asyncio.iscoroutine(res) else res
            if not isinstance(incoming, list):
                raise ValueError(f"数据源返回必须是列表: {type(incoming)}")

            canonical_list: list[CanonicalEvent] = []
            for item in incoming:
                if isinstance(item, CanonicalEvent):
                    canonical_list.append(item)
                elif isinstance(item, CalendarActivity):
                    canonical_list.append(CanonicalEvent.from_calendar_activity(item))
                else:
                    raise ValueError(f"未知活动类型: {type(item)}")

            src = "custom"
            now = datetime.now(timezone.utc)
            self._source_datasets[src] = canonical_list
            self.last_success_at = now
            self.content_updated_at = now
            self.last_updated_at = now.isoformat()

            effective = self._merge_datasets()
            self._sync_internal_stores(effective)
            self._has_snapshot = bool(effective)
            self.last_sync_error = ""
            self._update_health_state()
            self.last_sync_report = getattr(fetcher, "last_scan", None)

            self._save_cache(force_events=True)

            if self.visual_cache is not None:
                try:
                    self.last_visual_sync = await self.visual_cache.sync(list(self._activities.values()))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("[NIKKE] 活动宣传图缓存失败，保留结构化日程: %s", safe_exception_message(exc))

            return True, "ok"
        except Exception as exc:
            # 事务性回滚
            self._activities = _ActivitiesDict(self, old_activities)
            self._events = old_events
            self._base_events = old_base
            self._source_datasets = old_sources
            self.last_updated_at = old_timestamp
            self.content_updated_at = old_content_updated_at
            self.last_success_at = old_last_success_at
            self._last_batch_hash = old_batch_hash
            self._has_snapshot = old_has_snapshot
            err = safe_exception_message(exc)
            self.last_sync_error = err
            self._update_health_state()
            logger.warning("[NIKKE] 日程数据同步失败，保留原状态: %s", err)
            return False, err

    def freeze_query_context(self, now: datetime | None = None) -> QueryContext:
        """冻结单次查询上下文 (QueryContext)。"""
        current = _aware_utc(now) if now else datetime.now(timezone.utc)
        self._update_health_state()

        used_sources = set()
        for ev in self._events.values():
            used_sources.update(ev.sources)
        if not used_sources:
            source_display = "LOCAL SNAPSHOT"
        else:
            source_display = " + ".join(sorted(s.upper() for s in used_sources))

        return QueryContext(
            now=current,
            snapshot_version=self._snapshot_version,
            events=tuple(self._events.values()),
            source_health=dict(self._source_health),
            freshness=self.freshness,
            coverage=self.coverage,
            health_display=compute_health_badge(self.freshness, self.coverage),
            source_display=source_display,
        )

    def get_current(self) -> list[CanonicalEvent]:
        return list(self._events.values())

    def list_window(self, days: int = 14, now: datetime | None = None) -> list[CalendarActivity]:
        """查询在指定 horizon 范围内的活动。"""
        ctx = self.freeze_query_context(now)
        horizon = timedelta(days=days)

        results: list[CalendarActivity] = []
        for ev in ctx.events:
            status = resolve_event_status(ev, ctx.now)
            if status == EventStatus.ACTIVE.value:
                results.append(ev.to_calendar_activity())
            elif status == EventStatus.UPCOMING.value:
                if ev.start_at and ev.start_at <= ctx.now + horizon:
                    results.append(ev.to_calendar_activity())

        results.sort(key=lambda a: (safe_datetime_key(a.start_at), safe_datetime_key(a.end_at), a.event_id))
        return results

    def list_reminder_deadlines(self, now: datetime | None = None) -> list[CalendarActivity]:
        """返回当前处于 ACTIVE 且具备 EXACT 截止时间的活动用于截止提醒。

        严格门槛：
        1. 状态必须为 ACTIVE；
        2. end_precision 必须为 EXACT (DATE_ONLY 绝不触发小时级提醒)；
        3. end_at 必须在未来；
        4. start_at < end_at。
        """
        ctx = self.freeze_query_context(now)
        valid_acts: list[CalendarActivity] = []
        for ev in ctx.events:
            if not ev.is_valid_interval:
                continue
            if ev.end_precision != TimePrecision.EXACT.value:
                continue
            if not ev.end_at or ev.end_at <= ctx.now:
                continue
            if resolve_event_status(ev, ctx.now) != EventStatus.ACTIVE.value:
                continue
            act = ev.to_calendar_activity()
            object.__setattr__(act, "end_precision", ev.end_precision)
            valid_acts.append(act)

        valid_acts.sort(key=lambda a: (safe_datetime_key(a.end_at), a.event_id))
        return valid_acts

    def group_window(self, days: int = 14, now: datetime | None = None) -> dict[str, list[CalendarActivity]]:
        """向后兼容分组接口。"""
        ctx = self.freeze_query_context(now)
        horizon = timedelta(days=self.normalize_horizon(days))
        soon, active, upcoming = [], [], []

        for ev in ctx.events:
            status = resolve_event_status(ev, ctx.now)
            if status == EventStatus.ACTIVE.value:
                act = ev.to_calendar_activity()
                if ev.end_at and ev.end_precision == TimePrecision.EXACT.value and (ev.end_at - ctx.now <= timedelta(hours=24)):
                    soon.append(act)
                else:
                    active.append(act)
            elif status == EventStatus.UPCOMING.value:
                if ev.start_at and ev.start_at <= ctx.now + horizon:
                    upcoming.append(ev.to_calendar_activity())

        soon.sort(key=lambda a: (safe_datetime_key(a.end_at), a.event_id))
        active.sort(key=lambda a: (safe_datetime_key(a.end_at), a.event_id))
        upcoming.sort(key=lambda a: (safe_datetime_key(a.start_at), a.event_id))
        return {"ending_soon": soon, "active": active, "upcoming": upcoming}

    def format_schedule_text(
        self,
        days: int = 14,
        now: datetime | None = None,
        fallback_error: str = "",
    ) -> str:
        """基于同一 QueryContext 的统一文本 Fallback。"""
        ctx = self.freeze_query_context(now)
        if not self._has_snapshot:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方日程，请稍候。"

        active_events: list[CanonicalEvent] = []
        upcoming_events: list[CanonicalEvent] = []
        horizon = timedelta(days=self.normalize_horizon(days))

        for ev in ctx.events:
            status = resolve_event_status(ev, ctx.now)
            if status == EventStatus.ACTIVE.value:
                active_events.append(ev)
            elif status == EventStatus.UPCOMING.value:
                if ev.start_at and ev.start_at <= ctx.now + horizon:
                    upcoming_events.append(ev)

        active_sorted = sort_active_events(active_events, ctx.now)
        upcoming_events.sort(key=lambda e: (e.start_at or datetime.max.replace(tzinfo=timezone.utc), e.identity_key))

        lines: list[str] = [f"【NIKKE 近期日程 · 未来 {days} 天】"]
        if self.content_updated_at:
            try:
                updated_dt = self.content_updated_at.astimezone(CST)
                lines.append(f"（{ctx.health_display} · 数据源: {ctx.source_display} · 更新: {updated_dt.strftime('%m-%d %H:%M')}）")
            except Exception:
                pass

        error_to_show = fallback_error or self.last_sync_error
        if error_to_show:
            lines.append(f"⚠️ 日程数据同步失败：{error_to_show}，以下为本地缓存。")

        groups = self.group_window(days, ctx.now)
        soon = groups["ending_soon"]
        active = groups["active"]
        upcoming = groups["upcoming"]

        if not soon and not active and not upcoming:
            lines.append(f"未来 {days} 天暂无已记录活动。")
            return "\n".join(lines).strip()

        def _format_item(act: CalendarActivity) -> str:
            label = CAT_LABELS.get(act.category, "活动")
            start_str = act.start_at.astimezone(CST).strftime("%m/%d %H:%M")
            end_str = act.end_at.astimezone(CST).strftime("%m/%d %H:%M")
            rem = act.remaining_display(ctx.now)
            return f"• [{label}] {act.title}\n  {start_str} → {end_str} · {rem}"

        if soon:
            lines.append("【即将结束】")
            for act in soon:
                lines.append(_format_item(act))

        if active:
            lines.append("【进行中】")
            for act in active:
                lines.append(_format_item(act))

        if upcoming:
            lines.append("【即将开始】")
            for act in upcoming:
                lines.append(_format_item(act))

        return "\n".join(lines).strip()
