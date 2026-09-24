"""AstrBot 无关的命令上下文、处理器协议与结果消息。"""

from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, TypeAlias


@dataclass(frozen=True)
class CommandContext:
    platform_name: str = ""
    actor_id: str = ""
    is_admin: bool = False
    is_private_chat: bool = False
    conversation_id: str = ""
    parameters: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TextReply:
    text: str


@dataclass(frozen=True)
class ImageReply:
    path_or_url: str


CommandReply: TypeAlias = TextReply | ImageReply


@dataclass(frozen=True)
class CommandResult:
    messages: tuple[CommandReply, ...] = ()


class CommandHandler(Protocol):
    async def handle(self, context: CommandContext) -> CommandResult:
        ...


class FeedbackHandle(Protocol):
    async def cancel(self) -> None:
        """结束当前命令对应的延迟反馈。"""


CommandFeedbackStarter: TypeAlias = Callable[
    [CommandContext, str], FeedbackHandle | None
]
