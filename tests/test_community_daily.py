"""社区日常的脱敏接口合同与持久化状态回归。"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.daily.models import DailyTaskStatus
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, BlaBlaError, CookieExpired
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext

ACCOUNT = {"qq_id": "123", "game_uid": "uid", "platform": "global", "area_id": "3", "auto_daily_enabled": 1}


class Store:
    def __init__(self):
        self.runs = {}
        self.settings = {}
        self.account = dict(ACCOUNT)

    def claim_run(self, key, actor, action, initial_status):
        if key in self.runs:
            return False
        self.runs[key] = {"status": initial_status}
        return True

    def get_run(self, key):
        return self.runs.get(key)

    def finish_run(self, key, status, detail):
        self.runs[key] = {"status": status, "detail": detail}

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def get_account(self, actor, with_cookie=True):
        return self.account

    def set_auto_daily(self, actor, enabled):
        self.account["auto_daily_enabled"] = enabled

    def mark_cookie_invalid(self, actor):
        self.account["cookie_valid"] = False

    def list_accounts(self, **kwargs):
        assert kwargs["push_only"] is False
        return [self.account] if self.account["auto_daily_enabled"] else []


def reward(state="claimable", identifier="1"):
    return {"id": identifier, "period": "onboarding-v1", "name": "免费奖励", "state": state}


def setup():
    store = Store()
    client = AsyncMock()
    client.get_daily_signin.return_value = {"found": True, "completed": True}
    client.get_community_rewards.side_effect = [[reward()], [reward("claimed")]]
    runner = DailyRunner(client, store, {"enable_daily_actions": True})
    return store, client, runner


@pytest.mark.asyncio
async def test_reward_after_existing_signin_and_next_day_not_replayed():
    store, client, runner = setup()
    result = await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    assert result.status == DailyTaskStatus.SUCCESS and len(result.items) == 2
    client.perform_daily_signin.assert_not_awaited()
    client.get_community_rewards.side_effect = None
    client.get_community_rewards.return_value = [reward("claimed"), reward("pending", "2")]
    restarted = DailyRunner(client, store, {"enable_daily_actions": True})
    await restarted.run_community_for_account(ACCOUNT, "2026-10-14")
    client.claim_community_reward.assert_awaited_once_with(ACCOUNT, "1")


@pytest.mark.asyncio
async def test_new_reward_same_day_and_concurrent_signin_share_lock():
    store, client, runner = setup()
    await asyncio.gather(runner.run_community_for_account(ACCOUNT, "2026-10-13"),
                         runner.run_daily_for_account(ACCOUNT, "2026-10-13"))
    client.get_community_rewards.side_effect = [[reward("claimable", "2")], [reward("claimed", "2")]]
    await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    assert client.claim_community_reward.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), CookieExpired("expired")])
async def test_unknown_or_expired_stops_batch_and_restart_never_resubmits(failure):
    store, client, runner = setup()
    client.claim_community_reward.side_effect = failure
    client.get_community_rewards.side_effect = None
    client.get_community_rewards.return_value = [reward(), reward("claimable", "2")]
    first = await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    assert first.status in {DailyTaskStatus.UNKNOWN_AFTER_ACTION, DailyTaskStatus.COOKIE_EXPIRED}
    client.claim_community_reward.assert_awaited_once()
    restarted = DailyRunner(client, store, {"enable_daily_actions": True})
    await restarted.run_community_for_account(ACCOUNT, "2026-10-14")
    client.claim_community_reward.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_can_be_confirmed_by_read():
    store, client, runner = setup()
    client.claim_community_reward.side_effect = TimeoutError()
    assert (await runner.run_community_for_account(ACCOUNT, "2026-10-13")).status == DailyTaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_cancellation_persists_intent_and_does_not_erase_success():
    store, client, runner = setup()
    client.claim_community_reward.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    key = runner.daily_run_key("onboarding-v1", ACCOUNT, "reward:1")
    assert store.runs[key]["status"] == "UNKNOWN_AFTER_ACTION"
    assert any(v.get("items") for v in store.settings.values() if isinstance(v, dict))


@pytest.mark.asyncio
async def test_unknown_reward_no_write_and_disabled_global_gate():
    store, client, runner = setup()
    client.get_community_rewards.side_effect = None
    client.get_community_rewards.return_value = [reward("unknown")]
    assert (await runner.run_community_for_account(ACCOUNT, "2026-10-13")).status == DailyTaskStatus.UNAVAILABLE
    client.claim_community_reward.assert_not_awaited()
    runner.config["enable_daily_actions"] = False
    client.get_community_rewards.reset_mock()
    await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    client.get_community_rewards.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_private_route_dedup_and_rebind_guard():
    store, client, runner = setup()
    sender = AsyncMock(return_value=True)
    handler = DailyCommandHandler(account_reader=store, store=store, runner=runner, client=client,
        config={"enable_daily_actions": True}, render_summary=lambda rows: "x", send_summary=AsyncMock(), send_notice=sender)
    await handler.handle(CommandContext(actor_id="123", is_private_chat=True, conversation_id="private:123",
        parameters={"scope": "community", "action": "自动", "value": "开"}))
    client.get_community_rewards.side_effect = None
    client.get_community_rewards.return_value = [reward("unknown")]
    await runner.run_all_daily("2026-10-13", automatic=True)
    await runner.run_all_daily("2026-10-13", automatic=True)
    sender.assert_awaited_once()
    assert sender.await_args.args[0] == "private:123"
    store.account = {**ACCOUNT, "game_uid": "other"}
    await runner.run_all_daily("2026-10-14", automatic=True)
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_auto_scope_never_claims_rewards():
    store, client, runner = setup()
    await runner.run_all_daily("2026-10-13", automatic=True)
    client.get_community_rewards.assert_not_awaited()
    client.claim_community_reward.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("states", [[True, True], [False, False], [True, False], ["false"], [None], []])
async def test_signin_parses_all_rewards_strictly(states):
    client = BlaBlaClient()
    client.get_community_tasks = AsyncMock(return_value=[{"task_type": 1, "task_id": "s", "task_name": "每日签到",
        "reward_infos": [{"is_completed": state} for state in states]}])
    if states in ([True, True], [False, False]):
        assert (await client.get_daily_signin({}))["completed"] is all(states)
    else:
        with pytest.raises(BlaBlaError):
            await client.get_daily_signin({})
    await client.aclose()


@pytest.mark.asyncio
async def test_official_reward_contract_and_no_cost_endpoint():
    client = BlaBlaClient()
    client._community_request = AsyncMock(return_value={"data": {"mission_done_list": [
        {"tag_id": "1", "mission_status": 1}, {"tag_id": "2", "mission_status": 2},
        {"tag_id": "3", "mission_status": 0}, {"tag_id": "4", "mission_status": True},
        {"tag_id": "99", "mission_status": 1}]}})
    rewards = await client.get_community_rewards({})
    assert [r["state"] for r in rewards] == ["claimable", "claimed", "pending", "unknown", "unknown"]
    await client.claim_community_reward({}, "1")
    assert client._community_request.await_args.args[:2] == ("POST", "/api/game/proxy/Game/OnboardingMissionGiftCollection")
    assert client._community_request.await_args.kwargs["payload"] == {"tag_id": "1"}
    with pytest.raises(BlaBlaError):
        await client.claim_community_reward({}, "99")
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_status", ["success", "UNKNOWN_AFTER_ACTION"])
async def test_beijing_records_do_not_masquerade_as_utc_success(old_status):
    import hashlib
    store, client, runner = setup()
    digest = hashlib.sha256(runner.daily_identity(ACCOUNT).encode()).hexdigest()[:24]
    store.runs[f"2026-10-14:game:{digest}:signin"] = {"status": old_status}
    client.get_daily_signin.return_value = {"found": True, "completed": False}
    result = await runner.run_daily_for_account(ACCOUNT, "2026-10-13")
    if old_status == "success":
        client.perform_daily_signin.assert_awaited_once()
        assert result.status == DailyTaskStatus.SUCCESS
    else:
        client.perform_daily_signin.assert_not_awaited()
        assert result.status == DailyTaskStatus.UNKNOWN_AFTER_ACTION


@pytest.mark.asyncio
async def test_success_is_silent_and_group_context_is_not_private_route():
    store, client, runner = setup()
    sender = AsyncMock()
    handler = DailyCommandHandler(account_reader=store, store=store, runner=runner, client=client,
        config={"enable_daily_actions": True}, render_summary=lambda rows: "x", send_summary=AsyncMock(), send_notice=sender)
    await handler.handle(CommandContext(actor_id="123", conversation_id="group:9",
        parameters={"scope": "community", "action": "自动", "value": "开"}))
    assert "daily_private:123" not in store.settings
    await runner.run_all_daily("2026-10-13", automatic=True)
    sender.assert_not_awaited()
    client.get_community_rewards.side_effect = None
    client.get_community_rewards.return_value = [reward("unknown")]
    await runner.run_all_daily("2026-10-13", automatic=True)
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_catches_up_using_utc_period_once_per_instance():
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
    from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
    coordinator = RuntimeCoordinator()
    run = AsyncMock()
    now = datetime(2026, 10, 14, 1, 30, tzinfo=timezone(timedelta(hours=8)))
    scheduler = RuntimeScheduler(coordinator=coordinator,
        store=SimpleNamespace(get_setting=lambda key, default=None: default),
        config={"daily_hour": 1, "daily_minute": 0, "summary_hour": 8, "summary_minute": 30},
        run_daily=run, send_summary=AsyncMock(), sync_announcements=AsyncMock(),
        sync_calendar=AsyncMock(), dispatch_announcements=AsyncMock(), clock=lambda: now, unix_time=lambda: 0)
    await scheduler.tick()
    await asyncio.sleep(0)
    await scheduler.tick()
    run.assert_awaited_once_with("2026-10-13", stagger=True, automatic=True)
    await coordinator.close()


@pytest.mark.asyncio
async def test_zero_rewards_and_partial_success_are_visible():
    store, client, runner = setup()
    client.get_community_rewards.side_effect = [[], [reward(), reward("claimable", "2")],
        [reward("claimed"), reward("claimable", "2")], RuntimeError("query failed")]
    empty = await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    assert "未返回可领取记录" in empty.detail
    partial = await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    assert partial.items[1]["status"] == "success"
    assert partial.items[2]["status"] == "unknown_after_action"


@pytest.mark.asyncio
async def test_status_keeps_saved_result_when_source_is_unavailable():
    store, client, runner = setup()
    await runner.run_community_for_account(ACCOUNT, "2026-10-13")
    client.get_daily_signin.side_effect = TimeoutError()
    client.get_community_rewards.side_effect = TimeoutError()
    handler = DailyCommandHandler(account_reader=store, store=store, runner=runner, client=client,
        config={}, render_summary=lambda rows: "x", send_summary=AsyncMock())
    result = await handler.handle(CommandContext(actor_id="123", parameters={"scope": "community", "action": "状态"}))
    assert "状态未知" in result.messages[0].text
    assert "领取成功" in result.messages[0].text
    client.claim_community_reward.assert_awaited_once()


@pytest.mark.asyncio
async def test_notice_failure_does_not_discard_automatic_results():
    store, client, runner = setup()
    runner.on_automatic_result = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    results = await runner.run_all_daily("2026-10-13", automatic=True)
    assert len(results) == 1
    assert store.settings["daily_results:2026-10-13:automatic"]
