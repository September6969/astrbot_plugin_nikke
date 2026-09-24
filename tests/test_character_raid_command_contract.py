# SPDX-License-Identifier: GPL-3.0-or-later
"""Character 与 Raid 命令编排、错误映射和结果回退合同。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.application.commands.raid import RaidCommandHandler
from astrbot_plugin_nikke.features.raid.participants import RaidRankingData, format_ranking
from astrbot_plugin_nikke.integrations.blablalink.client import CookieExpired


class FeedbackHandle:
    def __init__(self) -> None:
        self.cancelled = 0

    async def cancel(self) -> None:
        self.cancelled += 1


@pytest.mark.asyncio
async def test_character_card_request_and_existing_dto_presentation_are_single_path():
    directory = ({"name_code": "5065", "name_cn": "皇冠"},)
    dto = object()
    application = SimpleNamespace()
    requests = []

    async def build_card(request):
        requests.append(request)
        return SimpleNamespace(card=dto)

    application.build_card = build_card
    presented = []
    feedback = FeedbackHandle()
    invalidated = []
    handler = CharacterCommandHandler(
        application=application,
        directory=lambda: directory,
        render_roster=lambda _data: None,
        render_card=lambda card: _image_path(card, presented),
        render_info=lambda _data: None,
        invalidate_cookie=invalidated.append,
        start_feedback=lambda _context, _message: feedback,
    )

    result = await handler.handle(
        CommandContext(
            actor_id="game-user",
            parameters={"operation": "character", "name": "皇冠"},
        )
    )

    assert result.messages[0].path_or_url == "character.png"
    assert len(requests) == 1
    assert requests[0].qq_id == "game-user"
    assert requests[0].query == "皇冠"
    assert requests[0].directory == directory
    assert presented == [dto]
    assert feedback.cancelled == 1
    assert invalidated == []


async def _image_path(card, presented):
    presented.append(card)
    return "character.png"


@pytest.mark.asyncio
async def test_character_cookie_expiry_invalidates_once_and_feedback_is_cancelled():
    invalidated = []
    feedback = FeedbackHandle()

    class Application:
        async def build_card(self, _request):
            raise CookieExpired("synthetic expired")

    handler = CharacterCommandHandler(
        application=Application(),
        directory=lambda: (),
        render_roster=lambda _data: None,
        render_card=lambda _data: None,
        render_info=lambda _data: None,
        invalidate_cookie=invalidated.append,
        start_feedback=lambda _context, _message: feedback,
    )
    result = await handler.handle(
        CommandContext(
            actor_id="qq-1",
            parameters={"operation": "character", "name": "拉毗"},
        )
    )

    assert "登录状态已失效" in result.messages[0].text
    assert invalidated == ["qq-1"]
    assert feedback.cancelled == 1


@pytest.mark.asyncio
async def test_raid_ranking_text_fallback_uses_one_fetched_dto():
    dto = RaidRankingData([])
    calls = []
    rendered = []

    class Application:
        async def ranking(self, actor_id):
            calls.append(actor_id)
            return dto

    async def render(page, data):
        rendered.append((page, data))
        return None

    handler = RaidCommandHandler(
        application=Application(),
        render_overview=lambda _data: None,
        render_ranking=render,
        invalidate_cookie=lambda _actor_id: None,
    )
    result = await handler.handle(
        CommandContext(actor_id="qq-2", parameters={"operation": "ranking"})
    )

    assert calls == ["qq-2"]
    assert rendered == [("union_records", dto)]
    assert result.messages[0].text == format_ranking(dto)


@pytest.mark.asyncio
async def test_raid_overview_delayed_feedback_is_cancelled_after_presentation():
    dto = object()
    feedback = FeedbackHandle()
    presented = []

    class Application:
        async def overview(self, actor_id):
            assert actor_id == "qq-3"
            return dto

    async def render(data):
        presented.append(data)
        return "raid.png"

    handler = RaidCommandHandler(
        application=Application(),
        render_overview=render,
        render_ranking=lambda _page, _data: None,
        invalidate_cookie=lambda _actor_id: None,
        start_feedback=lambda _context, _message: feedback,
    )
    result = await handler.handle(CommandContext(actor_id="qq-3"))

    assert result.messages[0].path_or_url == "raid.png"
    assert presented == [dto]
    assert feedback.cancelled == 1


@pytest.mark.asyncio
async def test_raid_cookie_expiry_invalidates_and_unknown_member_is_not_guessed():
    invalidated = []

    class ExpiredApplication:
        async def overview(self, _actor_id):
            raise CookieExpired("synthetic expired")

    expired = RaidCommandHandler(
        application=ExpiredApplication(),
        render_overview=lambda _data: None,
        render_ranking=lambda _page, _data: None,
        invalidate_cookie=invalidated.append,
    )
    result = await expired.handle(CommandContext(actor_id="qq-4"))
    assert "登录状态已失效" in result.messages[0].text
    assert invalidated == ["qq-4"]
