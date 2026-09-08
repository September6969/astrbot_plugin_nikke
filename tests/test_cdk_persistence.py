"""重复批量、跨服务重启与取消使用持久执行记录。"""
import tempfile
import hashlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import patch
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.client import CdkRedemptionResult, BlaBlaTimeoutError
from astrbot_plugin_nikke.cdk_service import CdkService
from astrbot_plugin_nikke.cdk_models import CdkBatchResult, CdkRedeemResult
from astrbot_plugin_nikke.main import NikkePlugin


class PersistenceTests(IsolatedAsyncioTestCase):
    async def test_command_wires_persistent_store_and_account_identity(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.config = {"enable_cdk_redemption": True}
        plugin.store = object()
        plugin._account_or_error = lambda event: {"game_uid": "synthetic-game"}
        plugin.cdk_service = SimpleNamespace(
            redeem_batch=AsyncMock(
                return_value=CdkBatchResult(
                    results=[CdkRedeemResult("SECRET-CODE", True, "兑换成功")]
                )
            )
        )

        class Event:
            def get_sender_id(self):
                return "synthetic-user"

            def plain_result(self, text):
                return text

        output = [item async for item in plugin.cdk_batch(Event(), "SECRET-CODE")]

        plugin.cdk_service.redeem_batch.assert_awaited_once_with(
            {"game_uid": "synthetic-game"},
            ["SECRET-CODE"],
            account_key="synthetic-user:synthetic-game",
            store=plugin.store,
            qq_id="synthetic-user",
        )
        self.assertNotIn("SECRET-CODE", output[0])

    async def test_service_batch_limits_and_minimum_delay(self):
        client = AsyncMock()
        client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "ok")
        service = CdkService(client)
        with self.assertRaises(ValueError):
            await service.redeem_batch({}, ["FAKE"] * 11)
        client.redeem_cdk.assert_not_awaited()
        with patch("astrbot_plugin_nikke.cdk_service.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await service.redeem_batch({}, ["FAKE-1", "FAKE-2"], delay=0)
            sleep.assert_awaited_once_with(1.0)

    async def test_batch_restart_reuses_single_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            client = AsyncMock()
            client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "ok")
            for _ in range(2):
                result = await CdkService(client).redeem_batch({"game_uid": "fake-game"}, ["TEST-CODE"],
                    account_key="fake-account", store=store, qq_id="fake-qq", delay=0)
                self.assertTrue(result.results[0].success)
            self.assertEqual(client.redeem_cdk.await_count, 1)
            key = "cdk:fake-qq:fake-game:" + hashlib.sha256(b"TEST-CODE").hexdigest()
            self.assertEqual(store.get_run(key)["status"], "success")
            self.assertNotIn("TEST-CODE", str(store.get_run(key)))

    async def test_unknown_batch_is_not_automatically_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            client = AsyncMock()
            client.redeem_cdk.side_effect = BlaBlaTimeoutError("timeout")
            service = CdkService(client)
            for _ in range(2):
                result = await service.redeem_batch({"game_uid": "fake"}, ["TEST-CODE"], store=store, qq_id="fake", delay=0)
                self.assertTrue(result.results[0].is_unknown)
            self.assertEqual(client.redeem_cdk.await_count, 1)

    async def test_single_and_batch_share_persistent_primitive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            client = AsyncMock()
            client.redeem_cdk.return_value = CdkRedemptionResult(True, True, "ok", "0")
            service = CdkService(client)
            first = await service.redeem_single(
                {"game_uid": "fake-game"},
                "TEST-CODE",
                account_key="fake-account",
                store=store,
                qq_id="fake-qq",
            )
            second = await service.redeem_single(
                {"game_uid": "fake-game"},
                "TEST-CODE",
                account_key="fake-account",
                store=store,
                qq_id="fake-qq",
            )
            self.assertTrue(first.success)
            self.assertFalse(second.success)
            self.assertEqual(client.redeem_cdk.await_count, 1)
