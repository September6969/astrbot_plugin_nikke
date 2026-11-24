# SPDX-License-Identifier: GPL-3.0-or-later
"""数据源适配器模块 (Schedule Adapters)。

定义源适配器抽象（BaseScheduleAdapter / FetchResult），并提供本地
ManualOverrideScheduleAdapter（手动配置覆盖，INCREMENTAL）。生产远程源
BlaBlaLink 适配器位于 integrations/calendar/blabla_source.py。

PR-6B（Decision 5 = A）已删除长期停用的 GameKee 与官方公告日程源；
如需恢复只能通过 git revert，不再提供配置开关。
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
    FetchOutcome,
    ResponseMode,
    SourceRole,
    ManualOverride,
)
from ...core.privacy import safe_exception_message

logger = logging.getLogger("nikke.schedule.adapters")


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
    completeness: str = "COMPLETE"


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
