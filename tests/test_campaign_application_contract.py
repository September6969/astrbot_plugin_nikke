from datetime import datetime, timezone
from pathlib import Path

import pytest

from astrbot_plugin_nikke.application.commands.campaign import CampaignCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    ImageReply,
    TextReply,
)
from astrbot_plugin_nikke.features.campaign.builder import CampaignHistoryBuilder
from astrbot_plugin_nikke.features.campaign.models import ClearLineupStatus
from astrbot_plugin_nikke.features.campaign.stage_resolver import CampaignStageResolver
from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired
from astrbot_plugin_nikke.features.campaign.application import CampaignApplication


class AccountReader:
    def __init__(self) -> None:
        self.account = {"area_id": 7, "nickname": "指挥官"}
        self.calls: list[str] = []

    def get_account(self, qq_id: str):
        assert qq_id == "qq-123"
        self.calls.append(qq_id)
        return self.account


class CampaignGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, int, int]] = []

    async def get_main_quest_clear_lineup(
        self, account: dict, *, stage_id: int, area_id: int
    ) -> dict:
        self.calls.append((account, stage_id, area_id))
        return {"code": 1300017, "msg": "no historical lineup"}


class ExpiredCampaignGateway:
    async def get_main_quest_clear_lineup(self, account, *, stage_id, area_id):
        raise CookieExpired("expired", "300001", "GetMainQuestClearLineup")


class FeedbackHandle:
    def __init__(self) -> None:
        self.cancelled = False

    async def cancel(self) -> None:
        self.cancelled = True


@pytest.mark.asyncio
async def test_campaign_lookup_uses_injected_account_gateway_and_clock() -> None:
    root = Path(__file__).resolve().parents[1]
    gateway = CampaignGateway()
    account_reader = AccountReader()
    resolver = CampaignStageResolver.from_file(root / "assets" / "campaign_stages.json")
    stage = resolver.resolve_query("46-40")
    assert stage is not None
    application = CampaignApplication(
        resolver=resolver,
        gateway=gateway,
        account_reader=account_reader,
        builder=CampaignHistoryBuilder(),
        clock=lambda: datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )

    resolved_stage = application.resolve("46-40")
    assert resolved_stage == stage
    record = await application.lookup("qq-123", resolved_stage)

    assert record is not None
    assert record.status is ClearLineupStatus.UNAVAILABLE
    assert record.fetched_at == "2026-09-22 18:00"
    assert record.plugin_version == "test-version"
    assert gateway.calls == [(account_reader.account, stage.stage_id, 7)]


@pytest.mark.asyncio
async def test_campaign_command_presents_record_and_cancels_delayed_feedback() -> None:
    root = Path(__file__).resolve().parents[1]
    application = CampaignApplication(
        resolver=CampaignStageResolver.from_file(root / "assets" / "campaign_stages.json"),
        gateway=CampaignGateway(),
        account_reader=AccountReader(),
        builder=CampaignHistoryBuilder(),
        clock=lambda: datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )
    feedback = FeedbackHandle()
    presented = []

    async def present(record) -> str:
        presented.append(record)
        return "campaign.png"

    handler = CampaignCommandHandler(
        application=application,
        present=present,
        invalidate_cookie=lambda _: None,
        start_feedback=lambda: feedback,
    )

    result = await handler.handle(
        CommandContext(
            actor_id="qq-123",
            parameters={"stage": "46-40", "mode": ""},
        )
    )

    assert result.messages == (ImageReply("campaign.png"),)
    assert presented[0].status is ClearLineupStatus.UNAVAILABLE
    assert feedback.cancelled


@pytest.mark.asyncio
async def test_unknown_campaign_stage_does_not_start_feedback_or_read_account() -> None:
    root = Path(__file__).resolve().parents[1]
    account_reader = AccountReader()
    application = CampaignApplication(
        resolver=CampaignStageResolver.from_file(root / "assets" / "campaign_stages.json"),
        gateway=CampaignGateway(),
        account_reader=account_reader,
        builder=CampaignHistoryBuilder(),
        clock=lambda: datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )
    feedback_calls = []
    handler = CampaignCommandHandler(
        application=application,
        present=lambda _: pytest.fail("未知关卡不能渲染"),
        invalidate_cookie=lambda _: None,
        start_feedback=lambda: feedback_calls.append("started"),
    )

    result = await handler.handle(
        CommandContext(actor_id="qq-123", parameters={"stage": "999-999"})
    )

    assert isinstance(result.messages[0], TextReply)
    assert "未找到关卡：999-999" in result.messages[0].text
    assert account_reader.calls == []
    assert feedback_calls == []


@pytest.mark.asyncio
async def test_expired_campaign_cookie_is_invalidated_and_reported() -> None:
    root = Path(__file__).resolve().parents[1]
    application = CampaignApplication(
        resolver=CampaignStageResolver.from_file(root / "assets" / "campaign_stages.json"),
        gateway=ExpiredCampaignGateway(),
        account_reader=AccountReader(),
        builder=CampaignHistoryBuilder(),
        clock=lambda: datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc),
        plugin_version="test-version",
    )
    invalidated: list[str] = []
    handler = CampaignCommandHandler(
        application=application,
        present=lambda _: pytest.fail("Cookie 失效后不能渲染"),
        invalidate_cookie=invalidated.append,
    )

    result = await handler.handle(
        CommandContext(actor_id="qq-123", parameters={"stage": "46-40"})
    )

    assert result.messages == (
        TextReply("登录状态已失效，请重新发送 /妮姬 账号 绑定。"),
    )
    assert invalidated == ["qq-123"]
