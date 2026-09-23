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
from .content_quality import apply_display_relevance, classify_category, should_parse_deadlines
from astrbot_plugin_nikke.features.calendar.canonical_models import (
    CanonicalEvent,
    FieldEvidence,
    FetchOutcome,
    ResponseMode,
    SourceRole,
    TimePrecision,
    ManualOverride,
)
from .gamekee_parser import ParseFailure, parse_gamekee_row
from ...core.privacy import safe_exception_message
from .ports import CalendarFetchGateway

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


def _classify_category(title: str, tag: str = "", activity_kind: str = "", description: str = "") -> str:
    """旧 API 兼容包装，实际分类只保留一份实现。"""
    return classify_category(title, tag, activity_kind, description)


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
    diagnostics: dict[str, Any] = field(default_factory=dict)


class BaseScheduleAdapter(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        pass

    @property
    def source_role(self) -> SourceRole:
        try:
            name = self.source_name.lower()
        except Exception:
            return SourceRole.OPTIONAL
        if name == "gamekee":
            return SourceRole.PRIMARY
        if name == "official":
            return SourceRole.AUTHORITATIVE_SUPPLEMENT
        if name in ("manual", "override", "manual_override"):
            return SourceRole.LOCAL_OVERRIDE
        return SourceRole.OPTIONAL

    @property
    def contributes_to_freshness(self) -> bool:
        return self.source_role not in (SourceRole.LOCAL_OVERRIDE, SourceRole.AUTHORITATIVE_SUPPLEMENT)

    @property
    def required_for_complete(self) -> bool:
        return self.source_role == SourceRole.PRIMARY

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

    def __init__(self, fetch_client: CalendarFetchGateway | None = None):
        self.client = fetch_client
        self.last_scan: dict[str, Any] = {
            "rows": 0,
            "valid": 0,
            "malformed": 0,
            "duplicates": 0,
            "with_visual": 0,
        }

    @property
    def source_name(self) -> str:
        return "gamekee"

    @property
    def source_role(self) -> SourceRole:
        return SourceRole.PRIMARY

    @property
    def contributes_to_freshness(self) -> bool:
        return True

    @property
    def required_for_complete(self) -> bool:
        return True

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
            if self.client is None:
                raise RuntimeError("Calendar 网络端口尚未由组合根装配")
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
            self.last_scan = {
                "rows": 0,
                "valid": 0,
                "malformed": 0,
                "duplicates": 0,
                "with_visual": 0,
                "malformed_reasons": {},
            }
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
                diagnostics={"gamekee_rows": 0, "gamekee_valid": 0},
            )

        valid_events: list[CanonicalEvent] = []
        seen_ids: set[str] = set()
        malformed_count = 0
        duplicate_count = 0
        visual_count = 0
        malformed_reasons: dict[str, int] = {}

        for row_index, row in enumerate(data):
            parsed = parse_gamekee_row(row, row_index=row_index)
            if isinstance(parsed, ParseFailure):
                malformed_count += 1
                malformed_reasons[parsed.reason] = malformed_reasons.get(parsed.reason, 0) + 1
                continue

            event_id = f"gamekee:{parsed.source_id}"
            if event_id in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(event_id)

            if parsed.visual_candidates:
                visual_count += 1

            # 字段级证据
            evidence = {
                "title": [FieldEvidence(parsed.title, "gamekee", confidence=0.85, scope="GLOBAL").to_dict()],
                "start": [FieldEvidence(parsed.start_at, "gamekee", confidence=0.85, precision="EXACT", source_timezone=self.source_timezone).to_dict()],
                "end": [FieldEvidence(parsed.end_at, "gamekee", confidence=0.85, precision="EXACT", source_timezone=self.source_timezone).to_dict()],
                "banner_url": [FieldEvidence(parsed.banner_url, "gamekee", confidence=0.85).to_dict()] if parsed.banner_url else [],
                "detail_url": [FieldEvidence(parsed.detail_url, "gamekee", confidence=0.85).to_dict()],
            }

            try:
                event = CanonicalEvent(
                    id=event_id,
                    title=parsed.title,
                    event_type=parsed.category,
                    start_at=parsed.start_at,
                    end_at=parsed.end_at,
                    start_precision="EXACT",
                    end_precision="EXACT",
                    server_scope="GLOBAL",
                    banner_url=parsed.banner_url or None,
                    detail_url=parsed.detail_url or None,
                    sources=["gamekee"],
                    primary_source="gamekee",
                    confidence=0.85,
                    field_evidence=evidence,
                    metadata=parsed.to_metadata(),
                    version=1,
                )
                apply_display_relevance(event)
                valid_events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] GameKee 条目解析失败: %s", safe_exception_message(exc))
                malformed_count += 1
                malformed_reasons["model"] = malformed_reasons.get("model", 0) + 1

        self.last_scan = {
            "rows": rows_count,
            "valid": len(valid_events),
            "malformed": malformed_count,
            "duplicates": duplicate_count,
            "with_visual": visual_count,
            "malformed_reasons": malformed_reasons,
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
                diagnostics={
                    "gamekee_rows": rows_count,
                    "gamekee_valid": 0,
                    "gamekee_malformed": malformed_count,
                    "gamekee_duplicates": duplicate_count,
                    "with_visual": visual_count,
                    "malformed_reasons": malformed_reasons,
                },
            )

        return FetchResult(
            outcome=FetchOutcome.SUCCESS_DATA,
            events=valid_events,
            source=self.source_name,
            response_mode=self.response_mode,
            diagnostics={
                "gamekee_rows": rows_count,
                "gamekee_valid": len(valid_events),
                "gamekee_malformed": malformed_count,
                "gamekee_duplicates": duplicate_count,
                "with_visual": visual_count,
                "malformed_reasons": malformed_reasons,
            },
        )


class OfficialAnnouncementScheduleAdapter(BaseScheduleAdapter):
    """从已获取的官方公告中提取维护和活动日程 (INCREMENTAL 模式)。"""

    def __init__(self, announcement_service: Any = None):
        self.announcement_service = announcement_service

    @property
    def source_name(self) -> str:
        return "official"

    @property
    def source_role(self) -> SourceRole:
        return SourceRole.AUTHORITATIVE_SUPPLEMENT

    @property
    def contributes_to_freshness(self) -> bool:
        return False

    @property
    def required_for_complete(self) -> bool:
        return False

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
        diagnostics: dict[str, Any] = {
            "official_deadlines_seen": 0,
            "official_deadlines_filtered": 0,
            "official_deadlines_parsed": 0,
        }
        try:
            if hasattr(self.announcement_service, "list_deadlines"):
                deadlines = self.announcement_service.list_deadlines()
                diagnostics["official_deadlines_parsed"] = len(deadlines) if isinstance(deadlines, list) else 0
            elif hasattr(self.announcement_service, "list_active_deadlines"):
                deadlines = self.announcement_service.list_active_deadlines()
                diagnostics["official_deadlines_parsed"] = len(deadlines) if isinstance(deadlines, list) else 0
            diagnostics["official_deadlines_seen"] = len(deadlines) if isinstance(deadlines, list) else 0
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
            from ..announcement.deadlines import DeadlineParser
            for rec in records_map.values():
                title = getattr(rec, "title", "")
                body = getattr(rec, "body", "") or getattr(rec, "content", "")
                cid = getattr(rec, "content_id", "")
                cat = getattr(rec, "category", "event")
                diagnostics["official_deadlines_seen"] += 1
                if not title or not body or not should_parse_deadlines(title, body):
                    diagnostics["official_deadlines_filtered"] += 1
                    continue
                try:
                    parsed = DeadlineParser.parse_deadlines(title, body, cid, cat)
                    deadlines.extend(parsed)
                    diagnostics["official_deadlines_parsed"] += len(parsed)
                except Exception:
                    continue

        if diagnostics["official_deadlines_seen"] == 0 and deadlines:
            diagnostics["official_deadlines_seen"] = len(deadlines)
            diagnostics["official_deadlines_parsed"] = len(deadlines)

        if not deadlines:
            return FetchResult(
                outcome=FetchOutcome.SUCCESS_EMPTY,
                events=[],
                source=self.source_name,
                response_mode=self.response_mode,
                diagnostics=diagnostics,
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
            body_text = (getattr(rec, "body", "") or getattr(rec, "content", "")) if rec else ""
            category = _classify_category(title, cat_raw, description=body_text)

            # 严格时区保证为 aware UTC
            if start_at is not None:
                start_at = _aware_utc(start_at)
            if end_at is not None:
                end_at = _aware_utc(end_at)

            start_prec = TimePrecision.EXACT.value if start_at else TimePrecision.UNKNOWN.value
            end_prec = TimePrecision.EXACT.value if end_at else TimePrecision.UNKNOWN.value

            # 基于正文 body 和标题的多维度取消检测
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
                    metadata={
                        "description": str(body_text or ""),
                        "tag": str(cat_raw or ""),
                        "activity_kind": "official_deadline",
                    },
                    version=1,
                )
                apply_display_relevance(event)
                events.append(event)
            except Exception as exc:
                logger.debug("[NIKKE] 官方日程条目构造跳过: %s", safe_exception_message(exc))

        return FetchResult(
            outcome=FetchOutcome.SUCCESS_DATA if events else FetchOutcome.SUCCESS_EMPTY,
            events=events,
            source=self.source_name,
            response_mode=self.response_mode,
            diagnostics=diagnostics,
        )


class ManualOverrideScheduleAdapter(BaseScheduleAdapter):
    """手动配置覆盖适配器。"""

    def __init__(self, config_path: Path | str | None = None):
        self.config_path = Path(config_path) if config_path else None

    @property
    def source_name(self) -> str:
        return "manual"

    @property
    def source_role(self) -> SourceRole:
        return SourceRole.LOCAL_OVERRIDE

    @property
    def contributes_to_freshness(self) -> bool:
        return False

    @property
    def required_for_complete(self) -> bool:
        return False

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
