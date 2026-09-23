# SPDX-License-Identifier: GPL-3.0-or-later
"""日程身份合并、字段仲裁、覆盖应用与来源健康策略。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Sequence

from .models import CalendarActivity, _aware_utc
from .content_quality import (
    DisplayTier,
    IdentityDecision,
    apply_display_relevance,
    canonical_identity_match,
    category_family,
    get_display_relevance,
    score_identity,
    title_similarity,
)
from .canonical_models import (
    CanonicalEvent,
    Coverage,
    FieldEvidence,
    Freshness,
    ManualOverride,
    ResolvedField,
    SourceHealth,
    SourceRole,
    TimePrecision,
    resolve_field,
)

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
    """旧 API 兼容包装；标题身份统一由 content_quality 计算。"""
    return title_similarity(a, b)


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
    """兼容旧调用点；AMBIGUOUS 永不自动合并。"""
    identity = score_identity(a, b)
    if identity.decision == IdentityDecision.MATCH:
        return True
    return canonical_identity_match(a, b) is not None


_is_same_event = _is_same_identity


def _merge_two_events(
    base: CanonicalEvent,
    incoming: CanonicalEvent,
    identity_match=None,
) -> CanonicalEvent:
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
    identity_reasons = set(getattr(identity_match, "reasons", ()) or ())
    if "canonical_title_exact_meta_reconciled" in identity_reasons:
        base_family = category_family(base.event_type)
        incoming_family = category_family(incoming.event_type)
        if base_family == "meta" and incoming_family != "meta":
            event_type = incoming.event_type
        elif incoming_family == "meta" and base_family != "meta":
            event_type = base.event_type

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

    merged_metadata: dict[str, Any] = {}
    for event in (base, incoming):
        if not isinstance(event.metadata, dict):
            continue
        for key, value in event.metadata.items():
            if key in ("visual_candidates", "image_urls"):
                old_values = merged_metadata.setdefault(key, [])
                if not isinstance(old_values, list):
                    old_values = []
                    merged_metadata[key] = old_values
                if isinstance(value, (list, tuple)):
                    for item in value:
                        if item not in old_values:
                            old_values.append(item)
            elif value not in (None, "", [], {}):
                merged_metadata[key] = value
    merged_metadata.pop("display_relevance", None)

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
        metadata=merged_metadata,
        version=max(base.version, incoming.version),
    )
    return merged

class CalendarMergePolicy:

    @staticmethod
    def _sync_internal_stores(service, events: dict[str, CanonicalEvent]) -> None:
        """同步内部有效事件与 CalendarActivity。"""
        dict.clear(service._activities)
        service._events = dict(events)
        for eid, ev in service._events.items():
            # 旧缓存没有 display_relevance 时在载入/同步阶段补算，绝不删除旧事件。
            apply_display_relevance(ev)
            dict.__setitem__(service._activities, eid, ev.to_calendar_activity())

    @staticmethod
    def _compute_batch_hash(service, events: Sequence[CanonicalEvent]) -> str:
        parts = [e.fingerprint for e in sorted(events, key=lambda x: x.id)]
        return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def reload_overrides(service) -> None:
        """重新载入手动覆盖层并重新应用到 Base 数据集，不消耗网络请求。"""
        service._manual_overrides = service.manual_adapter.load_overrides()
        if service._base_events:
            effective = service._apply_manual_overrides(service._base_events)
            service._sync_internal_stores(effective)
            service._has_snapshot = bool(effective)
            service._update_health_state()

    @staticmethod
    def _apply_manual_overrides(service, base_events: dict[str, CanonicalEvent]) -> dict[str, CanonicalEvent]:
        """应用手动覆盖层：Base Evidence -> Base Resolved -> Manual Override -> Effective Event。

        删除 Override 自动恢复 Base 真实值。
        """
        now = datetime.now(timezone.utc)
        effective: dict[str, CanonicalEvent] = {}
        for eid, ev in base_events.items():
            data = ev.to_dict()
            effective[eid] = CanonicalEvent.from_dict(data)

        for override in service._manual_overrides:
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

    @staticmethod
    def _merge_datasets(service) -> dict[str, CanonicalEvent]:
        """将各源独立的 LKG 数据集聚合并去重仲裁。"""
        for key in (
            "identity_matches",
            "identity_ambiguous",
            "identity_distinct",
            "canonical_title_matches",
            "official_enriched_existing",
            "official_created_new",
        ):
            service.quality_diagnostics[key] = 0
        all_events: list[CanonicalEvent] = []
        for src, events in service._source_datasets.items():
            all_events.extend(events)

        merged_list: list[CanonicalEvent] = []
        for incoming in all_events:
            matched_idx = -1
            ambiguous_seen = False
            for idx, existing in enumerate(merged_list):
                identity = score_identity(existing, incoming)
                canonical_match = None
                if identity.decision != IdentityDecision.MATCH:
                    canonical_match = canonical_identity_match(existing, incoming)
                    if canonical_match is not None:
                        identity = canonical_match
                if identity.decision == IdentityDecision.MATCH:
                    matched_idx = idx
                    service.quality_diagnostics["identity_matches"] = service.quality_diagnostics.get("identity_matches", 0) + 1
                    if canonical_match is not None:
                        service.quality_diagnostics["canonical_title_matches"] = service.quality_diagnostics.get("canonical_title_matches", 0) + 1
                        if isinstance(incoming.metadata, dict):
                            incoming.metadata["identity_match"] = canonical_match.to_dict()
                    if "official" in {str(item).casefold() for item in incoming.sources}:
                        service.quality_diagnostics["official_enriched_existing"] += 1
                    break
                if identity.decision == IdentityDecision.AMBIGUOUS:
                    ambiguous_seen = True

            if matched_idx >= 0:
                merged_list[matched_idx] = _merge_two_events(
                    merged_list[matched_idx], incoming, identity_match=identity
                )
            else:
                counter = "identity_ambiguous" if ambiguous_seen else "identity_distinct"
                service.quality_diagnostics[counter] = service.quality_diagnostics.get(counter, 0) + 1
                if ambiguous_seen and isinstance(incoming.metadata, dict):
                    incoming.metadata["identity_match"] = {
                        "decision": IdentityDecision.AMBIGUOUS.value,
                        "reason": "candidate identity requires human/source evidence",
                    }
                merged_list.append(incoming)
                if not ambiguous_seen and "official" in {str(item).casefold() for item in incoming.sources}:
                    service.quality_diagnostics["official_created_new"] += 1

        base_dict: dict[str, CanonicalEvent] = {}
        for ev in merged_list:
            old = service._events.get(ev.id)
            if old is not None:
                v = old.version if ev.fingerprint == old.fingerprint else old.version + 1
            else:
                v = max(1, ev.version)
            object.__setattr__(ev, "version", v)
            apply_display_relevance(ev)
            base_dict[ev.id] = ev

        service.quality_diagnostics["canonical_total"] = len(base_dict)
        relevance_counts = {DisplayTier.CORE: 0, DisplayTier.SUPPORTING: 0, DisplayTier.META: 0}
        for event in base_dict.values():
            relevance_counts[get_display_relevance(event).tier] += 1
        service.quality_diagnostics["relevance_core"] = relevance_counts[DisplayTier.CORE]
        service.quality_diagnostics["relevance_supporting"] = relevance_counts[DisplayTier.SUPPORTING]
        service.quality_diagnostics["relevance_meta"] = relevance_counts[DisplayTier.META]
        # 本阶段不丢弃 META；selected 表示进入 feed，deprioritized 表示排在核心内容之后。
        service.quality_diagnostics["display_selected"] = len(base_dict)
        service.quality_diagnostics["display_deprioritized"] = relevance_counts[DisplayTier.META]
        service._base_events = base_dict
        return service._apply_manual_overrides(base_dict)

    @staticmethod
    def _update_health_state(service) -> None:
        """评估 Freshness 和 Coverage 两轴。"""
        now = datetime.now(timezone.utc)

        # Coverage: 仅由 required_for_complete 来源决定
        required_adapters = [ad for ad in service.adapters if getattr(ad, "required_for_complete", False)]
        if not required_adapters:
            required_adapters = [ad for ad in service.adapters if getattr(ad, "source_role", None) != SourceRole.LOCAL_OVERRIDE]

        if not service._events and not service._source_datasets:
            service.coverage = Coverage.UNAVAILABLE.value
        else:
            has_required_failure = False
            for ad in required_adapters:
                h = service._source_health.get(ad.source_name)
                if h and h.consecutive_failures > 0:
                    has_required_failure = True
                    break

            if has_required_failure:
                has_usable_lkg = bool(service._events) or any(service._source_datasets.get(ad.source_name) for ad in required_adapters)
                if has_usable_lkg:
                    service.coverage = Coverage.PARTIAL.value
                else:
                    service.coverage = Coverage.UNAVAILABLE.value
            else:
                # 若仅有 Manual 覆盖层而无任何主源/补充源/外部源数据，不得判定为 COMPLETE
                non_manual_sources = [k for k in service._source_datasets.keys() if k not in ("manual", "override", "manual_override")]
                if not non_manual_sources and not any(service._source_health.get(ad.source_name) and service._source_health[ad.source_name].last_success_at for ad in required_adapters):
                    service.coverage = Coverage.PARTIAL.value
                else:
                    service.coverage = Coverage.COMPLETE.value

        # Freshness
        if service.last_success_at is None:
            service.freshness = Freshness.EXPIRED.value
        else:
            delta = (now - service.last_success_at).total_seconds()
            if delta <= service.ttl_seconds:
                service.freshness = Freshness.FRESH.value
            elif delta <= 72 * 3600:
                service.freshness = Freshness.STALE.value
            else:
                service.freshness = Freshness.EXPIRED.value

        # 若所有可贡献新鲜度的主源均失败但存在本地快照，置为 STALE
        active_freshness_adapters = [ad for ad in service.adapters if getattr(ad, "contributes_to_freshness", True)]
        if active_freshness_adapters and all(
            service._source_health.get(ad.source_name) and service._source_health[ad.source_name].consecutive_failures > 0
            for ad in active_freshness_adapters
        ) and (service._events or service._source_datasets):
            service.freshness = Freshness.STALE.value
