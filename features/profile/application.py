# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile 用例边界，只编排网关、构建器和显示时钟。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .models import ProfileDashboardData


DISPLAY_TIMEZONE = timezone(timedelta(hours=8))
ProfileClock = Callable[[], datetime]


class ProfileDashboardGateway(Protocol):
    """读取一次 Profile dashboard 的最小端口。"""

    async def get_profile_dashboard(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        """按账号读取 dashboard；具体 HTTP 错误由调用方观察。"""


class ProfileDashboardBuilder(Protocol):
    """将已采集的原始字段构建为领域 DTO。"""

    def build(
        self,
        *,
        account: Mapping[str, Any],
        basic: Mapping[str, Any],
        outpost: Mapping[str, Any],
        roster: list[Any] | None,
        outpost_available: bool | None = None,
        roster_available: bool | None = None,
        daily: Mapping[str, Any] | None = None,
        daily_available: bool | None = None,
        fetched_at: str,
        plugin_version: str,
    ) -> ProfileDashboardData:
        """构建 Profile DTO。"""


class ProfileApplication:
    """Profile 业务用例；不拥有消息、渲染、HTTP 或持久化副作用。"""

    def __init__(
        self,
        *,
        gateway: ProfileDashboardGateway,
        builder: ProfileDashboardBuilder,
        clock: ProfileClock,
        plugin_version: str,
    ) -> None:
        self.gateway = gateway
        self.builder = builder
        self.clock = clock
        self.plugin_version = plugin_version

    async def build_dashboard(self, account: Mapping[str, Any]) -> ProfileDashboardData:
        """单次读取并构建 dashboard，保留既有字段可用性语义。"""
        raw = await self.gateway.get_profile_dashboard(account)
        if not isinstance(raw, Mapping):
            raise TypeError("Profile dashboard 响应必须是对象")

        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=DISPLAY_TIMEZONE)
        fetched_at = now.astimezone(DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        return self.builder.build(
            account=account,
            basic=raw["basic"],
            outpost=raw["outpost"],
            roster=raw["roster"],
            outpost_available=raw.get("outpost_available"),
            roster_available=raw.get("roster_available"),
            daily=raw.get("daily"),
            daily_available=raw.get("daily_available"),
            fetched_at=fetched_at,
            plugin_version=self.plugin_version,
        )
