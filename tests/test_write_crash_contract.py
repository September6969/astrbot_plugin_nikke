# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 Daily/CDK 写请求的崩溃窗口不会被自动重放。"""

import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.features.daily.models import DailyTaskStatus
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.integrations.blablalink.client import UnknownAfterAction


class _DailyCrashClient:
    def __init__(self, store: NikkeStore, account: dict[str, str], day: str) -> None:
        self.store = store
        self.account = account
        self.day = day
        self.perform_calls = 0
        self.intent_seen_before_write = False
        self.read_calls = 0

    async def get_profile(self, account: dict[str, str]) -> dict[str, str]:
        return account

    async def get_daily_signin(self, account: dict[str, str]) -> dict[str, object]:
        self.read_calls += 1
        return {"found": True, "completed": False, "task_id": "daily-task"}

    async def perform_daily_signin(self, account: dict[str, str]) -> str:
        self.perform_calls += 1
        run_key = DailyRunner.daily_run_key(self.day, self.account, "signin")
        self.intent_seen_before_write = self.store.get_run(run_key)["status"] == "running"
        raise UnknownAfterAction("结果未确认", "UNKNOWN_AFTER_ACTION", "DailyCheckIn")


@pytest.mark.asyncio
async def test_daily_unknown_write_is_persisted_before_side_effect_and_not_replayed(tmp_path):
    store = NikkeStore(tmp_path)
    day = "2026-09-22"
    account = {
        "qq_id": "synthetic-qq",
        "nickname": "synthetic-account",
        "game_uid": "game-uid",
        "area_id": "1",
        "platform": "global",
    }
    client = _DailyCrashClient(store, account, day)
    runner = DailyRunner(client=client, store=store, config={"enable_daily_actions": True})

    first = await runner.run_daily_for_account(account, day)
    second = await runner.run_daily_for_account(account, day)

    signin_key = DailyRunner.daily_run_key(day, account, "signin")
    assert first.status is DailyTaskStatus.UNKNOWN_AFTER_ACTION
    assert second.status is DailyTaskStatus.UNKNOWN_AFTER_ACTION
    assert client.intent_seen_before_write is True
    assert client.perform_calls == 1
    assert client.read_calls == 2
    assert store.get_run(signin_key)["status"] == "unknown"


@pytest.mark.asyncio
async def test_cdk_cancelled_write_is_marked_unknown_and_not_replayed(tmp_path):
    store = NikkeStore(tmp_path)
    client = AsyncMock()
    client.redeem_cdk.side_effect = asyncio.CancelledError()
    service = CdkService(client)
    account = {"game_uid": "game-uid"}

    with pytest.raises(asyncio.CancelledError):
        await service.redeem_single(account, "TEST-CODE", account_key="game-uid", store=store, qq_id="synthetic-qq")

    second = await service.redeem_single(
        account,
        "TEST-CODE",
        account_key="game-uid",
        store=store,
        qq_id="synthetic-qq",
    )

    assert second.is_unknown is True
    assert second.success is False
    assert client.redeem_cdk.await_count == 1
    run_key = "cdk:synthetic-qq:game-uid:" + hashlib.sha256(b"TEST-CODE").hexdigest()
    run = store.get_run(run_key)
    assert run["status"] == "unknown"
    assert "TEST-CODE" not in run["detail"]
