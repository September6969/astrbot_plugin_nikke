# SPDX-License-Identifier: GPL-3.0-or-later
"""官方公告、活动日程与推送管理服务。

遵循 docs/ANNOUNCEMENT_V2_CONTRACT.md：
1. AnnouncementRecord 包含 content_id, body_hash, content_version, published_at, source_url；
2. 内容实体不保存全局 pushed: bool；
3. 投递去重键：target_id + content_id + content_version + push_type；
4. Deadline 去重键：target_id + deadline_id + deadline_version + reminder_hour + push_type；
5. 变更检测：content_id 相同但 body_hash 变化时生成新版本；
6. 统一使用 timezone-aware datetime（默认 UTC+8 展示）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .announcement_models import AnnouncementRecord

logger = logging.getLogger("nikke.announcements")
CST = timezone(timedelta(hours=8))


@dataclass(slots=True)
class GameDeadline:
    event_id: str
    name: str
    category: str
    end_at: datetime
    start_at: datetime | None = None
    source_content_id: str = ""
    source_url: str = ""
    deadline_version: int = 1

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.start_at and current < self.start_at:
            return False
        return current <= self.end_at

    def remaining_display(self, now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        if current > self.end_at:
            return "已结束"
        diff = self.end_at - current
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        if days > 0:
            return f"剩余 {days}天 {hours}小时"
        if hours > 0:
            return f"剩余 {hours}小时 {minutes}分钟"
        return f"剩余 {max(1, minutes)}分钟"


class DeadlineParser:
    MONTHS = {name.lower(): index for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}

    @classmethod
    def _normalize_english_dates(cls, body):
        """只转换带明确年份和时间的英文月份日期，不补猜年份。"""
        pattern = re.compile(r"\b(" + "|".join(cls.MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\s+(?:at\s+)?(?=\d{1,2}:\d{2})", re.IGNORECASE)
        return pattern.sub(lambda match: f"{match[3]}-{cls.MONTHS[match[1].lower()]:02d}-{int(match[2]):02d} ", body)

    # 匹配类似 2026.09.15 04:59 或 2026-09-15 05:00 或 2026/09/15 23:59 的时间
    DATETIME_PATTERN = re.compile(
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s+(\d{1,2}):(\d{2})"
    )

    @classmethod
    def _extract_timezone(cls, snippet: str, context: str = "") -> timezone:
        """从时间附近文本或上下文检测时区。默认 CST (UTC+8)。"""
        tz_pattern = re.compile(
            r"(?:\(|\b)(?:UTC|GMT)\s*([+-]\d{1,2})(?:\b|\))|"
            r"(?:\(|\b)(JST|KST)(?:\b|\))|"
            r"(?:\(|\b)(CST|SGT|HKT|BJT)(?:\b|\))|"
            r"(?:\(|\b)(UTC|GMT)(?:\b|\))|"
            r"(?:\(|\b)(PST)(?:\b|\))|"
            r"(?:\(|\b)(PDT)(?:\b|\))",
            re.IGNORECASE,
        )
        for target in (snippet, context):
            if not target:
                continue
            m = tz_pattern.search(target)
            if m:
                if m.group(1):
                    try:
                        return timezone(timedelta(hours=int(m.group(1))))
                    except ValueError:
                        pass
                name = (m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or "").upper()
                if name in ("JST", "KST"):
                    return timezone(timedelta(hours=9))
                if name in ("CST", "SGT", "HKT", "BJT"):
                    return timezone(timedelta(hours=8))
                if name in ("UTC", "GMT"):
                    return timezone.utc
                if name == "PST":
                    return timezone(timedelta(hours=-8))
                if name == "PDT":
                    return timezone(timedelta(hours=-7))
        return CST

    @classmethod
    def parse_deadlines(
        cls,
        title: str,
        body: str,
        content_id: str = "",
        category: str = "event",
    ) -> list[GameDeadline]:
        body = cls._normalize_english_dates(body)
        matches = list(cls.DATETIME_PATTERN.finditer(body))
        if not matches:
            return []

        deadlines: list[GameDeadline] = []
        # 如果找到至少两个时间点（通常为 开始 ~ 结束）
        if len(matches) > 2:
            # 多事件正文尚无可靠分段合同，保守拒绝把前两个日期拼成活动。
            return []
        if len(matches) == 2:
            try:
                m_start, m_end = matches[0], matches[1]
                between = body[m_start.end():m_end.start()]
                if len(between) > 120 or not re.search(r"[~～–—]|(?<!\w)-(?!\w)|至|到|结束|\b(?:to|until|ends?|ending)\b", between, re.IGNORECASE):
                    return []
                start_tz = cls._extract_timezone(body[m_start.end() : m_start.end() + 30], body)
                start_dt = datetime(
                    int(m_start.group(1)),
                    int(m_start.group(2)),
                    int(m_start.group(3)),
                    int(m_start.group(4)),
                    int(m_start.group(5)),
                    tzinfo=start_tz,
                ).astimezone(timezone.utc)

                end_tz = cls._extract_timezone(body[m_end.end() : m_end.end() + 30], body)
                end_dt = datetime(
                    int(m_end.group(1)),
                    int(m_end.group(2)),
                    int(m_end.group(3)),
                    int(m_end.group(4)),
                    int(m_end.group(5)),
                    tzinfo=end_tz,
                ).astimezone(timezone.utc)

                if end_dt <= start_dt:
                    return []
                deadlines.append(
                    GameDeadline(
                        event_id=f"{content_id or hashlib.md5(title.encode()).hexdigest()[:8]}_0",
                        name=title,
                        category=category,
                        start_at=start_dt,
                        end_at=end_dt,
                        source_content_id=content_id,
                    )
                )
            except (ValueError, OverflowError):
                pass
        elif len(matches) == 1:
            # 只有单个时间点时，严格检查是否为截止时间。
            # 如果是“开始/开启/上线/首发”等开始时间，绝不能误标为截止日程。
            m_single = matches[0]
            start_pos = max(0, m_single.start() - 30)
            end_pos = min(len(body), m_single.end() + 30)
            surrounding = (body[start_pos:end_pos] + " " + title).lower()

            is_start_marker = bool(
                re.search(r"开始|开启|上线|开放|举办|发布|启动|\b(?:starts?|starting|opens?|opening|launch(?:es|ing)?|begins?|beginning)\b", surrounding)
            )
            is_deadline_marker = bool(
                re.search(r"截止|结束|至|到|前|\b(?:ends?|ending|until|deadline)\b|维护结束", surrounding)
            )

            # 如果含有明确的“开始”语义且没有明确的“截止”语义，跳过不建 deadline
            if is_start_marker and not is_deadline_marker:
                return []
            # 如果既没有截止词也没有任何结束标识，避免盲目将单个时间识别为 deadline
            if not is_deadline_marker:
                return []

            try:
                end_tz = cls._extract_timezone(body[m_single.end() : m_single.end() + 30], body)
                end_dt = datetime(
                    int(m_single.group(1)),
                    int(m_single.group(2)),
                    int(m_single.group(3)),
                    int(m_single.group(4)),
                    int(m_single.group(5)),
                    tzinfo=end_tz,
                ).astimezone(timezone.utc)

                deadlines.append(
                    GameDeadline(
                        event_id=f"{content_id or hashlib.md5(title.encode()).hexdigest()[:8]}_0",
                        name=title,
                        category=category,
                        start_at=None,
                        end_at=end_dt,
                        source_content_id=content_id,
                    )
                )
            except (ValueError, OverflowError):
                pass

        return deadlines


class AnnouncementService:
    SUPPORTED_LOCALES = frozenset({"en", "ja", "ko", "th", "de", "fr"})
    CACHE_LOCALES = SUPPORTED_LOCALES | {"und"}
    NORMAL_MAX_PAGES = 2
    NORMAL_PAGE_SIZE = 5
    DEEP_MAX_PAGES = 5
    DEEP_PAGE_SIZE = 20
    CACHE_RETENTION_DAYS = 90
    REVISION_HISTORY_LIMIT = 8
    CATEGORY_ALIASES = {
        "公告": "general",
        "综合": "general",
        "维护": "maintenance",
        "活动": "event",
        "更新": "update",
        "版本更新": "update",
        "开发者笔记": "dev_note",
        "招募": "recruit",
        "联盟突袭": "union_raid",
    }

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else None
        self._records: dict[str, AnnouncementRecord] = {}
        self._deadlines: dict[str, GameDeadline] = {}
        self._revision_history: dict[str, list[str]] = {}
        self._delivery_log: set[str] = set()
        self.last_updated_at: str | None = None
        self.last_sync_report: dict[str, Any] | None = None
        self.cache_file = (self.data_dir / "announcements_cache.json") if self.data_dir else None
        if self.cache_file and self.cache_file.is_file():
            self.load_cache()

    @classmethod
    def normalize_locale(cls, value: str | None, *, allow_und: bool = False) -> str:
        """只允许已验证的官网语言及缓存迁移值。"""
        locale = (value or "en").strip().casefold()
        supported = cls.CACHE_LOCALES if allow_und else cls.SUPPORTED_LOCALES
        if locale not in supported:
            raise ValueError("公告语言仅支持 en、ja、ko、th、de、fr")
        return locale

    @staticmethod
    def _locale_from_content_id(content_id: str) -> str:
        parts = content_id.split(":", 2)
        if len(parts) == 3 and parts[0] == "informationfeeds" and parts[1] in AnnouncementService.SUPPORTED_LOCALES:
            return parts[1]
        return "und"

    @classmethod
    def _normalize_category(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        category = cls.CATEGORY_ALIASES.get(value.strip().casefold(), value.strip().casefold())
        if len(category) > 32 or not re.fullmatch(r"[a-z0-9_-]+", category):
            raise ValueError("公告分类仅支持本地分类标识或预设中文别名")
        return category

    @staticmethod
    def _normalize_query(value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        query = " ".join(value.split())
        if len(query) > 80:
            raise ValueError("公告搜索词不能超过 80 个字符")
        return query.casefold()

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
                        content_version=int(item.get("content_version", 1)),
                        category=str(item.get("category", "general")),
                        deadline_at=item.get("deadline_at"),
                        deadline_version=int(item.get("deadline_version", 1)),
                        locale=locale,
                    )
                except (TypeError, ValueError) as exc:
                    logger.warning("跳过损坏的公告缓存记录: %s", exc)
                    continue
                self._records[rec.content_id] = rec
                history = self._revision_history.setdefault(rec.content_id, [])
                if rec.content_fingerprint not in history:
                    history.append(rec.content_fingerprint)
                    self._revision_history[rec.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
                for dl in DeadlineParser.parse_deadlines(rec.title, rec.body, rec.content_id, rec.category):
                    dl.deadline_version = rec.deadline_version
                    self._deadlines[dl.event_id] = dl
            for key in data.get("delivery_log", []):
                self._delivery_log.add(str(key))
            logger.info("已成功从本地磁盘缓存加载 %d 条公告数据", len(self._records))
        except Exception as exc:
            logger.error("加载公告本地缓存失败: %s", exc)

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
            logger.error("保存公告本地缓存失败: %s", exc)

    async def sync_from_source(
        self,
        fetcher: Any = None,
        *,
        locale: str = "en",
        deep: bool = False,
    ) -> tuple[bool, str]:
        """同步公开数据；深度扫描受限且不会触发任何投递。"""
        selected_locale = self.normalize_locale(locale)
        try:
            source_name = "injected"
            scan = None
            if fetcher is not None:
                records = await fetcher()
            else:
                from .announcement_sources import InformationFeedsSource

                source = InformationFeedsSource(
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
                    records = await self.fetch_official()
                    source_name = "blablalink-fallback"
                    scan = {"fallback": True, "requested_pages": self.NORMAL_MAX_PAGES, "page_size": self.NORMAL_PAGE_SIZE}
            if not isinstance(records, list):
                raise ValueError("公告来源未返回列表")

            counts = Counter()
            for r in records:
                if not isinstance(r, AnnouncementRecord):
                    counts["invalid"] += 1
                    continue
                try:
                    is_new, is_updated = self.add_or_update(r, persist=False)
                except ValueError:
                    counts["invalid"] += 1
                    continue
                if is_new:
                    counts["new"] += 1
                elif is_updated:
                    counts["updated"] += 1
                else:
                    counts[self._last_update_outcome] += 1
            self.last_updated_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
            self.last_sync_report = {
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
            self.save_cache()
            scope = "深度重扫" if deep else "常规同步"
            return True, f"{scope}成功：收到 {len(records)} 条，新增 {counts['new']} 条，更新 {counts['updated']} 条。"
        except Exception as exc:
            logger.warning("官方公告同步失败，降级读取本地缓存: %s", exc)
            return False, f"官方数据同步失败（{exc}），已降级读取本地缓存"

    @staticmethod
    async def fetch_primary(*, locale: str = "en", deep: bool = False) -> list[AnnouncementRecord]:
        from .announcement_sources import InformationFeedsSource
        try:
            selected_locale = AnnouncementService.normalize_locale(locale)
            return await InformationFeedsSource(
                selected_locale,
                max_pages=(AnnouncementService.DEEP_MAX_PAGES if deep else AnnouncementService.NORMAL_MAX_PAGES),
                page_size=(AnnouncementService.DEEP_PAGE_SIZE if deep else AnnouncementService.NORMAL_PAGE_SIZE),
            ).fetch()
        except Exception:
            # 主源失败继续尝试原有 MVP；两者失败由同步层保留磁盘缓存。
            return await AnnouncementService.fetch_official()

    @staticmethod
    async def fetch_official() -> list[AnnouncementRecord]:
        """生产环境官方公告拉取器（带超时与异常降级）。"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.blablalink.com/api/ugc/direct/standalonesite/User/GetAnnouncements")
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            # 严格校验：若返回权限不足或非 0 状态码，必须抛出受控异常走降级，严禁误判为同步成功
            if code not in (0, "0") or data.get("code_type") == 1:
                msg = data.get("msg") or f"状态码 {code}"
                raise RuntimeError(f"官方公告接口返回业务错误: {msg} (code={code})")
            payload_data = data.get("data")
            if not isinstance(payload_data, dict):
                raise RuntimeError("官方公告数据结构缺失或非字典对象")
            if "list" not in payload_data:
                raise RuntimeError("官方公告数据缺失 list 字段")
            items = payload_data["list"]
            if not isinstance(items, list):
                raise RuntimeError("官方公告 list 字段非列表格式")
            records = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                content_id = it.get("content_id") or it.get("id")
                if not isinstance(content_id, (str, int)) or isinstance(content_id, bool) or not str(content_id).strip():
                    logger.warning("跳过缺少稳定 ID 的公告")
                    continue
                rec = AnnouncementRecord(
                    content_id=str(content_id),
                    title=str(it.get("title", "")),
                    body=str(it.get("content", "") or it.get("body", "")),
                    published_at=str(it.get("publish_time", "")),
                    source_url=str(it.get("url", "")),
                    locale="und",
                )
                records.append(rec)
        return records

    def add_or_update(
        self,
        record: AnnouncementRecord,
        *,
        persist: bool = True,
    ) -> tuple[bool, bool]:
        """添加或更新公告。
        返回 (is_new, is_updated)。
        """
        if not record.content_id or record.content_id.strip() in {"", "None"}:
            raise ValueError("公告缺少稳定 ID")
        record.locale = self.normalize_locale(record.locale, allow_und=True)
        existing = self._records.get(record.content_id)
        fingerprint = record.content_fingerprint
        history = self._revision_history.setdefault(record.content_id, [])
        self._last_update_outcome = "unchanged"
        if not existing:
            self._records[record.content_id] = record
            if fingerprint not in history:
                history.append(fingerprint)
                self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            parsed = DeadlineParser.parse_deadlines(
                record.title, record.body, record.content_id, record.category
            )
            for dl in parsed:
                dl.deadline_version = record.deadline_version
                self._deadlines[dl.event_id] = dl
            self.last_updated_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
            self._last_update_outcome = "new"
            if persist:
                self.save_cache()
            return True, False

        if fingerprint == existing.content_fingerprint:
            if fingerprint not in history:
                history.append(fingerprint)
                self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            return False, False

        # 已知旧指纹再次出现时按乱序回放处理，绝不回滚已显示版本或日程。
        if fingerprint in history:
            self._last_update_outcome = "stale"
            return False, False

        # 未知的新指纹按成功扫描到达顺序升级；diagnostic 会明确来源顺序尚未证实。
        if fingerprint != existing.content_fingerprint:
            new_version = existing.content_version + 1
            record.content_version = new_version
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
            record.deadline_version = existing.deadline_version + int(previous != current)
            for dl in parsed:
                dl.deadline_version = record.deadline_version
                self._deadlines[dl.event_id] = dl
            history.append(fingerprint)
            self._revision_history[record.content_id] = history[-self.REVISION_HISTORY_LIMIT:]
            self.last_updated_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
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
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("清理时间必须包含时区")
        current = current.astimezone(timezone.utc)
        cutoff = current - timedelta(days=days)
        removed = 0
        for content_id, rec in list(self._records.items()):
            published = self._parse_aware_timestamp(rec.published_at)
            if published is None or published >= cutoff:
                continue
            related = [deadline for deadline in self._deadlines.values() if deadline.source_content_id == content_id]
            if any(deadline.end_at >= current for deadline in related):
                continue
            self._records.pop(content_id, None)
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
        selected_locale = self.normalize_locale(locale, allow_und=True) if locale else None
        selected_category = self._normalize_category(category)
        selected_query = self._normalize_query(query)
        items = list(self._records.values())
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

    def format_diagnostic_text(self) -> str:
        """返回不含正文、订阅 target 或凭据的本地只读诊断。"""
        locale_counts = Counter(record.locale for record in self._records.values())
        category_counts = Counter(record.category for record in self._records.values())
        lines = ["【公告诊断（公开只读）】", f"缓存公告: {len(self._records)} 条"]
        if self.last_updated_at:
            lines.append(f"最近同步: {self.last_updated_at}")
        if self.last_sync_report:
            report = self.last_sync_report
            scope = "深度重扫" if report.get("deep") else "常规同步"
            lines.append(
                f"最近范围: {scope} · locale={report.get('locale', 'unknown')} · "
                f"收到 {report.get('received', 0)} / 新增 {report.get('new', 0)} / "
                f"更新 {report.get('updated', 0)} / 乱序回放忽略 {report.get('stale', 0)}"
            )
            lines.append(f"来源顺序: {report.get('source_order', 'unknown')}（未宣称官方修改时序）")
        else:
            lines.append("最近范围: 尚未同步")
        locales = ", ".join(f"{name}: {count}" for name, count in sorted(locale_counts.items())) or "无"
        categories = ", ".join(f"{name}: {count}" for name, count in sorted(category_counts.items())) or "无"
        lines.append(f"locale: {locales}")
        lines.append(f"category: {categories}")
        lines.append(
            f"缓存保留: {self.CACHE_RETENTION_DAYS} 天；已见内容指纹最多 {self.REVISION_HISTORY_LIMIT} 个/公告。"
        )
        lines.append("本诊断不发起网络请求、不发送消息，也不输出订阅目标或凭据。")
        return "\n".join(lines)

    def list_active_deadlines(self, now: datetime | None = None) -> list[GameDeadline]:
        current = now or datetime.now(timezone.utc)
        active = [dl for dl in self._deadlines.values() if dl.is_active(current)]
        active.sort(key=lambda dl: dl.end_at)
        return active

    def should_deliver(self, push_key: str) -> bool:
        """检查指定投递去重键是否已投递。"""
        return push_key not in self._delivery_log

    def mark_delivered(self, push_key: str) -> None:
        """记录投递成功并立即持久化。"""
        self._delivery_log.add(push_key)
        self.save_cache()

    def format_announcements_text(
        self,
        limit: int = 5,
        fallback_error: str = "",
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> str:
        selected_locale = self.normalize_locale(locale, allow_und=True) if locale else None
        selected_category = self._normalize_category(category)
        selected_query = self._normalize_query(query)
        records = self.list_announcements(
            limit,
            locale=selected_locale,
            category=selected_category,
            query=selected_query,
        )
        if not records:
            if self._records:
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
        if self.last_updated_at:
            lines.append(f"（最近更新时间: {self.last_updated_at}）")
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

    def format_schedule_text(self, now: datetime | None = None, fallback_error: str = "") -> str:
        current = now or datetime.now(timezone.utc)
        if not self._records:
            if fallback_error:
                return f"暂时无法获取官方日程：{fallback_error}。当前没有可用缓存，请稍后重试。"
            return "功能尚未就绪，正在同步官方数据，请稍候。"
        deadlines = self.list_active_deadlines(current)
        if not deadlines:
            time_hint = f"（最近更新时间: {self.last_updated_at}）" if self.last_updated_at else ""
            err_hint = f"\n⚠️ {fallback_error}" if fallback_error else ""
            return f"近期暂无可追踪的官方活动日程。{time_hint}{err_hint}".strip()
        lines = ["【NIKKE 近期日程与活动倒计时】"]
        if self.last_updated_at:
            lines.append(f"（最近更新时间: {self.last_updated_at}）")
        if fallback_error:
            lines.append(f"⚠️ {fallback_error}")
        lines.append("")
        ongoing = []
        ending_soon = []
        for dl in deadlines:
            rem = dl.remaining_display(current)
            end_cst = dl.end_at.astimezone(CST).strftime("%m-%d %H:%M")
            entry = f"• {dl.name}\n  截止: {end_cst} ({rem})"
            diff = dl.end_at - current
            if diff.total_seconds() < 86400 * 2:
                ending_soon.append(entry)
            else:
                ongoing.append(entry)

        if ending_soon:
            lines.append("⏳ 即将结束：")
            lines.extend(ending_soon)
            lines.append("")

        if ongoing:
            lines.append("📌 进行中：")
            lines.extend(ongoing)

        return "\n".join(lines).strip()
