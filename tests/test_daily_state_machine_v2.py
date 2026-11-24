# SPDX-License-Identifier: GPL-3.0-or-later
"""PR-3B：执行租约回收、UNKNOWN_AFTER_ACTION 人工核实、预检重试与社区日调度。"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.application.commands.community_automation import CommunityAutomationHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler, community_due
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from astrbot_plugin_nikke.features.daily import action_models
from astrbot_plugin_nikke.features.daily.action_models import (
    ACKNOWLEDGED_UNKNOWN,
    account_execution_lease,
    account_scope,
    lease_key,
)
from astrbot_plugin_nikke.features.daily.actions import CommunityTaskService
from astrbot_plugin_nikke.features.daily.models import DailyTaskStatus
from astrbot_plugin_nikke.features.daily.runner import DailyRunner

CST = timezone(timedelta(hours=8))
UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    monkeypatch.delenv("NIKKE_ENCRYPTION_KEY", raising=False)


def _bind(store: NikkeStore, actor="one", uid="synthetic-game", openid="synthetic-openid"):
    token = "bind-" + actor + uuid.uuid4().hex
    store.create_bind_session(token, actor, status="pending")
    store.consume_bind_session(token, "game_token=synthetic", uid, openid, "合成账号", "", "3",
                               success_status="success")
    return store.get_account(actor)


def _age(store: NikkeStore, key: str, seconds: int) -> None:
    with store._connect() as conn:
        conn.execute("UPDATE action_runs SET created_at=created_at-? WHERE run_key=?", (seconds, key))


# ------------------------------------------------------------------ 社区日调度时刻

def test_community_due_places_early_morning_in_next_calendar_day() -> None:
    assert community_due("2026-11-22", 8, 10) == datetime(2026, 11, 22, 8, 10, tzinfo=CST)
    assert community_due("2026-11-22", 23, 59) == datetime(2026, 11, 22, 23, 59, tzinfo=CST)
    # 北京时间 06:00 属于前一社区日的末尾，不应在社区日开始时提前 22 小时触发
    assert community_due("2026-11-22", 6, 0) == datetime(2026, 11, 23, 6, 0, tzinfo=CST)


class _Store(dict):
    def get_setting(self, key, default=None):
        return self.get(key, default)

    def set_setting(self, key, value):
        self[key] = value


def _scheduler(store, clock, events, config=None):
    def action(name):
        async def run(*args, **kwargs):
            events.append((name, args))
        return run

    coordinator = SimpleNamespace(closing=False, create_task=asyncio.ensure_future)
    return RuntimeScheduler(
        coordinator=coordinator, store=store,
        config=config or {"daily_hour": 6, "daily_minute": 0, "summary_hour": 6, "summary_minute": 30},
        run_daily=action("daily"), send_summary=action("summary"), sync_announcements=AsyncMock(),
        sync_calendar=AsyncMock(), dispatch_announcements=AsyncMock(), clock=clock, unix_time=lambda: 0.0,
    )


@pytest.mark.asyncio
async def test_early_daily_hour_no_longer_fires_at_community_day_start() -> None:
    events: list = []
    now = {"t": datetime(2026, 11, 22, 8, 30, tzinfo=CST)}  # 社区日 11-22 刚开始
    scheduler = _scheduler(_Store(), lambda: now["t"], events)
    await scheduler.tick()
    await asyncio.sleep(0)
    assert not [e for e in events if e[0] == "daily"]

    now["t"] = datetime(2026, 11, 23, 6, 0, tzinfo=CST)  # 同一社区日（UTC 11-22 22:00）
    await scheduler.tick()
    await asyncio.sleep(0)
    assert ("daily", ("2026-11-22",)) in events


@pytest.mark.asyncio
async def test_summary_waits_for_daily_and_is_idempotent_across_restart() -> None:
    store = _Store()
    events: list = []
    gate = asyncio.Event()
    config = {"daily_hour": 8, "daily_minute": 10, "summary_hour": 8, "summary_minute": 30}
    now = {"t": datetime(2026, 11, 22, 8, 10, tzinfo=CST)}

    async def slow_daily(day, **_kwargs):
        events.append(("daily", (day,)))
        await gate.wait()

    scheduler = _scheduler(store, lambda: now["t"], events, config)
    scheduler._run_daily = slow_daily
    await scheduler.tick()
    now["t"] = datetime(2026, 11, 22, 8, 31, tzinfo=CST)  # 日常仍在执行
    await scheduler.tick()
    await asyncio.sleep(0)
    assert not [e for e in events if e[0] == "summary"]

    gate.set()
    await asyncio.sleep(0)
    now["t"] = datetime(2026, 11, 22, 8, 45, tzinfo=CST)  # 超过精确分钟仍补发
    await scheduler.tick()
    await asyncio.sleep(0)
    assert events.count(("summary", ("2026-11-22",))) == 1

    restarted = _scheduler(store, lambda: now["t"], events, config)  # 同分钟重启
    restarted._daily_task = None
    await restarted.tick()
    await asyncio.sleep(0)
    assert events.count(("summary", ("2026-11-22",))) == 1


# ------------------------------------------------------------------ 执行租约

def test_crashed_lease_from_other_process_reclaimed_only_after_timeout(tmp_path, monkeypatch) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    key = lease_key(account)
    store.claim_run(key, "one", "community_account_lease", initial_status="LEASED")
    store.finish_run(key, "LEASED", json.dumps({"owner": "other-process"}))

    with account_execution_lease(store, account) as acquired:
        assert not acquired  # 其他进程的新近占用：不接管

    _age(store, key, action_models.LEASE_TIMEOUT_SECONDS + 5)
    with account_execution_lease(store, account) as acquired:
        assert acquired
    assert store.get_run(key)["status"] == "RELEASED"


def test_lease_left_by_this_process_generation_is_reclaimed_immediately(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    key = lease_key(account)
    store.claim_run(key, "one", "community_account_lease", initial_status="LEASED")
    store.finish_run(key, "LEASED", json.dumps({"owner": action_models.PROCESS_TOKEN}))
    with account_execution_lease(store, account) as acquired:
        assert acquired


# ------------------------------------------------------------------ UNKNOWN_AFTER_ACTION

def _service(store, clock):
    runner = DailyRunner(store=store)
    gateway = SimpleNamespace(dispatch=AsyncMock(side_effect=AssertionError("不得重放")))
    return CommunityTaskService(gateway=gateway, store=store, config={"enable_daily_actions": True},
                                account_lock=runner._account_lock, sleep=AsyncMock(), clock=clock)


def _unknown(store, account, period, kind="like", post="p1"):
    key = f"community-actions:v1:{account_scope(account)}:{period}:{kind}:{post}"
    assert store.claim_run(key, "one", "community_action", initial_status="UNKNOWN_AFTER_ACTION")
    return key


def test_unknown_after_action_never_auto_unlocks(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    key = _unknown(store, account, "community-utc:2026-11-19")
    _age(store, key, 72 * 3600 + 60)
    service = _service(store, lambda: datetime(2026, 11, 22, 4, tzinfo=UTC))
    # 72 小时后仍跨周期阻断，且不因超时变化状态
    assert service._unresolved(account, "like", "community-utc:2026-11-22")
    assert store.get_run(key)["status"] == "UNKNOWN_AFTER_ACTION"


def test_acknowledgement_unblocks_only_future_periods_and_is_audited(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    period = "community-utc:2026-11-22"
    key = _unknown(store, account, period)
    service = _service(store, lambda: datetime(2026, 11, 22, 4, tzinfo=UTC))

    result = service.acknowledge_unknown(account, operator="one")

    assert result.status == "acknowledged"
    row = store.get_run(key)
    assert row["status"] == ACKNOWLEDGED_UNKNOWN
    audit = json.loads(row["detail"])
    assert audit["acknowledged_by"] == "one" and audit["original_run_key"] == key
    assert audit["previous_status"] == "UNKNOWN_AFTER_ACTION" and audit["replayed"] is False
    history = store.get_setting(f"community_automation:recovery_audit:{account_scope(account)}")
    assert history and history[-1]["original_run_key"] == key
    # 所在周期仍阻断：不能为同周期再预留新动作
    assert service._unresolved(account, "like", period)
    scope = f"community-actions:v1:{account_scope(account)}:{period}:like"
    assert not store.reserve_run(scope, scope + ":p2", "one", "community_action", limit=10,
                                 blocking_statuses={"UNKNOWN_AFTER_ACTION", ACKNOWLEDGED_UNKNOWN},
                                 initial_status="DISPATCH_INTENT")
    # 下一个周期放行；原动作从未被重放
    assert not service._unresolved(account, "like", "community-utc:2026-11-23")
    service.gateway.dispatch.assert_not_awaited()


def test_fresh_dispatch_intent_is_not_acknowledgeable(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    key = f"community-actions:v1:{account_scope(account)}:community-utc:2026-11-22:like:p1"
    store.claim_run(key, "one", "community_action", initial_status="DISPATCH_INTENT")
    service = _service(store, lambda: datetime.now(UTC))
    assert service.recovery_candidates(account) == []
    _age(store, key, 300)
    assert [row["run_key"] for row in service.recovery_candidates(account)] == [key]


@pytest.mark.asyncio
async def test_recovery_command_requires_private_two_step_confirmation(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    key = _unknown(store, account, "community-utc:2026-11-22")
    service = _service(store, lambda: datetime(2026, 11, 22, 4, tzinfo=UTC))
    handler = CommunityAutomationHandler(tasks=service, renewal=None, store=store,
                                         config={"enable_daily_actions": True})

    def context(value, private=True):
        return CommandContext(actor_id="one", parameters={"value": value}, is_private_chat=private,
                              conversation_id="private:one")

    group = await handler.handle_tasks(context("确认恢复 确认", private=False))
    assert "私聊" in group.messages[0].text
    preview = await handler.handle_tasks(context("确认恢复"))
    assert "确认恢复 确认" in preview.messages[0].text
    assert store.get_run(key)["status"] == "UNKNOWN_AFTER_ACTION"
    done = await handler.handle_tasks(context("确认恢复 确认"))
    assert "不会被补做或重放" in done.messages[0].text
    assert store.get_run(key)["status"] == ACKNOWLEDGED_UNKNOWN


# ------------------------------------------------------------------ 签到预检重试

class _Client:
    def __init__(self) -> None:
        self.expired = True
        self.writes = 0

    async def get_profile(self, account):
        if self.expired:
            raise CredentialExpiredError("登录状态已失效")

    async def get_daily_signin(self, account):
        return {"found": True, "completed": False, "task_id": "t"}

    async def perform_daily_signin(self, account):
        self.writes += 1
        return "签到成功"


@pytest.mark.asyncio
async def test_precheck_expiry_allows_same_day_signin_after_rebind(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    client = _Client()
    runner = DailyRunner(store=store, client=client, config={"enable_daily_actions": True})

    first = await runner.run_daily_for_account(account, "2026-11-22")
    assert first.status is DailyTaskStatus.COOKIE_EXPIRED
    assert store.get_run(runner.daily_run_key("2026-11-22", account, "daily"))["status"] == "precheck_expired"

    client.expired = False  # 重新绑定后
    second = await runner.run_daily_for_account(store.get_account("one"), "2026-11-22")
    assert second.status is DailyTaskStatus.SUCCESS
    assert client.writes == 1
    third = await runner.run_daily_for_account(store.get_account("one"), "2026-11-22")
    assert third.status is DailyTaskStatus.ALREADY_DONE
    assert client.writes == 1


@pytest.mark.asyncio
async def test_fresh_daily_intent_is_not_overwritten_by_concurrent_attempt(tmp_path) -> None:
    store = NikkeStore(tmp_path)
    account = _bind(store)
    client = _Client()
    client.expired = False
    runner = DailyRunner(store=store, client=client, config={"enable_daily_actions": True})
    key = runner.daily_run_key("2026-11-22", account, "daily")
    store.claim_run(key, "one", "daily", initial_status="DISPATCH_INTENT")

    result = await runner.run_daily_for_account(account, "2026-11-22")

    assert result.status is DailyTaskStatus.UNKNOWN_AFTER_ACTION
    assert store.get_run(key)["status"] == "DISPATCH_INTENT"
    assert client.writes == 0
