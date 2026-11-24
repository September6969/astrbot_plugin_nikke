# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 日程服务装配入口；领域职责由独立协作者模块实现。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence

from .models import CalendarActivity
from .ports import CalendarVisualPort
from .canonical_models import (
    CanonicalEvent,
    Coverage,
    Freshness,
    ManualOverride,
    QueryContext,
    SourceHealth,
    compute_health_badge,
    CST,
)
from .schedule_adapters import (
    BaseScheduleAdapter,
    ManualOverrideScheduleAdapter,
)
from .merge import CalendarMergePolicy, _ActivitiesDict
from .snapshot_repository import CalendarSnapshotRepository
from .snapshot_state import SnapshotState
from dataclasses import asdict
from .refresh import CalendarRefreshCoordinator
from .query import CAT_LABELS, CalendarScheduleQueries


class ScheduleService:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        visual_cache: CalendarVisualPort | None | Literal[False] = None,
        adapters: Sequence[BaseScheduleAdapter] | None = None,
        # 须大于 300s 调度周期，避免正常同步间隔就把数据判为 STALE；连续失败仍转 STALE。
        ttl_seconds: float = 900.0,
        task_factory: Any = None,
    ) -> None:
        """adapters 由组合根注入（生产为 BlaBlaLink 单源）；未注入时只含本地手动覆盖层。"""
        self.merge_policy = CalendarMergePolicy()
        self.snapshot_repository = CalendarSnapshotRepository()
        self.snapshot_state = SnapshotState()
        self.refresh_coordinator = CalendarRefreshCoordinator()
        self.query_service = CalendarScheduleQueries()

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 持久化文件规范
        self.events_path = self.data_dir / "schedule_events.json"
        self.health_path = self.data_dir / "schedule_health.json"
        self.cache_path = self.data_dir / "calendar_cache.json"  # 100% 兼容文件
        self.overrides_path = self.data_dir / "schedule_overrides.json"

        self.ttl_seconds = ttl_seconds

        # 视觉缓存
        if visual_cache is False or visual_cache is None:
            self.visual_cache = None
        else:
            self.visual_cache = visual_cache

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
        self.quality_diagnostics: dict[str, Any] = {
            "canonical_total": 0,
            "relevance_core": 0,
            "relevance_supporting": 0,
            "relevance_meta": 0,
            "display_selected": 0,
            "display_deprioritized": 0,
        }

        self._sync_lock = asyncio.Lock()
        self._refresh_task = None
        self._task_factory = task_factory

        # 手动覆盖层始终加载；远程源由组合根注入（PR-6B 移除 source_mode 与
        # features -> integrations 的惰性导入）。未注入时仅含本地手动覆盖。
        self.manual_adapter = ManualOverrideScheduleAdapter(self.overrides_path)
        self.adapters: list[BaseScheduleAdapter] = (
            list(adapters) if adapters is not None else [self.manual_adapter]
        )
        self._load_cache()
        if adapters is not None:
            # 未装配来源（如已删除的 GameKee/官方公告）的旧快照不参与展示，
            # 也不以旧数据冒充已装配来源成功。
            configured = {adapter.source_name for adapter in self.adapters}
            self._source_datasets = {k: v for k, v in self._source_datasets.items() if k in configured}
            self._source_health = {k: v for k, v in self._source_health.items() if k in configured}
            self._base_events = self._merge_datasets()
            self._sync_internal_stores(self._base_events)
            self._has_snapshot = bool(self._source_datasets)
            self._update_health_state()

    @property
    def data_quality(self) -> str:
        """向后兼容属性：由 Freshness 与 Coverage 计算得到。"""
        return compute_health_badge(self.freshness, self.coverage)

    @data_quality.setter
    def data_quality(self, val: str) -> None:
        pass

    def has_snapshot(self) -> bool:
        return self._has_snapshot

    def has_failed_sources(self) -> bool:
        """是否有数据源处于连续失败中；仅单条记录解析警告（PARTIAL）不计入。"""
        return any(health.consecutive_failures > 0 for health in self._source_health.values())

    @property
    def snapshot_diagnostics(self) -> dict[str, Any]:
        """健康诊断显式区分可用内存和已经发布到磁盘的快照。"""
        return asdict(self.snapshot_state)

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

    def cached_visual_event_ids(self) -> tuple[str, ...]:
        """只列出清单中的本地视觉缓存键，不执行同步或网络请求。"""
        if self.visual_cache is None:
            return ()
        return self.visual_cache.cached_event_ids()

    def _sync_internal_stores(self, events: dict[str, CanonicalEvent]) -> None:
        self.merge_policy._sync_internal_stores(self, events)

    def _compute_batch_hash(self, events: Sequence[CanonicalEvent]) -> str:
        return self.merge_policy._compute_batch_hash(self, events)

    def reload_overrides(self) -> None:
        self.merge_policy.reload_overrides(self)

    def _apply_manual_overrides(self, base_events: dict[str, CanonicalEvent]) -> dict[str, CanonicalEvent]:
        return self.merge_policy._apply_manual_overrides(self, base_events)

    def _merge_datasets(self) -> dict[str, CanonicalEvent]:
        return self.merge_policy._merge_datasets(self)

    def _update_health_state(self) -> None:
        self.merge_policy._update_health_state(self)

    def _load_cache(self) -> None:
        self.snapshot_repository._load_cache(self)

    def _save_cache(self, force_events: bool = False) -> None:
        self.snapshot_repository._save_cache(self, force_events)

    async def refresh_schedule_data(self) -> tuple[bool, str]:
        return await self.refresh_coordinator.refresh_schedule_data(self)

    async def _refresh_schedule_data(self) -> tuple[bool, str]:
        return await self.refresh_coordinator._refresh_schedule_data(self)

    async def sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        return await self.refresh_coordinator.sync_from_source(self, fetcher)

    async def _sync_from_source(self, fetcher: Any = None) -> tuple[bool, str]:
        return await self.refresh_coordinator._sync_from_source(self, fetcher)

    @staticmethod
    def normalize_horizon(value: Any) -> int:
        return CalendarScheduleQueries.normalize_horizon(value)

    def freeze_query_context(self, now: datetime | None = None) -> QueryContext:
        return self.query_service.freeze_query_context(self, now)

    def get_current(self) -> list[CanonicalEvent]:
        return self.query_service.get_current(self)

    def list_window(self, days: int = 14, now: datetime | None = None) -> list[CalendarActivity]:
        return self.query_service.list_window(self, days, now)

    def list_reminder_deadlines(self, now: datetime | None = None) -> list[CalendarActivity]:
        return self.query_service.list_reminder_deadlines(self, now)

    def group_window(
        self, days: int = 14, now: datetime | None = None, *, context: QueryContext | None = None
    ) -> dict[str, list[CalendarActivity]]:
        return self.query_service.group_window(self, days, now, context=context)

    def format_schedule_text(
        self,
        days: int = 14,
        now: datetime | None = None,
        fallback_error: str = "",
        *,
        context: QueryContext | None = None,
    ) -> str:
        return self.query_service.format_schedule_text(
            self, days, now, fallback_error, context=context
        )
