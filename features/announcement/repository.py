# SPDX-License-Identifier: GPL-3.0-or-later
"""公告记录、版本历史、LKG 时间及本地原子缓存仓储。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from astrbot_plugin_nikke.core.privacy import safe_exception_message

from .deadlines import CST, DeadlineParser, GameDeadline
from .models import AnnouncementRecord
from .normalization import AnnouncementNormalizer, AnnouncementVersioning

logger = logging.getLogger("nikke.announcements")


class AnnouncementRepository:
    """持有公告缓存及修订/LKG 状态，不负责网络访问或消息投递。"""

    CACHE_RETENTION_DAYS = 90
    REVISION_HISTORY_LIMIT = 8
    CACHE_LOCALES = AnnouncementNormalizer.CACHE_LOCALES
    normalize_locale = staticmethod(AnnouncementNormalizer.normalize_locale)
    _locale_from_content_id = staticmethod(AnnouncementNormalizer._locale_from_content_id)
    _normalize_version = staticmethod(AnnouncementNormalizer._normalize_version)

    def __init__(self, data_dir: Path | None = None, *, clock: Any = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.data_dir = Path(data_dir) if data_dir else None
        self._records: dict[str, AnnouncementRecord] = {}
        self._deadlines: dict[str, GameDeadline] = {}
        self._revision_history: dict[str, list[str]] = {}
        self._last_changed_at: dict[str, str] = {}
        self._delivery_log: set[str] = set()
        self._last_update_outcome = "unchanged"
        self.last_updated_at: str | None = None
        self.last_sync_report: dict[str, Any] | None = None
        self.cache_file = (self.data_dir / "announcements_cache.json") if self.data_dir else None
        if self.cache_file and self.cache_file.is_file():
            self.load_cache()

    def _now_utc(self) -> datetime:
        """返回带时区的 UTC 当前时间，便于缓存生命周期保持可比较。"""
        current = self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise ValueError("公告时钟必须返回带时区的 datetime")
        return current.astimezone(timezone.utc)

    def _now_timestamp(self) -> str:
        return self._now_utc().isoformat()

    def record_count(self) -> int:
        return len(self._records)

    def load_cache(self) -> None:
        """从本地磁盘缓存加载公告与日程数据。"""
        if not self.cache_file or not self.cache_file.is_file():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.last_updated_at = data.get("last_updated_at")
            report = data.get("last_sync_report")
            self.last_sync_report = report if isinstance(report, dict) else None
            histories = data.get("revision_history")
            if isinstance(histories, dict):
                for content_id, fingerprints in histories.items():
                    if not isinstance(content_id, str) or not isinstance(fingerprints, list):
                        continue
                    self._revision_history[content_id] = [
                        value for value in fingerprints[-self.REVISION_HISTORY_LIMIT:]
                        if isinstance(value, str) and value
                    ]
            migration_timestamp = self._now_timestamp()
            migrated_legacy_timestamp = False
            for item in data.get("records", []):
                if not isinstance(item, dict):
                    continue
                try:
                    content_id = str(item.get("content_id") or "").strip()
                    title = item.get("title")
                    body = item.get("body")
                    published_at = item.get("published_at")
                    if not content_id or not isinstance(title, str) or not isinstance(body, str) or not isinstance(published_at, str):
                        raise ValueError("缺少公告必要字段")
                    locale = str(item.get("locale") or self._locale_from_content_id(content_id))
                    if locale not in self.CACHE_LOCALES:
                        locale = "und"
                    rec = AnnouncementRecord(
                        content_id=content_id,
                        title=title,
                        body=body,
                        published_at=published_at,
                        source_url=str(item.get("source_url", "")),
                        content_version=self._normalize_version(
                            item.get("content_version", 1), "公告内容版本"
                        ),
                        category=str(item.get("category", "general")),
                        deadline_at=item.get("deadline_at"),
                        deadline_version=self._normalize_version(
                            item.get("deadline_version", 1), "公告日程版本"
                        ),
                        locale=locale,
                    )
                except (TypeError, ValueError) as exc:
                    logger.warning("跳过损坏的公告缓存记录: %s", exc)
                    continue
                self._records[rec.content_id] = rec
                if "last_changed_at" not in item or item.get("last_changed_at") in (None, ""):
                    # 旧缓存没有本地维护时间时，从迁移时刻起安全保留，避免按发布时间立即误删。
                    self._last_changed_at[rec.content_id] = migration_timestamp
                    migrated_legacy_timestamp = True
                else:
                    self._last_changed_at[rec.content_id] = str(item["last_changed_at"])
                history = self._revision_history.setdefault(rec.content_id, [])
                if rec.content_fingerprint not in history:
                    history.append(rec.content_fingerprint)
                    self._revision_history[rec.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
                for dl in DeadlineParser.parse_deadlines(rec.title, rec.body, rec.content_id, rec.category):
                    dl.deadline_version = rec.deadline_version
                    self._deadlines[dl.event_id] = dl
            for key in data.get("delivery_log", []):
                self._delivery_log.add(str(key))
            if migrated_legacy_timestamp:
                self.save_cache()
            logger.info("已成功从本地磁盘缓存加载 %d 条公告数据", len(self._records))
        except Exception as exc:
            logger.error("加载公告本地缓存失败: %s", safe_exception_message(exc))

    def save_cache(self) -> None:
        """保存公告与日程数据至本地磁盘缓存。"""
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            records_data = []
            for rec in self._records.values():
                records_data.append({
                    "content_id": rec.content_id,
                    "title": rec.title,
                    "body": rec.body,
                    "published_at": rec.published_at,
                    "source_url": rec.source_url,
                    "content_version": rec.content_version,
                    "category": rec.category,
                    "deadline_at": rec.deadline_at,
                    "deadline_version": rec.deadline_version,
                    "locale": rec.locale,
                    "last_changed_at": self._last_changed_at.get(rec.content_id),
                })
            payload = {
                "last_updated_at": self.last_updated_at,
                "records": records_data,
                "revision_history": self._revision_history,
                "last_sync_report": self.last_sync_report,
                "delivery_log": sorted(self._delivery_log),
            }
            tmp_file = self.cache_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp_file.replace(self.cache_file)
        except Exception as exc:
            logger.error("保存公告本地缓存失败: %s", safe_exception_message(exc))

    def add_or_update(
        self,
        record: AnnouncementRecord,
        *,
        persist: bool = True,
    ) -> tuple[bool, bool]:
        """添加或更新公告。
        返回 (is_new, is_updated)。
        """
        if not isinstance(record.content_id, str):
            raise ValueError("公告稳定 ID 必须是文本")
        record.content_id = record.content_id.strip()
        if not record.content_id or record.content_id.casefold() == "none":
            raise ValueError("公告缺少稳定 ID")
        if not isinstance(record.title, str) or not isinstance(record.body, str):
            raise ValueError("公告标题和正文必须是文本")
        if not isinstance(record.published_at, str):
            raise ValueError("公告发布时间必须是文本")
        record.content_version = self._normalize_version(record.content_version, "公告内容版本")
        record.deadline_version = self._normalize_version(record.deadline_version, "公告日程版本")
        record.locale = self.normalize_locale(record.locale, allow_und=True)
        existing = self._records.get(record.content_id)
        fingerprint = record.content_fingerprint
        history = self._revision_history.setdefault(record.content_id, [])
        self._last_update_outcome = "unchanged"
        revision_action = AnnouncementVersioning.classify(existing, fingerprint, history)
        if revision_action == "new":
            self._records[record.content_id] = record
            self._last_changed_at[record.content_id] = self._now_timestamp()
            if fingerprint not in history:
                history.append(fingerprint)
                self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            parsed = DeadlineParser.parse_deadlines(
                record.title, record.body, record.content_id, record.category
            )
            for dl in parsed:
                dl.deadline_version = record.deadline_version
                self._deadlines[dl.event_id] = dl
            self.last_updated_at = self._now_utc().astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
            self._last_update_outcome = "new"
            if persist:
                self.save_cache()
            return True, False

        if revision_action == "unchanged":
            if fingerprint not in history:
                history.append(fingerprint)
                self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            return False, False

        # 已知旧指纹再次出现时按乱序回放处理，绝不回滚已显示版本或日程。
        if revision_action == "stale":
            self._last_update_outcome = "stale"
            return False, False

        # 未知的新指纹按成功扫描到达顺序升级；diagnostic 会明确来源顺序尚未证实。
        if revision_action == "updated":
            self._records[record.content_id] = record
            previous = sorted(
                (dl.event_id, dl.start_at, dl.end_at) for dl in self._deadlines.values()
                if dl.source_content_id == record.content_id
            )
            # 重新解析 deadline 前，先清理该公告旧版本产生的旧日程
            self._deadlines = {
                k: v for k, v in self._deadlines.items() if v.source_content_id != record.content_id
            }
            parsed = DeadlineParser.parse_deadlines(
                record.title, record.body, record.content_id, record.category
            )
            current = sorted((dl.event_id, dl.start_at, dl.end_at) for dl in parsed)
            record.content_version, record.deadline_version = AnnouncementVersioning.next_versions(
                existing, previous, current
            )
            for dl in parsed:
                dl.deadline_version = record.deadline_version
                self._deadlines[dl.event_id] = dl
            history.append(fingerprint)
            self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            self._last_changed_at[record.content_id] = self._now_timestamp()
            self.last_updated_at = self._now_utc().astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
            self._last_update_outcome = "updated"
            if persist:
                self.save_cache()
            return False, True

        return False, False

    @staticmethod
    def _parse_aware_timestamp(value: str) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    def prune_cache(self, *, now: datetime | None = None, retention_days: int | None = None) -> int:
        """删除可证明过期且没有进行中日程的缓存公告。"""
        days = self.CACHE_RETENTION_DAYS if retention_days is None else retention_days
        if type(days) is not int or days < 14:
            raise ValueError("公告缓存保留期不能短于 14 天")
        current = now or self._now_utc()
        if current.tzinfo is None:
            raise ValueError("清理时间必须包含时区")
        current = current.astimezone(timezone.utc)
        cutoff = current - timedelta(days=days)
        removed = 0
        for content_id, rec in list(self._records.items()):
            published = self._parse_aware_timestamp(rec.published_at)
            changed = self._parse_aware_timestamp(self._last_changed_at.get(content_id))
            if published is None or changed is None or published >= cutoff or changed >= cutoff:
                continue
            related = [deadline for deadline in self._deadlines.values() if deadline.source_content_id == content_id]
            if any(deadline.end_at >= current for deadline in related):
                continue
            self._records.pop(content_id, None)
            self._last_changed_at.pop(content_id, None)
            self._revision_history.pop(content_id, None)
            self._deadlines = {
                event_id: deadline
                for event_id, deadline in self._deadlines.items()
                if deadline.source_content_id != content_id
            }
            removed += 1
        if removed:
            self.save_cache()
        return removed

    def should_deliver(self, push_key: str) -> bool:
        """检查指定投递去重键是否已投递。"""
        return push_key not in self._delivery_log

    def mark_delivered(self, push_key: str) -> None:
        """记录投递成功并立即持久化。"""
        self._delivery_log.add(push_key)
        self.save_cache()
