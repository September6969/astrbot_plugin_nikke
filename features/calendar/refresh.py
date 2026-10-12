# SPDX-License-Identifier: GPL-3.0-or-later
"""多来源刷新协调；失败保持各来源 Last Known Good。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from .models import CalendarActivity
from .content_quality import get_display_relevance
from .canonical_models import CanonicalEvent, FetchOutcome, ResponseMode, SourceHealth
from .schedule_adapters import FetchResult
from .merge import _ActivitiesDict
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.refresh")

class CalendarRefreshCoordinator:

    @staticmethod
    async def refresh_schedule_data(service) -> tuple[bool, str]:
        """统一多源刷新流程 (Refresh Path)。"""
        if service._task_factory is None:
            async with service._sync_lock:
                return await service._refresh_schedule_data()
        task = service._refresh_task
        if task is None or task.done():
            async def run():
                async with service._sync_lock:
                    return await service._refresh_schedule_data()
            task = service._task_factory(run())
            if task is None:
                return False, "服务正在关闭"
            service._refresh_task = task
            # 即使所有等待者离开，也消费后台异常，任务由运行时统一回收。
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)

    @staticmethod
    async def _refresh_schedule_data(service) -> tuple[bool, str]:
        now_utc = datetime.now(timezone.utc)
        service.last_attempt_at = now_utc
        service._manual_overrides = service.manual_adapter.load_overrides()

        source_errors: list[str] = []
        any_success = False

        for adapter in service.adapters:
            src = adapter.source_name
            health = service._source_health.setdefault(src, SourceHealth(source=src))
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

            if src == "official":
                report = getattr(getattr(adapter, "announcement_service", None), "last_sync_report", None)
                if isinstance(report, dict) and report.get("success") is False:
                    res = FetchResult(FetchOutcome.REQUEST_FAILED, source=src,
                                      error_message="官方公告更新失败，保留旧日程")
                elif isinstance(report, dict) and report.get("invalid", 0):
                    res.completeness = "PARTIAL"
            health.last_outcome = res.outcome.value
            observed_at = res.observed_at
            if src == "official":
                origin = getattr(getattr(adapter, "announcement_service", None), "last_updated_at", None)
                try:
                    from .models import _aware_utc
                    if isinstance(origin, str):
                        # 公告仓库历史格式明确采用北京时间，按已有格式恢复时区。
                        parsed = datetime.fromisoformat(origin)
                        if parsed.tzinfo is None:
                            from .canonical_models import CST
                            parsed = parsed.replace(tzinfo=CST)
                        observed_at = _aware_utc(parsed)
                    else:
                        observed_at = _aware_utc(origin) if origin else None
                except (ValueError, TypeError):
                    observed_at = None

            if src == "gamekee":
                scan = res.diagnostics or getattr(adapter, "last_scan", {}) or {}
                for key in ("gamekee_rows", "gamekee_valid", "gamekee_malformed", "gamekee_duplicates"):
                    scan_key = key.removeprefix("gamekee_")
                    service.quality_diagnostics[key] = int(scan.get(key, scan.get(scan_key, 0)) or 0)
                if "with_visual" in scan:
                    service.quality_diagnostics["with_visual"] = int(scan.get("with_visual", 0) or 0)
            elif src == "official":
                for key in (
                    "official_deadlines_seen",
                    "official_deadlines_filtered",
                    "official_deadlines_parsed",
                ):
                    if key in res.diagnostics:
                        service.quality_diagnostics[key] = int(res.diagnostics.get(key, 0) or 0)

            contributes = getattr(adapter, "contributes_to_freshness", True)

            if res.outcome == FetchOutcome.SUCCESS_DATA:
                complete = res.completeness == "COMPLETE"
                if (adapter.response_mode == ResponseMode.COMPLETE_SNAPSHOT or src == "manual") and complete:
                    service._source_datasets[src] = res.events
                else:
                    retained = {event.id: CanonicalEvent.from_dict(event.to_dict())
                                for event in service._source_datasets.get(src, [])}
                    # 仅替换本次成功重新解析的公告，其他增量来源记录继续保留。
                    if src == "official":
                        patterns = [re.compile(rf"official:{re.escape(str(cid))}_(?:[0-9]+|range_[a-f0-9]{{20}})")
                                    for cid in res.diagnostics.get("reparsed_content_ids", []) if cid]
                        if patterns:
                            retained = {key: event for key, event in retained.items()
                                        if not any(pattern.fullmatch(key) for pattern in patterns)}
                    if not complete:
                        for event in retained.values():
                            event.metadata["source_stale"] = True
                    for event in res.events:
                        retained[event.id] = event
                    service._source_datasets[src] = list(retained.values())
                health.completeness = res.completeness
                health.last_success_at = observed_at
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            elif res.outcome == FetchOutcome.SUCCESS_EMPTY:
                if (adapter.response_mode == ResponseMode.COMPLETE_SNAPSHOT or src == "manual") and res.completeness == "COMPLETE":
                    service._source_datasets[src] = []
                elif res.completeness != "COMPLETE":
                    retained = [CanonicalEvent.from_dict(event.to_dict()) for event in service._source_datasets.get(src, [])]
                    for event in retained:
                        event.metadata["source_stale"] = True
                    if src in service._source_datasets:
                        service._source_datasets[src] = retained
                health.completeness = res.completeness
                health.last_success_at = observed_at
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            elif res.outcome == FetchOutcome.NOT_MODIFIED:
                health.last_success_at = observed_at
                health.consecutive_failures = 0
                health.last_error_type = ""
                if contributes:
                    any_success = True
            else:
                health.consecutive_failures += 1
                health.last_error_type = res.error_message or res.outcome.value
                source_errors.append(f"{src}: {health.last_error_type}")
                logger.warning("[NIKKE] 数据源 %s 同步失败，保留历史 LKG: %s", src, health.last_error_type)

            if res.outcome in (FetchOutcome.SUCCESS_DATA, FetchOutcome.SUCCESS_EMPTY) and res.completeness != "COMPLETE":
                source_errors.append(f"{src}: 数据范围不完整，保留未验证的旧记录")

        if any_success:
            service.last_success_at = now_utc

        all_not_modified = bool(service.adapters) and all(
            service._source_health.get(ad.source_name) and service._source_health[ad.source_name].last_outcome == FetchOutcome.NOT_MODIFIED.value
            for ad in service.adapters
        )

        merged_effective = service._merge_datasets()
        new_batch_hash = service._compute_batch_hash(list(merged_effective.values()))
        content_changed = (new_batch_hash != service._last_batch_hash) and not all_not_modified

        if content_changed:
            service._last_batch_hash = new_batch_hash
            service.content_updated_at = now_utc
            service.last_updated_at = now_utc.isoformat()
            service._snapshot_version = f"v{int(time.time())}"

        service._sync_internal_stores(merged_effective)
        service.snapshot_state.activate(service)
        service._has_snapshot = bool(merged_effective) or any_success or service._has_snapshot
        service.last_sync_error = "; ".join(source_errors) if source_errors else ""
        service._update_health_state()

        summary_keys = (
            "gamekee_rows", "gamekee_valid", "gamekee_malformed", "gamekee_duplicates",
            "with_visual", "canonical_total", "identity_matches", "canonical_title_matches", "identity_ambiguous",
            "identity_distinct", "official_deadlines_seen", "official_deadlines_filtered",
            "official_deadlines_parsed", "official_enriched_existing", "official_created_new",
            "relevance_core", "relevance_supporting", "relevance_meta", "display_selected",
            "display_deprioritized",
        )
        logger.info(
            "[NIKKE] 日程内容质量摘要: %s",
            json.dumps({key: service.quality_diagnostics.get(key, 0) for key in summary_keys}, ensure_ascii=False, sort_keys=True),
        )
        for event in merged_effective.values():
            relevance = get_display_relevance(event)
            logger.debug(
                "[NIKKE] 日程展示相关性 id=%s tier=%s score=%s reasons=%s",
                event.id,
                relevance.tier.value,
                relevance.score,
                ",".join(relevance.reasons),
            )

        try:
            service._save_cache(force_events=content_changed)
        except Exception as exc:
            error = safe_exception_message(exc)
            service.snapshot_state.dirty = True
            service.snapshot_state.durability_error = error
            service.last_sync_error = f"persistence failed: {error}"
            logger.error("[NIKKE] 日程持久化失败: %s", error)
            return False, service.last_sync_error

        if not any_success:
            err = "; ".join(source_errors) or "全部数据源抓取失败"
            service.last_sync_error = err
            return False, err

        if service.visual_cache is not None:
            try:
                service.last_visual_sync = await service.visual_cache.sync(list(service._activities.values()))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[NIKKE] 活动宣传图缓存失败，保留结构化日程: %s", safe_exception_message(exc))

        status_msg = "ok" if not source_errors else f"partial: {service.last_sync_error}"
        return True, status_msg

    @staticmethod
    async def sync_from_source(service, fetcher: Any = None) -> tuple[bool, str]:
        """兼容既有 sync_from_source 接口，支持事物级失败回滚。"""
        async with service._sync_lock:
            return await service._sync_from_source(fetcher)

    @staticmethod
    async def _sync_from_source(service, fetcher: Any = None) -> tuple[bool, str]:
        if fetcher is None:
            return await service._refresh_schedule_data()

        # 记录旧状态以备保存异常时回滚
        old_activities = dict(service._activities)
        old_events = dict(service._events)
        old_base = dict(service._base_events)
        old_sources = {k: list(v) for k, v in service._source_datasets.items()}
        old_timestamp = service.last_updated_at
        old_content_updated_at = service.content_updated_at
        old_last_success_at = service.last_success_at
        old_batch_hash = service._last_batch_hash
        old_has_snapshot = service._has_snapshot

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
            service._source_datasets[src] = canonical_list
            service.last_success_at = now
            service.content_updated_at = now
            service.last_updated_at = now.isoformat()

            effective = service._merge_datasets()
            service._sync_internal_stores(effective)
            service._last_batch_hash = service._compute_batch_hash(list(effective.values()))
            service._has_snapshot = bool(effective)
            service.last_sync_error = ""
            service._update_health_state()
            service.last_sync_report = getattr(fetcher, "last_scan", None)

            service.snapshot_state.activate(service)
            try:
                service._save_cache(force_events=True)
            except Exception as exc:
                # 新快照已经激活，落盘失败不能回滚可用内存。
                error = safe_exception_message(exc)
                service.snapshot_state.dirty = True
                service.snapshot_state.durability_error = error
                service.last_sync_error = f"persistence failed: {error}"
                return False, service.last_sync_error

            if service.visual_cache is not None:
                try:
                    service.last_visual_sync = await service.visual_cache.sync(list(service._activities.values()))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("[NIKKE] 活动宣传图缓存失败，保留结构化日程: %s", safe_exception_message(exc))

            return True, "ok"
        except Exception as exc:
            # 事务性回滚
            service._activities = _ActivitiesDict(service, old_activities)
            service._events = old_events
            service._base_events = old_base
            service._source_datasets = old_sources
            service.last_updated_at = old_timestamp
            service.content_updated_at = old_content_updated_at
            service.last_success_at = old_last_success_at
            service._last_batch_hash = old_batch_hash
            service._has_snapshot = old_has_snapshot
            err = safe_exception_message(exc)
            service.last_sync_error = err
            service._update_health_state()
            logger.warning("[NIKKE] 日程数据同步失败，保留原状态: %s", err)
            return False, err
