# SPDX-License-Identifier: GPL-3.0-or-later
"""公告与日程的本地只读查询和文本呈现。"""

from __future__ import annotations

from datetime import datetime, timezone

from .deadlines import CST, GameDeadline
from .normalization import AnnouncementNormalizer
from .repository import AnnouncementRepository


class AnnouncementQuery:
    """仅查询注入的本地仓储；不导入来源、HTTP 或应用编排。"""

    CACHE_RETENTION_DAYS = AnnouncementRepository.CACHE_RETENTION_DAYS
    REVISION_HISTORY_LIMIT = AnnouncementRepository.REVISION_HISTORY_LIMIT
    normalize_locale = staticmethod(AnnouncementNormalizer.normalize_locale)
    _normalize_category = staticmethod(AnnouncementNormalizer._normalize_category)
    _normalize_query = staticmethod(AnnouncementNormalizer._normalize_query)

    def __init__(self, repository: AnnouncementRepository):
        self.repository = repository

    def list_announcements(
        self,
        limit: int = 10,
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[AnnouncementRecord]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("公告查询数量超出范围")
        selected_locale = AnnouncementNormalizer.normalize_locale(locale, allow_und=True) if locale else None
        selected_category = AnnouncementNormalizer._normalize_category(category)
        selected_query = AnnouncementNormalizer._normalize_query(query)
        items = list(self.repository._records.values())
        if selected_locale:
            items = [record for record in items if record.locale == selected_locale]
        if selected_category:
            items = [record for record in items if record.category.casefold() == selected_category]
        if selected_query:
            items = [
                record for record in items
                if selected_query in f"{record.title}\n{record.body}".casefold()
            ]
        items.sort(key=lambda r: r.published_at, reverse=True)
        return items[:limit]

    def list_active_deadlines(self, now: datetime | None = None) -> list[GameDeadline]:
        current = now or datetime.now(timezone.utc)
        active = [dl for dl in self.repository._deadlines.values() if dl.is_active(current)]
        active.sort(key=lambda dl: dl.end_at)
        return active

    def list_deadlines(self, now: datetime | None = None) -> list[GameDeadline]:
        """返回所有未结束（ACTIVE 或 UPCOMING）的结构化日程活动。"""
        current = now or datetime.now(timezone.utc)
        deadlines = [dl for dl in self.repository._deadlines.values() if not dl.is_ended(current)]
        deadlines.sort(key=lambda dl: (dl.start_at is None, dl.start_at or dl.end_at, dl.end_at))
        return deadlines

    def format_announcements_text(
        self,
        limit: int = 5,
        fallback_error: str = "",
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> str:
        selected_locale = AnnouncementNormalizer.normalize_locale(locale, allow_und=True) if locale else None
        selected_category = AnnouncementNormalizer._normalize_category(category)
        selected_query = AnnouncementNormalizer._normalize_query(query)
        records = self.list_announcements(
            limit,
            locale=selected_locale,
            category=selected_category,
            query=selected_query,
        )
        if not records:
            if self.repository._records:
                filters = []
                if selected_locale:
                    filters.append(f"语言={selected_locale}")
                if selected_category:
                    filters.append(f"分类={selected_category}")
                if selected_query:
                    filters.append("关键词")
                return f"没有匹配的缓存公告（{'、'.join(filters) or '当前筛选'}）。"
            if fallback_error:
                return f"暂时无法获取官方公告：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方数据，请稍候。"
        lines = ["【NIKKE 官方最新公告】"]
        filters = []
        if selected_locale:
            filters.append(f"语言={selected_locale}")
        if selected_category:
            filters.append(f"分类={selected_category}")
        if selected_query:
            filters.append("关键词匹配")
        if filters:
            lines.append(f"（筛选: {' · '.join(filters)}）")
        if self.repository.last_updated_at:
            lines.append(f"（最近更新时间: {self.repository.last_updated_at}）")
        if fallback_error:
            lines.append(f"⚠️ {fallback_error}")
        category_map = {
            "maintenance": "维护",
            "event": "活动",
            "update": "更新",
            "version_update": "版本",
            "recruit": "招募",
            "union_raid": "突袭",
            "dev_note": "笔记",
            "general": "公告",
        }
        for index, r in enumerate(records, 1):
            tag = category_map.get(r.category, "公告")
            pub = r.published_at[:10] if len(r.published_at) >= 10 else r.published_at
            lines.append(f"{index}. [{tag}] {r.title} ({pub})")
            if r.source_url:
                lines.append(f"   链接: {r.source_url}")
        lines.append("\n发送 /妮姬 日程 可查看进行中活动的结束倒计时。")
        return "\n".join(lines)

    @staticmethod
    def _is_coop_deadline(dl: GameDeadline) -> bool:
        name_lower = dl.name.lower()
        return (
            dl.category == "coop"
            or "协同作战" in dl.name
            or "协同" in dl.name
            or "co-op" in name_lower
            or "coordinated operation" in name_lower
            or "cooperative" in name_lower
        )

    def format_schedule_text(self, now: datetime | None = None, fallback_error: str = "") -> str:
        current = now or datetime.now(timezone.utc)
        if not self.repository._records:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方数据，请稍候。"

        deadlines = self.list_active_deadlines(current)
        lines = ["【NIKKE 近期日程与活动倒计时】"]
        if self.repository.last_updated_at:
            lines.append(f"（最近更新时间: {self.repository.last_updated_at}）")
        if fallback_error:
            lines.append(f"⚠️ {fallback_error}")
        lines.append("【进行中活动】")
        if deadlines:
            for dl in deadlines:
                rem = dl.remaining_display(current)
                start_cst = dl.start_at.astimezone(CST).strftime("%Y-%m-%d %H:%M") if dl.start_at else "见公告详情"
                end_cst = dl.end_at.astimezone(CST).strftime("%Y-%m-%d %H:%M")
                tag = ""
                if self._is_coop_deadline(dl):
                    tag = "[协同] "
                elif dl.category == "raid" or "突袭" in dl.name or "raid" in dl.name.lower():
                    tag = "[突袭] "
                elif dl.category == "recruit" or "招募" in dl.name or "recruit" in dl.name.lower() or "pick up" in dl.name.lower():
                    tag = "[招募] "
                lines.append(f"• {tag}{dl.name}")
                lines.append("  状态: 进行中")
                lines.append(f"  开始时间: {start_cst}")
                lines.append(f"  结束时间: {end_cst}")
                lines.append(f"  剩余时间: {rem}")
        else:
            lines.append("当前暂无进行中的活动。")
        return "\n".join(lines).strip()
