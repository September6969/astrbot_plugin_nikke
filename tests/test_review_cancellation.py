"""单条兑换取消后不得重复进入远端兑换。"""
from plugin_fixtures import inject_cdk_handler, make_plugin_shell
import asyncio
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.cdk.service import CdkService


class CancellationTests(IsolatedAsyncioTestCase):
    async def test_single_cancel_is_unknown_and_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = make_plugin_shell()
            plugin.services.store = NikkeStore(directory)
            plugin.config = {"enable_cdk_redemption": True}
            plugin.services.store.get_account = lambda qq_id, with_cookie=True: {
                "qq_id": qq_id,
                "game_uid": "synthetic-game",
                "cookie": "synthetic-cookie",
            }
            entered = asyncio.Event()
            async def redeem(_account, _code):
                entered.set()
                await asyncio.Event().wait()
            client = AsyncMock()
            client.redeem_cdk.side_effect = redeem
            plugin.services.cdk_service = CdkService(client)
            inject_cdk_handler(plugin)
            event = SimpleNamespace(get_sender_id=lambda: "synthetic-user", plain_result=lambda x: x)
            async def consume():
                return [result async for result in plugin.cdk(event, "FAKE-CODE")]
            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            key = CdkService.persistent_run_key(
                {"game_uid": "synthetic-game"}, "FAKE-CODE"
            )
            self.assertEqual(plugin.services.store.get_run(key)["status"], "UNKNOWN_AFTER_ACTION")
            await consume()
            self.assertEqual(client.redeem_cdk.await_count, 1)
