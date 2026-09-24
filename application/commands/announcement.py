# SPDX-License-Identifier: GPL-3.0-or-later
"""公告查看、订阅和公开重扫命令处理器。"""

from __future__ import annotations

from collections.abc import Callable

from ...features.announcement.application import AnnouncementApplication
from .contracts import CommandContext, CommandResult, TextReply


class AnnouncementCommandHandler:
    """统一公告操作的权限、输入边界和用户提示。"""

    def __init__(
        self,
        *,
        application: AnnouncementApplication,
        push_enabled: Callable[[], bool],
    ) -> None:
        self._application = application
        self._push_enabled = push_enabled

    async def handle(self, context: CommandContext) -> CommandResult:
        """处理只读查看、管理员重扫和当前会话订阅。"""
        operation = context.parameters.get("operation", "view").strip().casefold()
        if operation == "view":
            try:
                text = await self._application.view_announcements(
                    locale=context.parameters.get("locale") or None,
                    category=context.parameters.get("category") or None,
                    query=context.parameters.get("query") or None,
                )
            except ValueError as exc:
                text = f"公告查询参数无效：{exc}"
            return self._text(text)
        if operation == "deep_rescan":
            if not context.is_admin:
                return self._text("仅机器人管理员可执行公告深度刷新。")
            result = await self._application.deep_rescan(
                context.parameters.get("locale", "en")
            )
            return self._text(result.message)
        if operation in {"subscribe", "unsubscribe"}:
            if not context.is_admin:
                return self._text("仅机器人管理员可管理公告订阅。")
            target = context.parameters.get("target", "")
            if not target:
                return self._text("当前适配器未提供可持久化会话目标。")
            enabled = operation == "subscribe"
            try:
                self._application.set_subscription(target, enabled=enabled)
            except ValueError as exc:
                return self._text(str(exc))
            if not enabled:
                return self._text("已取消当前会话的公告订阅。")
            suffix = (
                ""
                if self._push_enabled()
                else " 全局推送开关当前关闭，不会自动发送。"
            )
            return self._text(
                "已订阅当前会话；不补发已有公告，截止提醒为 24/6/1 小时。"
                + suffix
            )
        if operation == "unsupported":
            return self._text("公告命令已简化，请使用：\n\n/妮姬 公告")
        return self._text("未知公告操作。")

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))
