# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar LKG 快照的迁移读取与原子持久化。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from .models import CalendarActivity, _aware_utc
from .canonical_models import CanonicalEvent, SourceHealth
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.snapshot")

class CalendarSnapshotRepository:

    @staticmethod
    def _load_cache(service) -> None:
        """载入本地数据并支持新旧 schema 平滑自动迁移。"""
        service._manual_overrides = service.manual_adapter.load_overrides()
        service.migrated_from_merged_snapshot = False

        events_loaded = False
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
        else:
            service._has_snapshot = False
            service._sync_internal_stores({})
            service._update_health_state()

    @staticmethod
    def _save_cache(service, force_events: bool = False) -> None:
        """原子落盘：大事件数据仅在内容变更时写盘，健康元数据独立写盘。"""
        # 1. schedule_health.json
        health_payload = {
            "last_success_at": service.last_success_at.isoformat() if service.last_success_at else None,
            "last_attempt_at": service.last_attempt_at.isoformat() if service.last_attempt_at else None,
            "content_updated_at": service.content_updated_at.isoformat() if service.content_updated_at else None,
            "freshness": service.freshness,
            "coverage": service.coverage,
            "source_health": {src: h.to_dict() for src, h in service._source_health.items()},
        }
        tmp_health = service.health_path.with_suffix(".json.tmp")
        with open(tmp_health, "w", encoding="utf-8") as f:
            f.write(json.dumps(health_payload, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        tmp_health.replace(service.health_path)

        # 2. schedule_events.json 与 calendar_cache.json
        if force_events or not service.events_path.is_file():
            events_payload = {
                "schema": 4,
                "content_updated_at": service.content_updated_at.isoformat() if service.content_updated_at else datetime.now(timezone.utc).isoformat(),
                "fingerprint": service._last_batch_hash,
                "source_datasets": {
                    src: [ev.to_dict() for ev in ev_list]
                    for src, ev_list in service._source_datasets.items()
                },
                "merged_snapshot": [ev.to_dict() for ev in service._events.values()],
                "events": [ev.to_dict() for ev in service._events.values()],
            }
            tmp_events = service.events_path.with_suffix(".json.tmp")
            with open(tmp_events, "w", encoding="utf-8") as f:
                f.write(json.dumps(events_payload, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
            tmp_events.replace(service.events_path)

            legacy_payload = {
                "schema": 2,
                "updated_at": service.last_updated_at or datetime.now(timezone.utc).isoformat(),
                "activities": [ev.to_dict() for ev in service._events.values()],
            }
            tmp_cache = service.cache_path.with_suffix(".json.tmp")
            with open(tmp_cache, "w", encoding="utf-8") as f:
                f.write(json.dumps(legacy_payload, ensure_ascii=False, indent=2))
                f.flush()
                os.fsync(f.fileno())
            tmp_cache.replace(service.cache_path)
