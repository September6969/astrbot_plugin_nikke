"""联盟突袭查询用例及其账号、数据网关与时钟端口。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .query import RaidQueryMixin
from .models import RaidState, UnionRaidOverviewData


DISPLAY_TIMEZONE = timezone(timedelta(hours=8))


class RaidAccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取当前 QQ 绑定的游戏账号。"""


class RaidGateway(Protocol):
    async def get_union_raid_dashboard(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        """共享联盟身份返回 Boss、攻击数据及局部失败标记。"""

    async def get_union_raid_season(
        self,
        account: Mapping[str, Any],
        *,
        guild_id: str,
        season_id: str,
        levels: bool = False,
    ) -> Mapping[str, Any]:
        """读取显式赛季 ID 的历史突袭数据。"""


class RaidBuilderPort(Protocol):
    def build(
        self,
        *,
        guild_name: str,
        level_info_payload: Mapping[str, Any],
        fetched_at: str,
        plugin_version: str,
        now: datetime,
    ) -> UnionRaidOverviewData:
        """将当前响应映射为概览 DTO。"""

    def resolve_response_state(self, payload: Any, *, now: datetime) -> RaidState:
        """使用指定时钟解析响应对应的突袭状态。"""

    def latest_completed_season_id(self, *, now: datetime) -> str | None:
        """返回当前时钟之前最近结束赛季的显式 ID。"""


class RaidApplication(RaidQueryMixin):
    def __init__(
        self,
        *,
        account_reader: RaidAccountReader,
        gateway: RaidGateway,
        builder: RaidBuilderPort,
        clock: Callable[[], datetime],
        plugin_version: str,
        task_factory=None,
    ) -> None:
        self._account_reader = account_reader
        self._gateway = gateway
        self._builder = builder
        self._clock = clock
        self._plugin_version = plugin_version
        self._task_factory = task_factory
        self._init_query_cache()

    def _account(self, qq_id: str) -> Mapping[str, Any]:
        account = self._account_reader.get_account(str(qq_id))
        if not account:
            self.invalidate(qq_id)
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        return account

    def _query_time(self) -> datetime:
        current = self._clock()
        if not isinstance(current, datetime):
            raise TypeError("突袭查询时钟必须返回 datetime")
        if current.tzinfo is None:
            current = current.replace(tzinfo=DISPLAY_TIMEZONE)
        return current.astimezone(DISPLAY_TIMEZONE)
