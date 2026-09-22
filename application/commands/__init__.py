"""命令用例共享协议与结果类型。"""

from .contracts import (
    CommandContext,
    CommandHandler,
    CommandResult,
    ImageReply,
    TextReply,
)
from .profile import ProfileCommandHandler

__all__ = [
    "CommandContext",
    "CommandHandler",
    "CommandResult",
    "ImageReply",
    "TextReply",
    "ProfileCommandHandler",
]
