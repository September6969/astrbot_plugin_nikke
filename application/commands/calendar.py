# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 查询与显式刷新命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ...features.calendar.application import (
    CalendarRefreshResult,
    CalendarScheduleSnapshot,
)
from .contracts import CommandContext, CommandResult, ImageReply, TextReply


class CalendarApplicationPort(Protocol):
    """Calendar 查询与刷新应用端口。"""

    def query_schedule(self, horizon: str) -> CalendarScheduleSnapshot:
        """读取本地快照，不执行网络刷新。"""

    async def refresh_schedule(self) -> CalendarRefreshResult:
        """显式刷新公开日程数据。"""


class CalendarPayloadBuilder(Protocol):
    """构造 Operations Feed 页面 payload。"""

    def build(self, snapshot: CalendarScheduleSnapshot) -> Mapping[str, Any]:
        """从同一次冻结快照构造分页展示数据。"""


CalendarRenderer = Callable[[Mapping[str, Any]], Awaitable[Any]]
CalendarRefreshScheduler = Callable[[], Any]


class CalendarCommandHandler:
    """封装 Calendar 查询、刷新、T2I 与本地文本回退。"""

    _REFRESH_WORDS = {"刷新", "refresh", "rescan"}

    def __init__(
        self,
        *,
        application: CalendarApplicationPort,
        payload_builder: CalendarPayloadBuilder,
        render: CalendarRenderer,
        start_background_refresh: CalendarRefreshScheduler,
    ) -> None:
        self._application = application
        self._payload_builder = payload_builder
        self._render = render
        self._start_background_refresh = start_background_refresh

    async def handle(self, context: CommandContext) -> CommandResult:
        """按只读热查询、尚无快照或显式刷新分派。"""
        horizon = context.parameters.get("horizon", "").strip()
        if horizon.casefold() in self._REFRESH_WORDS:
            result = await self._application.refresh_schedule()
            return self._text(self._refresh_message(result))

        try:
            snapshot = self._application.query_schedule(horizon)
        except ValueError as exc:
            return self._text(
                f"日程范围错误：{exc}\n用法：/妮姬 日程 [7|14|30] 或 /妮姬 日程 刷新"
            )
        if not snapshot.service_available:
            return self._text("日程服务尚未就绪，正在后台同步，请稍后重试。")
        if not snapshot.has_snapshot:
            self._start_background_refresh()
            return self._text("日程数据尚未就绪，正在后台同步，请稍后重试。")

        payload = self._payload_builder.build(snapshot)
        rendered = await self._render(payload)
        if isinstance(rendered, (list, tuple)):
            replies = tuple(ImageReply(path) for path in rendered if path)
            if replies:
                return CommandResult(replies)
        elif rendered:
            return CommandResult((ImageReply(rendered),))
        return self._text(str(payload.get("fallback_text", snapshot.fallback_text)))

    @staticmethod
    def _refresh_message(result: CalendarRefreshResult) -> str:
        state = "成功" if result.success else "失败（已保留旧快照）"
        suffix = f"，提示：{result.message}" if result.message != "ok" else ""
        return (
            f"【NIKKE 日程】数据刷新完成：{state} ({result.data_quality})\n"
            f"当前活动条目数：{result.activity_count}{suffix}"
        )

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
