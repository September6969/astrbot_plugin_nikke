# SPDX-License-Identifier: GPL-3.0-or-later
"""AstrBot 插件入口注入的 handler 与平台适配器集合。"""

from __future__ import annotations

from dataclasses import dataclass

from ...application.commands.account import AccountCommandHandler
from ...application.commands.announcement import AnnouncementCommandHandler
from ...application.commands.cdk import CdkCommandHandler
from ...application.commands.calendar import CalendarCommandHandler
from ...application.commands.daily import DailyCommandHandler
from ...application.commands.guide import GuideCommandHandler
from ...application.commands.profile import ProfileCommandHandler
from ...application.commands.tarot import TarotCommandHandler
from ...application.commands.tower import TowerCommandHandler
from .command_adapter import AstrBotCommandAdapter
from .voice_adapter import AstrBotVoiceAdapter


@dataclass
class PluginCommandHandlers:
    """插件入口持有的全部框架无关命令处理器。"""

    account: AccountCommandHandler | None = None
    announcement: AnnouncementCommandHandler | None = None
    cdk: CdkCommandHandler | None = None
    calendar: CalendarCommandHandler | None = None
    daily: DailyCommandHandler | None = None
    guide: GuideCommandHandler | None = None
    profile: ProfileCommandHandler | None = None
    tarot: TarotCommandHandler | None = None
    tower: TowerCommandHandler | None = None


@dataclass
class AstrBotAdapterCollection:
    """统一注入给入口的宿主命令与语音适配器。"""

    command: AstrBotCommandAdapter | None = None
    voice: AstrBotVoiceAdapter | None = None
