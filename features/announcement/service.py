# SPDX-License-Identifier: GPL-3.0-or-later
"""公告能力的兼容门面与协作者组合根。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .deadlines import CST, DeadlineParser, GameDeadline
from .diagnostics import AnnouncementDiagnostics
from .normalization import AnnouncementNormalizer
from .query import AnnouncementQuery
from .repository import AnnouncementRepository
from .synchronization import AnnouncementSyncCoordinator
from .models import AnnouncementRecord


class AnnouncementService:
    """兼容旧调用面的组合根；业务规则由显式协作者承担。"""

    SUPPORTED_LOCALES = AnnouncementNormalizer.SUPPORTED_LOCALES
    CACHE_LOCALES = AnnouncementNormalizer.CACHE_LOCALES
    NORMAL_MAX_PAGES = AnnouncementSyncCoordinator.NORMAL_MAX_PAGES
    NORMAL_PAGE_SIZE = AnnouncementSyncCoordinator.NORMAL_PAGE_SIZE
    DEEP_MAX_PAGES = AnnouncementSyncCoordinator.DEEP_MAX_PAGES
    DEEP_PAGE_SIZE = AnnouncementSyncCoordinator.DEEP_PAGE_SIZE
    CACHE_RETENTION_DAYS = AnnouncementRepository.CACHE_RETENTION_DAYS
    REVISION_HISTORY_LIMIT = AnnouncementRepository.REVISION_HISTORY_LIMIT
    CATEGORY_ALIASES = AnnouncementNormalizer.CATEGORY_ALIASES
    _COMPAT_STATE = frozenset(
        {
            "_clock",
            "data_dir",
            "_records",
            "_deadlines",
            "_revision_history",
            "_last_changed_at",
            "_delivery_log",
            "_last_update_outcome",
            "last_updated_at",
            "last_sync_report",
            "cache_file",
        }
    )

    def __init__(self, data_dir: Path | None = None, *, clock: Any = None):
        self.repository = AnnouncementRepository(data_dir, clock=clock)
        self.synchronizer = AnnouncementSyncCoordinator(self.repository)
        self.query = AnnouncementQuery(self.repository)
        self.diagnostics = AnnouncementDiagnostics(self.repository)

    def __getattr__(self, name: str):
        if name in self._COMPAT_STATE:
            repository = self.__dict__.get("repository")
            if repository is not None:
                return getattr(repository, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        repository = self.__dict__.get("repository")
        if name in self._COMPAT_STATE and repository is not None:
            setattr(repository, name, value)
            return
        object.__setattr__(self, name, value)

    @staticmethod
    def normalize_locale(value: str | None, *, allow_und: bool = False) -> str:
        return AnnouncementNormalizer.normalize_locale(value, allow_und=allow_und)

    @staticmethod
    def _locale_from_content_id(content_id: str) -> str:
        return AnnouncementNormalizer._locale_from_content_id(content_id)

    @staticmethod
    def _normalize_category(value: str | None) -> str | None:
        return AnnouncementNormalizer._normalize_category(value)

    @staticmethod
    def _normalize_query(value: str | None) -> str | None:
        return AnnouncementNormalizer._normalize_query(value)

    @staticmethod
    def _normalize_version(value: Any, field_name: str) -> int:
        return AnnouncementNormalizer._normalize_version(value, field_name)

    def record_count(self) -> int:
        return self.repository.record_count()

    def _now_utc(self) -> datetime:
        return self.repository._now_utc()

    def _now_timestamp(self) -> str:
        return self.repository._now_timestamp()

    def load_cache(self) -> None:
        return self.repository.load_cache()

    def save_cache(self) -> None:
        return self.repository.save_cache()

    async def sync_from_source(self, fetcher=None, *, locale: str = "en", deep: bool = False) -> tuple[bool, str]:
        return await self.synchronizer.sync_from_source(fetcher, locale=locale, deep=deep)

    @staticmethod
    async def fetch_primary(*, locale: str = "en", deep: bool = False) -> list[AnnouncementRecord]:
        return await AnnouncementSyncCoordinator.fetch_primary(
            locale=locale,
            deep=deep,
            fallback=AnnouncementService.fetch_official,
        )

    @staticmethod
    async def fetch_official() -> list[AnnouncementRecord]:
        return await AnnouncementSyncCoordinator.fetch_official()

    def add_or_update(self, record: AnnouncementRecord, *, persist: bool = True) -> tuple[bool, bool]:
        return self.repository.add_or_update(record, persist=persist)

    @staticmethod
    def _parse_aware_timestamp(value: str) -> datetime | None:
        return AnnouncementRepository._parse_aware_timestamp(value)

    def prune_cache(self, *, now: datetime | None = None, retention_days: int | None = None) -> int:
        return self.repository.prune_cache(now=now, retention_days=retention_days)

    def list_announcements(self, limit: int = 10, *, locale=None, category=None, query=None) -> list[AnnouncementRecord]:
        return self.query.list_announcements(limit, locale=locale, category=category, query=query)

    def format_diagnostic_text(self) -> str:
        return self.diagnostics.format_diagnostic_text()

    def list_active_deadlines(self, now: datetime | None = None) -> list[GameDeadline]:
        return self.query.list_active_deadlines(now)

    def list_deadlines(self, now: datetime | None = None) -> list[GameDeadline]:
        return self.query.list_deadlines(now)

    def should_deliver(self, push_key: str) -> bool:
        return self.repository.should_deliver(push_key)

    def mark_delivered(self, push_key: str) -> None:
        return self.repository.mark_delivered(push_key)

    def format_announcements_text(self, limit: int = 5, fallback_error: str = "", *, locale=None, category=None, query=None) -> str:
        return self.query.format_announcements_text(
            limit,
            fallback_error,
            locale=locale,
            category=category,
            query=query,
        )

    @staticmethod
    def _is_coop_deadline(deadline: GameDeadline) -> bool:
        return AnnouncementQuery._is_coop_deadline(deadline)

    def format_schedule_text(self, now: datetime | None = None, fallback_error: str = "") -> str:
        return self.query.format_schedule_text(now, fallback_error)
