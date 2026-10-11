# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar 查询与显式刷新命令用例。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from ...features.calendar.application import (
    CalendarRefreshResult,
    CalendarScheduleSnapshot,
)
from .contracts import CommandContext, CommandResult, ImageReply, TextReply, CommandFeedbackStarter


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
        start_feedback: CommandFeedbackStarter | None = None,
    ) -> None:
        self._start_feedback = start_feedback
        self._application = application
        self._payload_builder = payload_builder
        self._render = render
        self._start_background_refresh = start_background_refresh

    async def handle(self, context: CommandContext) -> CommandResult:
        """按只读热查询、尚无快照或显式刷新分派。"""
        horizon = context.parameters.get("horizon", "").strip()
        if horizon.casefold() in self._REFRESH_WORDS:
            feedback = self._start_feedback(context, "正在刷新日程信息...") if self._start_feedback else None
            try:
                result = await self._application.refresh_schedule()
                return self._text(self._refresh_message(result))
            except Exception:
                return self._text("日程刷新暂不可用，请稍后重试。")
            finally:
                if feedback:
                    await feedback.cancel()

        raw_page = context.parameters.get("page", "").strip() or "1"
        if not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 6 or int(raw_page) < 1:
            return self._text("页码须为正整数；用法：/妮姬 日程 [7|14|30] [页码]")
        page = int(raw_page)
        try:
            snapshot = self._application.query_schedule(horizon)
        except ValueError as exc:
            return self._text(
                f"日程范围错误：{exc}\n用法：/妮姬 日程 [7|14|30] [页码] 或 /妮姬 日程 刷新"
            )
        if not snapshot.service_available:
            return self._text("日程服务尚未就绪，正在后台同步，请稍后重试。")
        if not snapshot.has_snapshot:
            self._start_background_refresh()
            return self._text("日程数据尚未就绪，正在后台同步，请稍后重试。")

        fallback = snapshot.fallback_text
        # 先独立准备本页文字，图片载荷构建失败也不会退回全量长文本。
        if hasattr(snapshot.context, "events"):
            from ...features.calendar.presentation import schedule_pages
            pages = schedule_pages(snapshot)
            if page > len(pages):
                return self._text(f"页码超出范围，共 {len(pages)} 页；用法：/妮姬 日程 {snapshot.horizon_days} [页码]")
            fallback = pages[page - 1]["fallback_text"]
        try:
            payload = self._payload_builder.build(snapshot)
            if payload.get("pages"):
                if page > len(payload["pages"]):
                    return self._text("页码超出范围；用法：/妮姬 日程 [7|14|30] [页码]")
                selected = payload["pages"][page - 1]
                payload = {**payload, **selected, "pages": [selected]}
            fallback = str(payload.get("fallback_text", fallback))
            rendered = await self._render(payload)
        except Exception:
            return self._text(fallback)
        if isinstance(rendered, (list, tuple)):
            replies = tuple(ImageReply(path) for path in rendered if path)
            if replies:
                return CommandResult(replies)
        elif rendered:
            return CommandResult((ImageReply(rendered),))
        return self._text(fallback)

    @staticmethod
    def _refresh_message(result: CalendarRefreshResult) -> str:
        available = result.has_snapshot if result.has_snapshot is not None else result.activity_count > 0
        state = "成功" if result.success else ("失败（已保留旧快照）" if available else "失败（暂无可用快照）")
        suffix = f"，提示：{result.message}" if result.message != "ok" else ""
        return (
            f"【NIKKE 日程】数据刷新完成：{state}\n"
            f"当前活动条目数：{result.activity_count}{suffix}"
        )

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
