# SPDX-License-Identifier: GPL-3.0-or-later
"""数据源适配器模块 (Schedule Adapters)。

将各个远程/本地源映射为标准 CanonicalEvent 与 FieldEvidence：
- GameKeeScheduleAdapter: GameKee 结构化活动数据 (COMPLETE_SNAPSHOT)
- OfficialAnnouncementScheduleAdapter: 官方公告/维护日程数据 (INCREMENTAL)
- ManualOverrideScheduleAdapter: 手动配置覆盖 (INCREMENTAL)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import _aware_utc
from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    FieldEvidence,
    FetchOutcome,
    ResponseMode,
    SourceRole,
    TimePrecision,
    ManualOverride,
)
from ...integrations.blablalink.fetch_client import FetchClient
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.adapters")


def _canonical_int(value: Any) -> int | None:
    """严格校验整数，拒绝 bool、float 与非纯数字字符串。"""
    if type(value) is int:
        return value
    if isinstance(value, str):
        s = value.strip()
        if s and s.isascii() and s.isdecimal():
            return int(s)
    return None


def _classify_category(title: str, tag: str = "", activity_kind: str = "") -> str:
    """确定性分类标签映射。"""
    text = f"{title} {tag} {activity_kind}".casefold()
    if any(k in text for k in ("协同", "co-op", "coop", "coordinated operation")):
        return "coop"
    if any(k in text for k in ("联盟突袭", "union raid")):
        return "union_raid"
    if any(k in text for k in ("单人突袭", "solo raid")):
        return "solo_raid"
    if any(k in text for k in ("招募", "recruit", "pick up", "pickup")):
        return "recruit"
    if any(k in text for k in ("维护", "maintenance", "停服")):
        return "maintenance"
    if any(k in text for k in ("更新", "update", "版本")):
        return "update"
    return "event"


@dataclass
class FetchResult:
    """标准源抓取结果封装，承载 FetchOutcome 与每源数据。"""

    outcome: FetchOutcome
    events: list[CanonicalEvent] = field(default_factory=list)
    raw_status: int | None = None
    error_message: str = ""
    source: str = ""
    response_mode: ResponseMode = ResponseMode.COMPLETE_SNAPSHOT
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseScheduleAdapter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @property
    def response_mode(self) -> ResponseMode:
        return ResponseMode.COMPLETE_SNAPSHOT

    @property
    def source_timezone(self) -> str:
        return "Asia/Shanghai"

    @abstractmethod
    async def fetch_result(self) -> FetchResult:
        pass

    async def fetch(self) -> list[CanonicalEvent]:
        """向后兼容抽象方法：调用 fetch_result 并返回事件列表，若异常则抛出。"""
        res = await self.fetch_result()
        if res.outcome in (FetchOutcome.SUCCESS_DATA, FetchOutcome.SUCCESS_EMPTY):
            return res.events
        if res.outcome == FetchOutcome.NOT_MODIFIED:
            return []
        raise RuntimeError(
            f"数据源 {self.source_name} 抓取失败: outcome={res.outcome.value}, error={res.error_message}"
        )


class GameKeeScheduleAdapter(BaseScheduleAdapter):
    API_URL = "https://www.gamekee.com/v1/activity/page-list"

    def __init__(self, fetch_client: FetchClient | None = None):
        self.client = fetch_client or FetchClient()
        self.last_scan: dict[str, int] = {
            "rows": 0,
            "valid": 0,
            "malformed": 0,
            "duplicates": 0,
        }

    @property
    def source_name(self) -> str:
        return "gamekee"

    @property
    def response_mode(self) -> ResponseMode:
        return ResponseMode.COMPLETE_SNAPSHOT

    @property
    def source_timezone(self) -> str:
        return "Asia/Shanghai"

    async def fetch_result(self) -> FetchResult:
        headers = {
            "game-alias": "nikke",
        }
        params = {
            "importance": 0,
            "sort": -1,
            "keyword": "",
            "limit": 999,
            "page_no": 1,
            "serverId": 19,
            "status": 0,
        }

        try:
            payload = await self.client.get_json(self.API_URL, headers=headers, params=params)
        except Exception as exc:
            err = safe_exception_message(exc)
            logger.warning("[NIKKE] GameKee 网络请求失败: %s", err)
            return FetchResult(
                outcome=FetchOutcome.REQUEST_FAILED,
                error_message=err,
                source=self.source_name,
                response_mode=self.response_mode,
            )

        if not isinstance(payload, dict):
            return FetchResult(
                outcome=FetchOutcome.SCHEMA_INVALID,
                error_message=f"GameKee 响应根节点必须是 JSON 对象: {type(payload)}",
                source=self.source_name,
                response_mode=self.response_mode,
            )

        code = payload.get("code")
        if code is not None:
            canonical_code = _canonical_int(code)
            if canonical_code not in (0, 200):
                return FetchResult(
                    outcome=FetchOutcome.REQUEST_FAILED,
                    error_message=f"GameKee 接口返回非成功业务码: {code!r}",
                    source=self.source_name,
                    response_mode=self.response_mode,
                )

        data = payload.get("data")
        if not isinstance(data, list):
            return FetchResult(
                outcome=FetchOutcome.SCHEMA_INVALID,
                error_message=f"GameKee 响应 data 节点必须是列表: {type(data)}",
                source=self.source_name,
                response_mode=self.response_mode,
            )

        rows_count = len(data)
        if rows_count == 0:
            self.last_scan = {"rows": 0, "valid": 0, "malformed": 0, "duplicates": 0}
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
            )

        valid_events: list[CanonicalEvent] = []
        seen_ids: set[str] = set()
        malformed_count = 0
        duplicate_count = 0

        for row in data:
            if not isinstance(row, dict):
                malformed_count += 1
                continue

            row_id = _canonical_int(row.get("id"))
            title = str(row.get("title") or "").strip()
            begin_at = _canonical_int(row.get("begin_at"))
            end_at = _canonical_int(row.get("end_at"))

            if (
                row_id is None
                or row_id <= 0
                or not title
                or begin_at is None
                or end_at is None
                or begin_at < 0
            ):
                malformed_count += 1
                continue

            event_id = f"gamekee:{row_id}"
            if event_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(event_id)

            try:
                start_dt = datetime.fromtimestamp(begin_at, tz=timezone.utc)
                end_dt = datetime.fromtimestamp(end_at, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                malformed_count += 1
                continue

            # 非法时间区间校验
            is_valid = (end_dt > start_dt)

            big_picture = str(row.get("big_picture") or "").strip()
            picture = str(row.get("picture") or "").strip()
            banner_url = big_picture or picture or None

            link_url = str(row.get("link_url") or "").strip()
            detail_url = link_url or "https://www.gamekee.com/nikke/"

            tag = str(row.get("tag") or "").strip()
            category = _classify_category(title, tag)

            # 字段级证据
            evidence = {
                "title": [FieldEvidence(title, "gamekee", confidence=0.85, scope="GLOBAL").to_dict()],
                "start": [FieldEvidence(start_dt, "gamekee", confidence=0.85, precision="EXACT", source_timezone=self.source_timezone).to_dict()],
                "end": [FieldEvidence(end_dt, "gamekee", confidence=0.85, precision="EXACT", source_timezone=self.source_timezone).to_dict()],
                "banner_url": [FieldEvidence(banner_url, "gamekee", confidence=0.85).to_dict()] if banner_url else [],
                "detail_url": [FieldEvidence(detail_url, "gamekee", confidence=0.85).to_dict()],
            }

            try:
                event = CanonicalEvent(
                    id=event_id,
                    title=title,
                    event_type=category,
                    start_at=start_dt,
                    end_at=end_dt,
                    start_precision="EXACT",
                    end_precision="EXACT",
                    server_scope="GLOBAL",
                    banner_url=banner_url,
                    detail_url=detail_url,
                    sources=["gamekee"],
                    primary_source="gamekee",
                    confidence=0.85,
                    is_valid_interval=is_valid,
                    field_evidence=evidence,
                    version=1,
                )
                valid_events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] GameKee 条目解析失败: %s", safe_exception_message(exc))
                malformed_count += 1

        self.last_scan = {
            "rows": rows_count,
            "valid": len(valid_events),
            "malformed": malformed_count,
            "duplicates": duplicate_count,
        }

        # Schema drift 保护：返回了数据但全部无法解析
        if rows_count > 0 and len(valid_events) == 0:
            err = f"GameKee 返回了 {rows_count} 条数据但全部无法解析 (malformed={malformed_count})，上游数据结构可能已漂移"
            logger.warning("[NIKKE] %s", err)
            return FetchResult(
                outcome=FetchOutcome.PARSE_FAILED,
                error_message=err,
                source=self.source_name,
                response_mode=self.response_mode,
            )

        return FetchResult(
            outcome=FetchOutcome.SUCCESS_DATA,
            events=valid_events,
            source=self.source_name,
            response_mode=self.response_mode,
        )


class OfficialAnnouncementScheduleAdapter(BaseScheduleAdapter):
    """从已获取的官方公告中提取维护和活动日程 (INCREMENTAL 模式)。"""

    def __init__(self, announcement_service: Any = None):
        self.announcement_service = announcement_service

    @property
    def source_name(self) -> str:
        return "official"

    @property
    def response_mode(self) -> ResponseMode:
        return ResponseMode.INCREMENTAL

    @property
    def source_timezone(self) -> str:
        return "UTC"

    async def fetch_result(self) -> FetchResult:
        if self.announcement_service is None:
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
            )

        deadlines: list[Any] = []
        try:
            if hasattr(self.announcement_service, "list_deadlines"):
                deadlines = self.announcement_service.list_deadlines()
            elif hasattr(self.announcement_service, "list_active_deadlines"):
                deadlines = self.announcement_service.list_active_deadlines()
        except Exception as exc:
            err = safe_exception_message(exc)
            logger.debug("[NIKKE] 官方公告日程读取异常: %s", err)
            return FetchResult(
                outcome=FetchOutcome.REQUEST_FAILED,
                error_message=err,
                source=self.source_name,
                response_mode=self.response_mode,
            )

        records_map: dict[str, Any] = {}
        if hasattr(self.announcement_service, "_records") and isinstance(self.announcement_service._records, dict):
            records_map = self.announcement_service._records
        elif hasattr(self.announcement_service, "list_announcements"):
            try:
                rec_list = self.announcement_service.list_announcements(limit=50)
                records_map = {getattr(r, "content_id", str(i)): r for i, r in enumerate(rec_list)}
            except Exception:
                pass

        # 若无现成 GameDeadline，则尝试从公告正文提取
        if not deadlines and records_map:
            from ..announcement.service import DeadlineParser
            for rec in records_map.values():
                title = getattr(rec, "title", "")
                body = getattr(rec, "body", "") or getattr(rec, "content", "")
                cid = getattr(rec, "content_id", "")
                cat = getattr(rec, "category", "event")
                if title and body:
                    try:
                        parsed = DeadlineParser.parse_deadlines(title, body, cid, cat)
                        deadlines.extend(parsed)
                    except Exception:
                        pass

        if not deadlines:
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
            )

        events: list[CanonicalEvent] = []
        for dl in deadlines:
            title = getattr(dl, "name", "") or getattr(dl, "title", "")
            if not title:
                continue

            start_at = getattr(dl, "start_at", None)
            end_at = getattr(dl, "end_at", None)
            cid = getattr(dl, "source_content_id", "") or getattr(dl, "event_id", title)
            rec = records_map.get(cid)

            event_id = f"official:{getattr(dl, 'event_id', cid)}"
            detail_url = getattr(dl, "source_url", "") or (getattr(rec, "source_url", "") if rec else "")
            cat_raw = getattr(dl, "category", "") or (getattr(rec, "category", "") if rec else "")
            category = _classify_category(title, cat_raw)

            # 严格时区保证为 aware UTC
            if start_at is not None:
                start_at = _aware_utc(start_at)
            if end_at is not None:
                end_at = _aware_utc(end_at)

            start_prec = TimePrecision.EXACT.value if start_at else TimePrecision.UNKNOWN.value
            end_prec = TimePrecision.EXACT.value if end_at else TimePrecision.UNKNOWN.value

            # 基于正文 body 和标题的多维度取消检测
            body_text = getattr(rec, "body", "") if rec else ""
            cancel_target = f"{title} {body_text}".casefold()
            is_cancelled = any(k in cancel_target for k in ("取消", "中止", "活动延期", "停止开放", "cancel"))

            # 置信度评估：双时间且有上下文为 0.95，单结束时间为 0.90，弱上下文为 0.75
            explicit_confidence = getattr(dl, "confidence", None)
            if explicit_confidence is not None:
                confidence = float(explicit_confidence)
            elif start_at and end_at:
                confidence = 0.95
            elif end_at:
                confidence = 0.90
            else:
                confidence = 0.70

            evidence = {
                "title": [FieldEvidence(title, "official", confidence=confidence).to_dict()],
                "cancellation": [FieldEvidence(is_cancelled, "official", confidence=1.0, is_cancelled=is_cancelled).to_dict()] if is_cancelled else [],
            }
            if start_at:
                evidence["start"] = [FieldEvidence(start_at, "official", confidence=confidence, precision=start_prec).to_dict()]
            if end_at:
                evidence["end"] = [FieldEvidence(end_at, "official", confidence=confidence, precision=end_prec).to_dict()]
            if detail_url:
                evidence["detail_url"] = [FieldEvidence(detail_url, "official", confidence=confidence).to_dict()]

            is_valid = True
            if start_at and end_at and end_at <= start_at:
                is_valid = False

            try:
                event = CanonicalEvent(
                    id=event_id,
                    title=title,
                    event_type=category,
                    start_at=start_at,
                    end_at=end_at,
                    start_precision=start_prec,
                    end_precision=end_prec,
                    server_scope="GLOBAL",
                    banner_url=None,
                    detail_url=detail_url or None,
                    sources=["official"],
                    primary_source="official",
                    confidence=confidence,
                    is_cancelled=is_cancelled,
                    is_valid_interval=is_valid,
                    field_evidence=evidence,
                    version=1,
                )
                events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] 官方日程条目构造跳过: %s", safe_exception_message(exc))

        return FetchResult(
            outcome=FetchOutcome.SUCCESS_DATA if events else FetchOutcome.SUCCESS_EMPTY,
            events=events,
            source=self.source_name,
            response_mode=self.response_mode,
        )


class ManualOverrideScheduleAdapter(BaseScheduleAdapter):
    """手动配置覆盖适配器。"""

    def __init__(self, config_path: Path | str | None = None):
        self.config_path = Path(config_path) if config_path else None

    @property
    def source_name(self) -> str:
        return "manual"

    @property
    def response_mode(self) -> ResponseMode:
        return ResponseMode.INCREMENTAL

    def load_overrides(self) -> list[ManualOverride]:
        """读取纯字段覆盖层记录 (ManualOverride)。"""
        if not self.config_path or not self.config_path.is_file():
            return []
        try:
            content = self.config_path.read_text(encoding="utf-8")
            items = json.loads(content)
            if not isinstance(items, list):
                return []
            overrides: list[ManualOverride] = []
            for item in items:
                if isinstance(item, dict) and "event_id" in item and "field" in item:
                    overrides.append(ManualOverride(
                        event_id=str(item["event_id"]),
                        field=str(item["field"]),
                        value=item.get("value"),
                        operator=str(item.get("operator", "admin")),
                        reason=str(item.get("reason", "")),
                        created_at=_aware_utc(item.get("created_at", datetime.now(timezone.utc))),
                        expires_at=_aware_utc(item["expires_at"]) if item.get("expires_at") else None,
                    ))
            return overrides
        except Exception as exc:
            logger.warning("[NIKKE] 手动覆盖层配置解析失败: %s", safe_exception_message(exc))
            return []

    async def fetch_result(self) -> FetchResult:
        """支持完整的事件条目作为基础输入源（若用户配置了独立完整事件）。"""
        if not self.config_path or not self.config_path.is_file():
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
            )

        try:
            content = self.config_path.read_text(encoding="utf-8")
            items = json.loads(content)
            if not isinstance(items, list):
                return FetchResult(
                    outcome=FetchOutcome.SCHEMA_INVALID,
                    error_message="手动配置必须是列表",
                    source=self.source_name,
                    response_mode=self.response_mode,
                )

            events: list[CanonicalEvent] = []
            for item in items:
                if isinstance(item, dict) and "title" in item and ("start_at" in item or "end_at" in item):
                    item["sources"] = ["manual"]
                    item["primary_source"] = "manual"
                    item["confidence"] = 1.0
                    events.append(CanonicalEvent.from_dict(item))

            return FetchResult(
                outcome=FetchOutcome.SUCCESS_DATA if events else FetchOutcome.SUCCESS_EMPTY,
                events=events,
                source=self.source_name,
                response_mode=self.response_mode,
            )
        except Exception as exc:
            err = safe_exception_message(exc)
            logger.warning("[NIKKE] 手动日程配置解析失败: %s", err)
            return FetchResult(
                outcome=FetchOutcome.PARSE_FAILED,
                error_message=err,
                source=self.source_name,
                response_mode=self.response_mode,
            )
