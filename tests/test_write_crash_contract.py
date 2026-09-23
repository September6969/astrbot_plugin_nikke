# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 Daily/CDK 写请求的崩溃窗口不会被自动重放。"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.features.daily.models import DailyTaskStatus
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaTimeoutError, UnknownAfterAction


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
        self.intent_seen_before_write = self.store.get_run(run_key)["status"] == "DISPATCH_INTENT"
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
    assert store.get_run(signin_key)["status"] == "UNKNOWN_AFTER_ACTION"


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
    run_key = CdkService.persistent_run_key(account, "TEST-CODE")
    run = store.get_run(run_key)
    assert run["status"] == "UNKNOWN_AFTER_ACTION"
    assert "TEST-CODE" not in run["detail"]


@pytest.mark.asyncio
async def test_cdk_dispatch_intent_is_persisted_before_remote_write(tmp_path):
    store = NikkeStore(tmp_path)
    account = {"game_uid": "game-uid", "area_id": "1", "platform": "global"}
    key = CdkService.persistent_run_key(account, "TEST-CODE")
    client = AsyncMock()

    async def redeem(_account, _code):
        assert store.get_run(key)["status"] == "DISPATCH_INTENT"
        return type("Result", (), {"success": True, "terminal": True, "message": "兑换成功"})()

    client.redeem_cdk.side_effect = redeem
    result = await CdkService(client).redeem_single(
        account, "TEST-CODE", store=store, qq_id="synthetic-qq"
    )

    assert result.success is True
    assert client.redeem_cdk.await_count == 1
    assert store.get_run(key)["status"] == "success"


@pytest.mark.asyncio
async def test_legacy_cdk_success_record_blocks_replay_after_qq_rebinding(tmp_path):
    store = NikkeStore(tmp_path)
    account = {"game_uid": "game-uid", "area_id": "1", "platform": "global"}
    client = AsyncMock()
    legacy_key = CdkService._legacy_run_key("previous-qq", "game-uid", "TEST-CODE")
    store.claim_run(legacy_key, "previous-qq", "cdk")
    store.finish_run(legacy_key, "success", "兑换成功")

    result = await CdkService(client).redeem_single(
        account, "TEST-CODE", store=store, qq_id="synthetic-qq"
    )

    assert result.success is True
    client.redeem_cdk.assert_not_awaited()
    assert store.get_run(CdkService.persistent_run_key(account, "TEST-CODE")) is None


@pytest.mark.asyncio
async def test_legacy_cdk_failed_record_is_conservatively_blocked(tmp_path):
    store = NikkeStore(tmp_path)
    account = {"game_uid": "game-uid", "area_id": "1", "platform": "global"}
    client = AsyncMock()
    legacy_key = CdkService._legacy_run_key("previous-qq", "game-uid", "TEST-CODE")
    store.claim_run(legacy_key, "previous-qq", "cdk")
    store.finish_run(legacy_key, "failed", "旧版本无法证明未写入")

    result = await CdkService(client).redeem_single(
        account, "TEST-CODE", store=store, qq_id="current-qq"
    )

    assert result.is_unknown is True
    assert "未自动重发" in result.message
    client.redeem_cdk.assert_not_awaited()
    assert store.get_run(CdkService.persistent_run_key(account, "TEST-CODE")) is None


@pytest.mark.asyncio
async def test_cdk_timeout_and_unexpected_error_are_unknown_and_not_replayed(tmp_path):
    for error in (
        BlaBlaTimeoutError("synthetic timeout", endpoint="RedeemCdk"),
        RuntimeError("synthetic transport failure"),
    ):
        store = NikkeStore(tmp_path / type(error).__name__)
        client = AsyncMock()
        client.redeem_cdk.side_effect = error
        service = CdkService(client)
        account = {"game_uid": "game-uid", "area_id": "1", "platform": "global"}

        first = await service.redeem_single(
            account, "TEST-CODE", store=store, qq_id="synthetic-qq"
        )
        second = await service.redeem_single(
            account, "TEST-CODE", store=store, qq_id="synthetic-qq"
        )

        assert first.is_unknown is True
        assert second.is_unknown is True
        client.redeem_cdk.assert_awaited_once()
        run = store.get_run(CdkService.persistent_run_key(account, "TEST-CODE"))
        assert run["status"] == "UNKNOWN_AFTER_ACTION"
