from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.application.commands.contracts import CommandContext, TextReply
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus


class _Store:
    def __init__(self):
        self.settings = {}
        self.auto_daily = []

    def get_account(self, actor_id, with_cookie=True):
        return {"qq_id": actor_id, "game_uid": "game-1", "area_id": "3", "platform": "global"}

    def set_auto_daily(self, actor_id, enabled):
        self.auto_daily.append((actor_id, enabled))
        return True

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)


@pytest.fixture
def daily_handler():
    store = _Store()
    runner = AsyncMock()
    runner.run_daily_for_account.return_value = DailyTaskResult(
        "synthetic-account", DailyTaskStatus.SUCCESS, "签到成功"
    )
    runner.run_all_daily.return_value = []
    client = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=client,
        config={"enable_daily_actions": True},
        render_summary=lambda rows: "summary.png",
        send_summary=AsyncMock(),
        clock=lambda: "2026-09-22",
    )
    return handler, store, runner, client


@pytest.mark.asyncio
async def test_manual_daily_command_delegates_one_account_to_runner(daily_handler):
    handler, _, runner, _ = daily_handler
    result = await handler.handle(CommandContext(actor_id="qq-1", parameters={"action": ""}))
    runner.run_daily_for_account.assert_awaited_once_with(
        {"qq_id": "qq-1", "game_uid": "game-1", "area_id": "3", "platform": "global"},
        "2026-09-22",
    )
    assert result.messages == (TextReply("synthetic-account：签到成功"),)


@pytest.mark.asyncio
async def test_auto_preference_only_changes_local_setting(daily_handler):
    handler, store, runner, _ = daily_handler
    handler._config["enable_daily_actions"] = False
    result = await handler.handle(
        CommandContext(actor_id="qq-1", parameters={"action": "自动", "value": "开"})
    )
    assert store.auto_daily == [("qq-1", True)]
    runner.run_daily_for_account.assert_not_awaited()
    assert "暂不会提交" in result.messages[0].text


@pytest.mark.asyncio
async def test_daily_status_is_read_only(daily_handler):
    handler, _, runner, client = daily_handler
    client.get_profile.return_value = {}
    client.get_daily_signin.return_value = {"found": True, "completed": False}
    result = await handler.handle(
        CommandContext(actor_id="qq-1", parameters={"action": "状态"})
    )
    assert result.messages == (TextReply("今日待签到"),)
    runner.run_daily_for_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_and_automatic_batches_keep_separate_scopes(daily_handler):
    handler, _, runner, _ = daily_handler
    await handler.run_all_daily("2026-09-22")
    await handler.run_all_daily("2026-09-22", stagger=True, automatic=True)
    assert runner.run_all_daily.await_args_list[0].args == ("2026-09-22",)
    assert runner.run_all_daily.await_args_list[1].kwargs == {
        "stagger": True,
        "automatic": True,
    }
