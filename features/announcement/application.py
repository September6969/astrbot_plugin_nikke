# SPDX-License-Identifier: GPL-3.0-or-later
"""公告查询与投递操作的唯一应用边界。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from astrbot_plugin_nikke.core.privacy import safe_exception_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AnnouncementOperationResult:
    """只读公告源操作的状态和可展示提示。"""

    success: bool
    message: str


@dataclass(frozen=True, slots=True)
class AnnouncementDispatchResult:
    """一次投递批次的稳定汇总，不暴露目标或公告正文。"""

    succeeded: int
    failed: int
    unknown: int


class AnnouncementApplication:
    """集中编排公告缓存、订阅与投递状态机；仅支持单进程单实例。"""

    SINGLE_INSTANCE_ONLY = True
    EXECUTION_SCOPE = "one plugin instance; no cross-process dispatch lock"

    def __init__(
        self,
        *,
        announcements: Any,
        delivery: Any,
        deadline_selector: Callable[[list[Any]], list[Any]] | None = None,
    ) -> None:
        self._announcements = announcements
        self._delivery = delivery
        self._deadline_selector = deadline_selector or (lambda deadlines: deadlines)

    async def sync_announcements(self) -> tuple[bool, str]:
        """同步公开公告源，供启动和定时刷新使用。"""
        return await self._announcements.sync_from_source()

    async def dispatch_pushes(
        self,
        sender: Callable[[str, str], Any],
        *,
        now: datetime | None = None,
    ) -> AnnouncementDispatchResult:
        """由应用唯一编排内容、提醒和持久化投递状态机。"""
        records = self._announcements.list_announcements(limit=10000)
        fallback_deadlines = self._announcements.list_active_deadlines()
        deadlines = self._deadline_selector(fallback_deadlines)
        result = await self._delivery.dispatch(
            records,
            deadlines,
            sender,
            now=now,
        )
        summary = AnnouncementDispatchResult(
            succeeded=int(result.get("succeeded", 0)),
            failed=int(result.get("failed", 0)),
            unknown=int(result.get("unknown", 0)),
        )
        if summary.unknown:
            logger.warning(
                "公告投递结果未知 %s 条；未自动重放，需按受控流程对账。",
                summary.unknown,
            )
        return summary

    def diagnostic_text(self) -> str:
        """返回公告缓存的脱敏、只读诊断。"""
        return self._announcements.format_diagnostic_text()

    async def deep_rescan(self, locale: str = "en") -> AnnouncementOperationResult:
        """有界地重扫公开公告源；此操作不会调用投递状态机。"""
        try:
            selected_locale = self._announcements.normalize_locale(locale)
        except ValueError as exc:
            return AnnouncementOperationResult(False, f"公告语言无效：{exc}")
        try:
            success, message = await asyncio.wait_for(
                self._announcements.sync_from_source(
                    locale=selected_locale,
                    deep=True,
                ),
                timeout=40.0,
            )
        except asyncio.TimeoutError:
            return AnnouncementOperationResult(
                False, "公告深度刷新超时，已保留原有缓存。"
            )
        except Exception as exc:
            return AnnouncementOperationResult(
                False,
                f"公告深度刷新异常：{safe_exception_message(exc)}",
            )
        if success:
            message += " 仅执行公开只读同步，未发送消息。"
        return AnnouncementOperationResult(bool(success), message)

    def set_subscription(self, target: str, *, enabled: bool) -> None:
        """在唯一应用边界内保存当前会话订阅及其公告版本基线。"""
        if not isinstance(target, str) or not target.strip():
            raise ValueError("当前适配器未提供可持久化会话目标")
        if enabled:
            self._delivery.subscribe(
                target,
                self._announcements.list_announcements(limit=10000),
            )
        else:
            self._delivery.unsubscribe(target)

    async def view_announcements(
        self,
        *,
        locale: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> str:
        """查询本地公告；仅缓存为空时尝试有界的首次公开同步。"""
        fallback_error = ""
        if self._announcements.record_count() == 0:
            try:
                success, message = await asyncio.wait_for(
                    self._announcements.sync_from_source(), timeout=4.0
                )
                if not success:
                    fallback_error = message
            except asyncio.TimeoutError:
                fallback_error = "同步公告超时"
            except Exception as exc:
                fallback_error = f"同步异常: {safe_exception_message(exc)}"
        try:
            return self._announcements.format_announcements_text(
                5,
                fallback_error=fallback_error,
                locale=locale,
                category=category,
                query=query,
            )
        except ValueError as exc:
            return f"公告查询参数无效：{exc}"
