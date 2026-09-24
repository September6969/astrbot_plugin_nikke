"""战役历史查询用例及其账号、网关、时钟端口。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from .builder import CampaignHistoryBuilder
from .models import StageClearRecord
from .stage_resolver import CampaignStage, CampaignStageResolver


DISPLAY_TIMEZONE = timezone(timedelta(hours=8))


class CampaignAccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取战役查询所需账号及凭据。"""


class CampaignGateway(Protocol):
    async def get_main_quest_clear_lineup(
        self,
        account: Mapping[str, Any],
        stage_id: int,
        area_id: int | str,
    ) -> Mapping[str, Any]:
        """读取指定账号、关卡与服务器的历史通关阵容。"""


class CampaignRecordBuilder(Protocol):
    def update_directory(self, directory: list[dict]) -> None:
        """更新角色目录，以丰富历史阵容成员信息。"""

    def build(
        self,
        *,
        stage: CampaignStage,
        response: Mapping[str, Any],
        commander_name: str = "",
        fetched_at: str = "",
        plugin_version: str = "",
    ) -> StageClearRecord:
        """将上游响应转换为战役历史记录 DTO。"""


class CampaignApplication:
    def __init__(
        self,
        *,
        resolver: CampaignStageResolver,
        gateway: CampaignGateway,
        account_reader: CampaignAccountReader,
        builder: CampaignRecordBuilder | CampaignHistoryBuilder,
        clock: Callable[[], datetime],
        plugin_version: str,
    ) -> None:
        self._resolver = resolver
        self._gateway = gateway
        self._account_reader = account_reader
        self._builder = builder
        self._clock = clock
        self._plugin_version = plugin_version

    def resolve(self, query: str) -> CampaignStage | None:
        return self._resolver.resolve_query(query)

    def update_directory(self, directory: list[dict]) -> None:
        self._builder.update_directory(directory)

    async def lookup(
        self, qq_id: str, stage: CampaignStage
    ) -> StageClearRecord:
        account = self._account_reader.get_account(str(qq_id))
        if not account:
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")

        response = await self._gateway.get_main_quest_clear_lineup(
            account,
            stage_id=stage.stage_id,
            area_id=account.get("area_id", 0),
        )
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=DISPLAY_TIMEZONE)
        fetched_at = now.astimezone(DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M")
        return self._builder.build(
            stage=stage,
            response=response,
            commander_name=account.get("nickname") or account.get("role_name") or "指挥官",
            fetched_at=fetched_at,
            plugin_version=self._plugin_version,
        )
