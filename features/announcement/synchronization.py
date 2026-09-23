# SPDX-License-Identifier: GPL-3.0-or-later
"""公告公开只读同步编排与来源抓取。"""

from __future__ import annotations

from collections import Counter
import logging
from typing import Any

from astrbot_plugin_nikke.core.privacy import safe_exception_message

from .deadlines import CST
from .models import AnnouncementRecord
from .normalization import AnnouncementNormalizer
from .ports import (
    AnnouncementSource,
    AnnouncementSourceFactory,
    OfficialAnnouncementFetcher,
)
from .repository import AnnouncementRepository

logger = logging.getLogger("nikke.announcements")


class AnnouncementSyncCoordinator:
    """协调公开来源、仓储更新及受控失败回退；从不触发投递。"""

    NORMAL_MAX_PAGES = 2
    NORMAL_PAGE_SIZE = 5
    DEEP_MAX_PAGES = 5
    DEEP_PAGE_SIZE = 20
    normalize_locale = staticmethod(AnnouncementNormalizer.normalize_locale)

    def __init__(
        self,
        repository: AnnouncementRepository,
        *,
        source_factory: AnnouncementSourceFactory | None = None,
        official_fetcher: OfficialAnnouncementFetcher | None = None,
    ):
        self.repository = repository
        self._source_factory = source_factory
        self._official_fetcher = official_fetcher

    async def fetch_primary(self, *, locale: str = "en", deep: bool = False) -> list[AnnouncementRecord]:
        try:
            selected_locale = AnnouncementNormalizer.normalize_locale(locale)
            source = self._create_source(
                selected_locale,
                max_pages=(AnnouncementSyncCoordinator.DEEP_MAX_PAGES if deep else AnnouncementSyncCoordinator.NORMAL_MAX_PAGES),
                page_size=(AnnouncementSyncCoordinator.DEEP_PAGE_SIZE if deep else AnnouncementSyncCoordinator.NORMAL_PAGE_SIZE),
            )
            return await source.fetch()
        except Exception:
            if deep:
                # 深度范围必须由主 InformationFeeds 源确认，不能用旧回退源冒充完成。
                raise
            return await self._fetch_official()

    def _create_source(self, locale: str, *, max_pages: int, page_size: int) -> AnnouncementSource:
        if self._source_factory is None:
            raise RuntimeError("公告来源尚未由组合根装配")
        return self._source_factory(locale, max_pages=max_pages, page_size=page_size)

    async def _fetch_official(self) -> list[AnnouncementRecord]:
        if self._official_fetcher is None:
            raise RuntimeError("官方公告回退来源尚未由组合根装配")
        return await self._official_fetcher()

    async def sync_from_source(
        self,
        fetcher: Any = None,
        *,
        locale: str = "en",
        deep: bool = False,
    ) -> tuple[bool, str]:
        """同步公开数据；深度扫描受限且不会触发任何投递。"""
        selected_locale = AnnouncementNormalizer.normalize_locale(locale)
        try:
            source_name = "injected"
            scan = None
            if fetcher is not None:
                records = await fetcher()
            else:
                source = self._create_source(
                    selected_locale,
                    max_pages=self.DEEP_MAX_PAGES if deep else self.NORMAL_MAX_PAGES,
                    page_size=self.DEEP_PAGE_SIZE if deep else self.NORMAL_PAGE_SIZE,
                )
                try:
                    records = await source.fetch()
                    source_name = "informationfeeds"
                    scan = source.last_scan
                except Exception:
                    # 深度重扫必须能够确认完整的 InformationFeeds 扫描范围；
                    # 不以旧 MVP 回退结果冒充已完成的深度扫描。
                    if deep:
                        raise
                    records = await self._fetch_official()
                    source_name = "blablalink-fallback"
                    scan = {"fallback": True, "requested_pages": self.NORMAL_MAX_PAGES, "page_size": self.NORMAL_PAGE_SIZE}
            if not isinstance(records, list):
                raise ValueError("公告来源未返回列表")

            counts: Counter[str] = Counter()
            for r in records:
                if not isinstance(r, AnnouncementRecord):
                    counts["invalid"] += 1
                    continue
                try:
                    is_new, is_updated = self.repository.add_or_update(r, persist=False)
                except ValueError:
                    counts["invalid"] += 1
                    continue
                if is_new:
                    counts["new"] += 1
                elif is_updated:
                    counts["updated"] += 1
                else:
                    counts[self.repository._last_update_outcome] += 1
            self.repository.prune_cache(now=self.repository._now_utc())
            self.repository.last_updated_at = self.repository._now_utc().astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
            self.repository.last_sync_report = {
                "success": True,
                "source": source_name,
                "locale": selected_locale,
                "deep": bool(deep),
                "received": len(records),
                "new": counts["new"],
                "updated": counts["updated"],
                "unchanged": counts["unchanged"],
                "stale": counts["stale"],
                "invalid": counts["invalid"],
                "scan": scan,
                "source_order": "unknown",
            }
            self.repository.save_cache()
            scope = "深度重扫" if deep else "常规同步"
            return True, f"{scope}成功：收到 {len(records)} 条，新增 {counts['new']} 条，更新 {counts['updated']} 条。"
        except Exception as exc:
            # 失败时覆盖旧的成功范围，避免诊断把过期报告冒充最近同步结果。
            self.repository.last_sync_report = {
                "success": False,
                "source": "failure",
                "locale": selected_locale,
                "deep": bool(deep),
                "error_type": type(exc).__name__,
                "source_order": "unknown",
            }
            self.repository.save_cache()
            safe_message = safe_exception_message(exc)
            logger.warning("官方公告同步失败，降级读取本地缓存: %s", safe_message)
            return False, f"官方数据同步失败（{safe_message}），已降级读取本地缓存"
