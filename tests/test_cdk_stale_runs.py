"""硬崩溃遗留的写请求只隔离，不重放。"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

import pytest

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.integrations.blablalink.client import CdkRedemptionResult


def account():
    return {"game_uid": "synthetic-game"}


def key(code):
    return CdkService.persistent_run_key(account(), code)


def legacy_key(code):
    return CdkService._legacy_run_key("synthetic-user", "synthetic-game", code)


@pytest.mark.asyncio
async def test_single_final_and_retryable_states_without_plaintext():
    for status in ("success", "terminal", "unknown", "UNKNOWN_AFTER_ACTION", "failed", "expired"):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            store.claim_run(key("FAKE-CODE"), "synthetic-user", "cdk", initial_status="DISPATCH_INTENT")
            store.finish_run(key("FAKE-CODE"), status)
            client = AsyncMock()
            client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "兑换成功")

            await CdkService(client).redeem_single(
                account(), "FAKE-CODE", store=store, qq_id="synthetic-user"
            )

            assert client.redeem_cdk.await_count == int(status in {"failed", "expired"})
            assert "FAKE-CODE" not in str(store.get_run(key("FAKE-CODE")))


@pytest.mark.asyncio
async def test_single_stale_and_fresh_intents_never_replay():
    for stale in (True, False):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1000):
                store.claim_run(key("FAKE-CODE"), "synthetic-user", "cdk", initial_status="DISPATCH_INTENT")
            client = AsyncMock()
            service = CdkService(client)
            with patch(
                "astrbot_plugin_nikke.core.storage.time.time",
                return_value=1180 if stale else 1010,
            ):
                await service.redeem_single(
                    account(), "FAKE-CODE", store=store, qq_id="synthetic-user"
                )
                await service.redeem_single(
                    account(), "FAKE-CODE", store=store, qq_id="synthetic-user"
                )
            client.redeem_cdk.assert_not_awaited()
            expected = "UNKNOWN_AFTER_ACTION" if stale else "DISPATCH_INTENT"
            assert store.get_run(key("FAKE-CODE"))["status"] == expected
            assert "FAKE-CODE" not in str(store.get_run(key("FAKE-CODE")))


@pytest.mark.asyncio
async def test_legacy_batch_intent_is_quarantined_but_new_code_continues():
    with tempfile.TemporaryDirectory() as directory:
        store = NikkeStore(directory)
        with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1000):
            store.claim_run(legacy_key("FAKE-A"), "synthetic-user", "cdk", initial_status="DISPATCH_INTENT")
        client = AsyncMock()
        client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "ok")
        with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1180), patch(
            "astrbot_plugin_nikke.features.cdk.service.asyncio.sleep", new_callable=AsyncMock
        ):
            result = await CdkService(client).redeem_batch(
                account(),
                ["FAKE-A", "FAKE-B"],
                store=store,
                qq_id="synthetic-user",
            )
        assert result.results[0].is_unknown
        assert result.results[1].success
        client.redeem_cdk.assert_awaited_once()
        assert store.get_run(legacy_key("FAKE-A"))["status"] == "UNKNOWN_AFTER_ACTION"


@pytest.mark.asyncio
async def test_atomic_transition_across_store_instances():
    with tempfile.TemporaryDirectory() as directory:
        stores = [NikkeStore(directory), NikkeStore(directory)]
        with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1000):
            stores[0].claim_run(key("FAKE-A"), "synthetic-user", "cdk", initial_status="DISPATCH_INTENT")
        with patch("astrbot_plugin_nikke.core.storage.time.time", return_value=1180), ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda store: store.transition_run(
                        key("FAKE-A"),
                        from_statuses={"running", "DISPATCH_INTENT"},
                        to_status="UNKNOWN_AFTER_ACTION",
                        stale_after=120,
                        detail="结果未确认",
                    ),
                    stores,
                )
            )
        assert sum(results) == 1


@pytest.mark.asyncio
async def test_batch_final_states_skip_retryable_states_retry():
    for status in ("success", "terminal", "unknown", "UNKNOWN_AFTER_ACTION", "failed", "expired"):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            store.claim_run(key("FAKE-A"), "synthetic-user", "cdk", initial_status="DISPATCH_INTENT")
            store.finish_run(key("FAKE-A"), status)
            client = AsyncMock()
            client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "ok")
            await CdkService(client).redeem_batch(
                account(), ["FAKE-A"], store=store, qq_id="synthetic-user"
            )
            assert client.redeem_cdk.await_count == int(status in {"failed", "expired"})
            assert "FAKE-A" not in str(store.get_run(key("FAKE-A")))
