"""个人资料的未知值、认证优先级和图片失败降级回归。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, CookieExpired


def dashboard(**overrides):
    values = dict(account={}, basic={"nickname": "测试指挥官"}, outpost={}, roster=None,
        fetched_at="2026-10-10 12:00", plugin_version="test")
    values.update(overrides)
    return ProfileBuilder().build(**values)


def test_invalid_tower_count_does_not_silently_become_zero():
    data = dashboard(daily_available=True, daily={"tower_daily_info_list": [
        {"type": 1, "is_opened": True, "remaining_count": 2},
        {"type": 2, "is_opened": True, "remaining_count": "bad"},
    ]})
    assert data.tower_daily_remaining is None
    zero = dashboard(daily_available=True, daily={"tower_daily_info_list": [
        {"type": 1, "is_opened": True, "remaining_count": 0}]})
    assert zero.tower_daily_remaining == 0


def test_outpost_failure_marks_its_child_sections_unavailable():
    payload = ProfileT2IPayloadBuilder().build(dashboard(outpost_available=False))
    assert payload["research_state"] == payload["collection_state"] == "UNAVAILABLE"


def test_successful_outpost_does_not_prove_missing_child_fields_available():
    data = dashboard(outpost_available=True)
    data.recycle_room_researches = data.memorial_summary = None
    payload = ProfileT2IPayloadBuilder().build(data)
    assert payload["research_state"] == payload["collection_state"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_auth_expiry_is_not_hidden_by_simultaneous_basic_failure():
    client = object.__new__(BlaBlaClient)
    client._post = AsyncMock(side_effect=[RuntimeError("network"), CookieExpired("expired"), {"data": {}}, {"data": {}}])
    with pytest.raises(CookieExpired):
        await client.get_profile_dashboard({"cookie": "fake", "area_id": "81", "game_openid": "synthetic"})


@pytest.mark.asyncio
async def test_failed_render_returns_same_snapshot_text_without_refetch():
    from astrbot_plugin_nikke.application.commands.profile import ProfileCommandHandler
    from astrbot_plugin_nikke.application.commands.contracts import CommandContext
    data = dashboard(daily_available=True, daily={"intercept_remaining_tickets": 0})
    app = SimpleNamespace(build_dashboard=AsyncMock(return_value=data))
    feedback = SimpleNamespace(cancel=AsyncMock())
    handler = ProfileCommandHandler(account_reader=SimpleNamespace(get_account=lambda _: {"cookie": "fake"}),
        application=app, present=AsyncMock(side_effect=RuntimeError("render failed")),
        start_feedback=lambda *args: feedback)
    result = await handler.handle(CommandContext(actor_id="a"))
    assert "测试指挥官" in result.messages[0].text
    assert "拦截剩余：0" in result.messages[0].text
    assert "咨询剩余：未知" in result.messages[0].text
    app.build_dashboard.assert_awaited_once()
    feedback.cancel.assert_awaited_once()
