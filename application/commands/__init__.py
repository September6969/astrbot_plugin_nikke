"""命令用例共享协议与结果类型。"""

from .contracts import (
    CommandContext,
    CommandFeedbackStarter,
    CommandHandler,
    CommandResult,
    FeedbackHandle,
    ImageReply,
    TextReply,
)
from .cdk import CdkCommandHandler
from .calendar import CalendarCommandHandler
from .campaign import CampaignCommandHandler
from .character import CharacterCommandHandler
from .announcement import AnnouncementCommandHandler
from .daily import DailyCommandHandler
from .profile import ProfileCommandHandler
from .raid import RaidCommandHandler

__all__ = [
    "CommandContext",
    "CommandFeedbackStarter",
    "CommandHandler",
    "CommandResult",
    "FeedbackHandle",
    "ImageReply",
    "TextReply",
    "CdkCommandHandler",
    "CalendarCommandHandler",
    "CampaignCommandHandler",
    "CharacterCommandHandler",
    "AnnouncementCommandHandler",
    "DailyCommandHandler",
    "ProfileCommandHandler",
    "RaidCommandHandler",
]
