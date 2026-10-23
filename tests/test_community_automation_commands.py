"""验证独立授权、私聊一次通知、旧调度及实际宿主参数解析。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import inspect

import pytest

from astrbot_plugin_nikke.application.commands.community_automation import CommunityAutomationHandler
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.application.commands.account import AccountCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.daily.action_models import OperationResult, binding_stamp
from astrbot_plugin_nikke.features.account.application import AccountApplication
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot.core.star.filter.command import CommandFilter

from test_session_renewal import bind
from test_command_routing_contract import _plugin_with_recorders, Event


@pytest.fixture
def env(tmp_path):
    store = NikkeStore(tmp_path)
    account = bind(store)
    tasks, renewal = AsyncMock(), AsyncMock()
    tasks.status.return_value = OperationResult("status", "浏览0/5；点赞0/5")
    tasks.execute.return_value = OperationResult("completed", "已完成")
    renewal.execute.return_value = OperationResult("validated", "已验证，期限未证实")
    notice = AsyncMock()
    config = {"enable_daily_actions": True}
    handler = CommunityAutomationHandler(tasks=tasks, renewal=renewal, store=store, config=config,
        send_notice=notice, sleep=AsyncMock(), clock=lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))
    return store, account, tasks, renewal, notice, config, handler


def context(value="状态", *, private=True, action="任务"):
    return CommandContext(actor_id="one", is_private_chat=private,
                          conversation_id="adapter:FriendMessage:one" if private else "adapter:GroupMessage:group",
                          parameters={"action": action, "value": value, "scope": "community", "operation": "account"})


@pytest.mark.asyncio
async def test_new_preferences_are_independent_and_old_daily_scope_unchanged(env):
    store, account, tasks, renewal, notice, config, handler = env
    store.set_auto_daily("one", True)
    await handler.run_automatic()
    tasks.execute.assert_not_awaited()
    renewal.execute.assert_not_awaited()
    await handler.handle_tasks(context("自动 开"))
    assert store.get_setting("session_renewal:auto:one", None) is None
    await handler.run_automatic()
    tasks.execute.assert_awaited_once()
    renewal.execute.assert_not_awaited()
    assert store.get_account("one")["auto_daily_enabled"] == 1
    notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_manual_and_account_renewal_routes_delegate_correctly(env):
    store, _, tasks, renewal, _, config, extra = env
    daily = DailyCommandHandler(account_reader=store, store=store, runner=AsyncMock(), client=AsyncMock(),
        config=config, send_summary=AsyncMock(), extra_automation=extra)
    assert "0/5" in (await daily.handle(context())).messages[0].text
    tasks.execute.assert_not_awaited()
    await daily.handle(context("执行"))
    tasks.execute.assert_awaited_once()
    account = AccountCommandHandler(application=AccountApplication(store), public_base_url="https://example.invalid",
        allow_group_bind=False, runtime_health=lambda: None, render_manual_summary=AsyncMock(), session_handler=extra.handle_renewal)
    await account.handle(context("", action="续期"))
    renewal.execute.assert_awaited_once()
    await account.handle(context("开", action="自动续期"))
    assert store.get_setting("session_renewal:auto:one") == binding_stamp(store.get_account("one"))


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["tasks", "renewal"])
async def test_groups_never_receive_account_progress_or_exceptions(env, capability):
    _, _, tasks, renewal, _, _, handler = env
    result = await (handler.handle_tasks(context("执行", private=False)) if capability == "tasks"
                    else handler.handle_renewal(context("", private=False, action="续期")))
    assert "请私聊" in result.messages[0].text
    tasks.execute.assert_not_awaited()
    renewal.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_notification_once_per_capability_cycle_and_no_route_means_no_send(env):
    store, account, tasks, renewal, notice, _, handler = env
    store.set_setting("community_actions:auto:one", binding_stamp(account))
    tasks.execute.return_value = OperationResult("unknown_after_action", "结果未知")
    await handler.run_automatic()
    notice.assert_not_awaited()
    await handler.handle_tasks(context())
    await handler.run_automatic()
    await handler.run_automatic()
    notice.assert_awaited_once()
    assert notice.await_args.args[0] == "adapter:FriendMessage:one"


@pytest.mark.asyncio
async def test_missing_results_do_not_dispatch_from_group_summary(env):
    store, _, tasks, _, _, config, extra = env
    store.set_setting("summary_group_umo", "adapter:GroupMessage:group")
    daily = DailyCommandHandler(account_reader=store, store=store, runner=AsyncMock(), client=AsyncMock(),
        config=config, send_summary=AsyncMock(), extra_automation=extra)
    await daily.send_automatic_summary("2026-10-22")
    tasks.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_off_or_rebind_after_queue_prevents_automatic_service_call(env):
    store, account, tasks, _, _, _, handler = env
    await handler.handle_tasks(context("自动 开"))
    async def rebind(_): bind(store)
    handler.sleep = rebind
    await handler.run_automatic(stagger=True)
    tasks.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_off_blocks_scheduler_even_with_both_preferences(env):
    store, account, tasks, renewal, _, config, handler = env
    for capability in ("community_actions", "session_renewal"):
        store.set_setting(f"{capability}:auto:one", binding_stamp(account))
    config["enable_daily_actions"] = False
    await handler.run_automatic()
    tasks.execute.assert_not_awaited()
    renewal.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_risk_in_renewal_stops_tasks_and_following_legacy_automatic_writes(env):
    from astrbot_plugin_nikke.features.daily.runner import DailyRunner
    store, account, tasks, renewal, notice, config, handler = env
    for capability in ("community_actions", "session_renewal"):
        store.set_setting(f"{capability}:auto:one", binding_stamp(account))
    await handler.handle_tasks(context())
    renewal.execute.return_value = OperationResult("rate_limited", "请求受到限流")
    await handler.run_automatic()
    tasks.execute.assert_not_awaited()
    store.set_auto_daily("one", True)
    client = AsyncMock()
    result = await DailyRunner(client=client, store=store, config=config).run_all_daily("2026-10-22", automatic=True)
    client.get_profile.assert_not_awaited()
    assert result and result[0].items


@pytest.mark.asyncio
async def test_interrupted_renewal_is_visible_without_reexecuting(env):
    from astrbot_plugin_nikke.features.daily.action_models import account_scope
    store, account, _, renewal, _, _, handler = env
    key = f"session-renewal:v1:{account_scope(account)}:{account['binding_revision']}"
    store.claim_run(key, "one", "session_renewal", initial_status="DISPATCH_INTENT")
    result = await handler.handle_renewal(context("状态", action="续期"))
    assert "未决续期" in result.messages[0].text
    renewal.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_notification_failure_cannot_remove_automatic_risk_halt(env):
    from astrbot_plugin_nikke.features.daily.action_models import account_scope
    store, account, tasks, renewal, notice, _, handler = env
    for capability in ("community_actions", "session_renewal"):
        store.set_setting(f"{capability}:auto:one", binding_stamp(account))
    await handler.handle_tasks(context())
    renewal.execute.return_value = OperationResult("rate_limited", "请求受到限流")
    notice.side_effect = TimeoutError()
    await handler.run_automatic()
    assert store.get_setting(f"community_automation:halt:{account_scope(account)}:2026-10-22") is True
    tasks.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_astrbot_parameter_parser_preserves_fourth_word_of_task_auto_command():
    signature = inspect.signature(NikkePlugin.nikke)
    params = {k: v.default for k, v in signature.parameters.items() if k not in {"self", "event"}}
    parsed = CommandFilter("妮姬").validate_and_convert_params(["日常", "任务", "自动", "开"], params)
    plugin, recorders = _plugin_with_recorders()
    result = [r async for r in plugin.nikke(Event(), **parsed)]
    assert result == [("plain", "daily")]
    assert recorders["daily"].contexts[-1].parameters["value"] == "自动 开"
