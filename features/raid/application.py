"""联盟突袭查询用例及其账号、数据网关与时钟端口。"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .models import RaidState, UnionRaidOverviewData
from .participants import RaidRankingData, build_member_ranking, build_ranking


_LOGGER = logging.getLogger(__name__)


DISPLAY_TIMEZONE = timezone(timedelta(hours=8))


class RaidMemberIdentityUnavailable(ValueError):
    """当前账号没有可用于精确筛选的稳定联盟身份。"""


class RaidAccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取当前 QQ 绑定的游戏账号。"""


class RaidGateway(Protocol):
    async def get_union_raid_overview(
        self, account: Mapping[str, Any], *, attacks: bool = False
    ) -> Mapping[str, Any]:
        """读取联盟突袭概览；攻击记录通过显式参数选择。"""

    async def get_union_raid_snapshot(
        self, account: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """一次读取联盟身份与当前攻击响应。"""

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


class RaidApplication:
    def __init__(
        self,
        *,
        account_reader: RaidAccountReader,
        gateway: RaidGateway,
        builder: RaidBuilderPort,
        clock: Callable[[], datetime],
        plugin_version: str,
    ) -> None:
        self._account_reader = account_reader
        self._gateway = gateway
        self._builder = builder
        self._clock = clock
        self._plugin_version = plugin_version

    def _account(self, qq_id: str) -> Mapping[str, Any]:
        account = self._account_reader.get_account(str(qq_id))
        if not account:
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        return account

    def _query_time(self) -> datetime:
        current = self._clock()
        if not isinstance(current, datetime):
            raise TypeError("突袭查询时钟必须返回 datetime")
        if current.tzinfo is None:
            current = current.replace(tzinfo=DISPLAY_TIMEZONE)
        return current.astimezone(DISPLAY_TIMEZONE)

    async def overview(self, qq_id: str) -> UnionRaidOverviewData:
        account = self._account(qq_id)
        response = await self._gateway.get_union_raid_overview(account)
        current = self._query_time()
        data = self._builder.build(
            guild_name=str(response["guild_name"]),
            level_info_payload=response["level_info"],
            fetched_at=current.strftime("%Y-%m-%d %H:%M"),
            plugin_version=self._plugin_version,
            now=current,
        )
        previous = data.previous_season
        guild_id = response.get("guild_id")
        if (
            data.raid_state is RaidState.OFFSEASON
            and previous is not None
            and previous.season_id
            and guild_id
        ):
            try:
                historical = await self._gateway.get_union_raid_season(
                    account,
                    guild_id=str(guild_id),
                    season_id=str(previous.season_id),
                    levels=False,
                )
                attacks = historical.get("participate_data")
                if isinstance(attacks, list):
                    total_damage = sum(
                        int(item.get("total_damage", 0) or item.get("damage", 0) or 0)
                        for item in attacks
                    )
                    data.previous_season = replace(
                        previous,
                        total_attacks=len(attacks),
                        total_damage=total_damage,
                    )
            except Exception as exc:
                _LOGGER.warning("[NIKKE] 获取上一赛季突袭数据失败: %s", exc)
        return data

    async def ranking(self, qq_id: str) -> RaidRankingData:
        account = self._account(qq_id)
        snapshot = await self._gateway.get_union_raid_snapshot(account)
        payload = snapshot["level_info"]
        current = self._query_time()
        historical = await self._previous_season_attacks(
            account, payload, current, snapshot.get("guild_id")
        )
        if historical is not None:
            season_id, payload = historical
            data = build_ranking(payload)
            season_number = int(season_id) % 1000000 if season_id.isdigit() else season_id
            data.scope = f"第 {season_number} 季 · LAST_SEASON_RESPONSE"
            return data
        return build_ranking(payload)

    async def member(self, qq_id: str) -> RaidRankingData:
        account = self._account(qq_id)
        member_openid = str(account.get("game_openid") or "").strip()
        if not member_openid:
            raise RaidMemberIdentityUnavailable(
                "当前账号缺少稳定联盟身份，暂不能安全筛选个人记录。"
            )

        snapshot = await self._gateway.get_union_raid_snapshot(account)
        payload = snapshot["level_info"]
        current = self._query_time()
        historical = await self._previous_season_attacks(
            account, payload, current, snapshot.get("guild_id")
        )
        if historical is not None:
            _, payload = historical
        return build_member_ranking(payload, member_openid)

    async def _previous_season_attacks(
        self,
        account: Mapping[str, Any],
        payload: Mapping[str, Any],
        now: datetime,
        guild_id: Any,
    ) -> tuple[str, Mapping[str, Any]] | None:
        attacks = payload.get("participate_data")
        if not isinstance(attacks, list) or attacks:
            return None
        if self._builder.resolve_response_state(payload, now=now) is not RaidState.OFFSEASON:
            return None
        season_id = self._builder.latest_completed_season_id(now=now)
        if not season_id:
            return None

        if not guild_id:
            return None
        try:
            historical = await self._gateway.get_union_raid_season(
                account,
                guild_id=str(guild_id),
                season_id=season_id,
                levels=False,
            )
            historical_attacks = historical.get("participate_data")
            if isinstance(historical_attacks, list) and historical_attacks:
                return season_id, historical
        except Exception as exc:
            _LOGGER.warning("[NIKKE] 获取上一赛季突袭攻击记录失败: %s", exc)
        return None
