"""将无框架命令协议映射为 AstrBot 输入和消息事件结果。"""

from collections.abc import AsyncIterator
from types import MappingProxyType
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ...application.commands.contracts import (
    CommandContext,
    CommandHandler,
    CommandResult,
    ImageReply,
    TextReply,
)


class AstrBotCommandAdapter:
    @staticmethod
    def _event_value(event: AstrMessageEvent, name: str, default: Any) -> Any:
        value = getattr(event, name, None)
        if value is None:
            return default
        return value() if callable(value) else value

    def context_from_event(
        self, event: AstrMessageEvent, **parameters: str
    ) -> CommandContext:
        normalized_parameters = {
            key: "" if value is None else str(value)
            for key, value in parameters.items()
        }
        return CommandContext(
            platform_name=str(self._event_value(event, "get_platform_name", "") or ""),
            actor_id=str(self._event_value(event, "get_sender_id", "") or ""),
            is_admin=bool(self._event_value(event, "is_admin", False)),
            is_private_chat=bool(self._event_value(event, "is_private_chat", False)),
            parameters=MappingProxyType(normalized_parameters),
        )

    async def dispatch(
        self,
        event: AstrMessageEvent,
        handler: CommandHandler,
        **parameters: str,
    ) -> AsyncIterator[Any]:
        context = self.context_from_event(event, **parameters)
        result = await handler.handle(context)
        if not isinstance(result, CommandResult):
            raise TypeError("命令 handler 必须返回 CommandResult")

        for message in result.messages:
            if isinstance(message, TextReply):
                yield event.plain_result(message.text)
            elif isinstance(message, ImageReply):
                yield event.image_result(message.path_or_url)
            else:
                raise TypeError(f"不支持的命令结果消息类型：{type(message).__name__}")
