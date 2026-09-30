# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar LKG 快照的迁移读取与原子持久化。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from .models import CalendarActivity, _aware_utc
from .canonical_models import CanonicalEvent, SourceHealth
from .snapshot_state import revision
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.snapshot")

class CalendarSnapshotRepository:

    @staticmethod
    def _load_cache(service) -> None:
        """载入本地数据并支持新旧 schema 平滑自动迁移。"""
        service._manual_overrides = service.manual_adapter.load_overrides()
        service.migrated_from_merged_snapshot = False

        events_loaded = False
        data = {}
        hdata = {}
        if service.events_path.is_file():
            try:
                content = service.events_path.read_text(encoding="utf-8")
                data = json.loads(content)
                schema_version = int(data.get("schema", 1))

                if schema_version >= 4 and "source_datasets" in data:
                    raw_sources = data.get("source_datasets", {})
                    by_source: dict[str, list[CanonicalEvent]] = {}
                    for src, raw_list in raw_sources.items():
                        by_source[src] = [CanonicalEvent.from_dict(item) for item in raw_list]
                    service._source_datasets = by_source
                    service.migrated_from_merged_snapshot = False
                else:
                    raw_events = data.get("events", []) or data.get("merged_snapshot", [])
                    by_source = {}
                    for item in raw_events:
                        ev = CanonicalEvent.from_dict(item)
                        src = ev.primary_source or (ev.sources[0] if ev.sources else "gamekee")
                        by_source.setdefault(src, []).append(ev)
                    service._source_datasets = by_source
                    service.migrated_from_merged_snapshot = True

                service._last_batch_hash = data.get("fingerprint", "")
                service.content_updated_at = _aware_utc(data["content_updated_at"]) if data.get("content_updated_at") else None
                events_loaded = True
            except Exception as exc:
                logger.warning("[NIKKE] 读取 schedule_events.json 失败: %s", safe_exception_message(exc))

        if service.health_path.is_file():
            try:
                hdata = json.loads(service.health_path.read_text(encoding="utf-8"))
                service.last_success_at = _aware_utc(hdata["last_success_at"]) if hdata.get("last_success_at") else None
                service.last_attempt_at = _aware_utc(hdata["last_attempt_at"]) if hdata.get("last_attempt_at") else None
                raw_health = hdata.get("source_health", {})
                service._source_health = {
                    src: SourceHealth.from_dict(info) for src, info in raw_health.items() if isinstance(info, dict)
                }
            except Exception as exc:
                logger.warning("[NIKKE] 读取 schedule_health.json 失败: %s", safe_exception_message(exc))

        # 若新文件不存在，尝试从旧 calendar_cache.json 迁移
        if not events_loaded and service.cache_path.is_file():
            try:
                content = service.cache_path.read_text(encoding="utf-8")
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

                service._source_datasets = by_source
                service.migrated_from_merged_snapshot = True
                up_str = data.get("updated_at")
                if up_str:
                    up_dt = _aware_utc(up_str)
                    service.content_updated_at = up_dt
                    service.last_success_at = up_dt
                    service.last_attempt_at = up_dt
                events_loaded = True
                logger.info("[NIKKE] 成功从旧 calendar_cache.json 迁移载入 %d 条活动", sum(len(v) for v in by_source.values()))
            except Exception as exc:
                logger.warning("[NIKKE] 读取旧快照失败: %s", safe_exception_message(exc))

        if events_loaded:
            effective = service._merge_datasets()
            service._sync_internal_stores(effective)
            service._has_snapshot = bool(effective)
            service.last_updated_at = service.content_updated_at.isoformat() if service.content_updated_at else None
            service._update_health_state()
            state = service.snapshot_state
            state.activate(service)
            generation = data.get("generation", "")
            if data.get("schema") == 5 and generation and generation == hdata.get("snapshot_generation"):
                state.persisted_display_revision = data.get("display_revision", "")
                state.persisted_source_revision = data.get("source_revision", "")
                state.generation = generation
                state.dirty = (
                    state.active_display_revision != state.persisted_display_revision
                    or state.active_source_revision != state.persisted_source_revision
                )
                if state.dirty:
                    state.durability_error = "snapshot revision mismatch"
            elif data.get("schema") == 5:
                # events 是数据权威；不把另一代 health 的新鲜度套到该快照。
                state.durability_error = "snapshot generation mismatch; events authoritative, health discarded"
                state.dirty = True
                service.last_success_at = None
                service.last_attempt_at = None
                service._source_health = {}
                service.last_sync_error = state.durability_error
                service._update_health_state()
        else:
            service._has_snapshot = False
            service._sync_internal_stores({})
            service._update_health_state()

    @staticmethod
    def _save_cache(service, force_events: bool = False) -> None:
        """先发布完整 events，再发布同代 health，兼容缓存最后写。"""
        state = service.snapshot_state
        state.activate(service)
        write_events = force_events or state.dirty or not service.events_path.is_file()
        generation = revision([state.active_display_revision, state.active_source_revision]) if write_events else state.generation
        if write_events:
            events_payload = {
                "schema": 5,
                "generation": generation,
                "display_revision": state.active_display_revision,
                "source_revision": state.active_source_revision,
                "content_updated_at": service.content_updated_at.isoformat() if service.content_updated_at else None,
                "fingerprint": service._last_batch_hash,
                "source_datasets": {
                    src: [ev.to_dict() for ev in ev_list]
                    for src, ev_list in service._source_datasets.items()
                },
                "merged_snapshot": [ev.to_dict() for ev in service._events.values()],
                "events": [ev.to_dict() for ev in service._events.values()],
            }
            CalendarSnapshotRepository._atomic_write(service.events_path, events_payload)

        health_payload = {
            "snapshot_generation": generation,
            "dirty": False,
            "durability_error": None,
            "last_success_at": service.last_success_at.isoformat() if service.last_success_at else None,
            "last_attempt_at": service.last_attempt_at.isoformat() if service.last_attempt_at else None,
            "content_updated_at": service.content_updated_at.isoformat() if service.content_updated_at else None,
            "freshness": service.freshness,
            "coverage": service.coverage,
            "source_health": {src: h.to_dict() for src, h in service._source_health.items()},
        }
        CalendarSnapshotRepository._atomic_write(service.health_path, health_payload)

        # 2. schedule_events.json 与 calendar_cache.json
        if write_events:
            legacy_payload = {
                "schema": 2,
                "updated_at": service.last_updated_at or datetime.now(timezone.utc).isoformat(),
                "activities": [ev.to_dict() for ev in service._events.values()],
            }
            CalendarSnapshotRepository._atomic_write(service.cache_path, legacy_payload)
        state.acknowledge(generation)

    @staticmethod
    def _atomic_write(path, payload) -> None:
        temporary = path.with_suffix(".json.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
