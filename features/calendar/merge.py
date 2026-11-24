# SPDX-License-Identifier: GPL-3.0-or-later
"""日程按 ID 聚合、覆盖应用与来源健康策略。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from .models import CalendarActivity, _aware_utc
from .snapshot_state import revision
from .content_quality import (
    DisplayTier,
    apply_display_relevance,
    get_display_relevance,
)
from .canonical_models import (
    CanonicalEvent,
    Coverage,
    Freshness,
    SourceRole,
    TimePrecision,
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
        fields = {
            "id", "title", "event_type", "start_at", "end_at", "start_precision",
            "end_precision", "server_scope", "cycle_id", "banner_url", "detail_url",
            "has_started_evidence", "is_cancelled", "is_valid_interval", "metadata",
        }
        return revision([
            {key: value for key, value in event.to_dict().items() if key in fields}
            for event in sorted(events, key=lambda item: item.id)
        ])

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
        """将各源独立的 LKG 数据集按事件 ID 单遍聚合。

        生产只装配 BlaBlaLink 单一远程源（ID 在源内唯一），因此不再做跨源模糊
        身份去重与字段仲裁（PR-6B G5-calendar-a3，原实现为 O(N^2) 空转）。来源按
        名称排序、源内按 ID 排序后依次写入；若未来装配多个源且 ID 冲突，后写入
        的来源覆盖先写入的来源，需要时应另行设计合并策略。
        """
        merged_list: list[CanonicalEvent] = []
        for src, events in sorted(service._source_datasets.items()):
            # 聚合的版本和展示诊断不得回写到来源 LKG。
            merged_list.extend(
                CanonicalEvent.from_dict(event.to_dict())
                for event in sorted(events, key=lambda item: item.id)
            )

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
                if h is None or h.consecutive_failures > 0 or h.completeness != "COMPLETE":
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

        # 若所有可贡献新鲜度的主源均失败但存在本地快照，FRESH 降为 STALE；
        # 已 EXPIRED 的快照不得因“仍有本地数据”被反向提升为 STALE。
        active_freshness_adapters = [ad for ad in service.adapters if getattr(ad, "contributes_to_freshness", True)]
        if service.freshness == Freshness.FRESH.value and active_freshness_adapters and all(
            service._source_health.get(ad.source_name) and service._source_health[ad.source_name].consecutive_failures > 0
            for ad in active_freshness_adapters
        ) and (service._events or service._source_datasets):
            service.freshness = Freshness.STALE.value
