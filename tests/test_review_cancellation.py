"""单条兑换取消后不得重复进入远端兑换。"""
import asyncio
import hashlib
import tempfile
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.storage import NikkeStore


class CancellationTests(IsolatedAsyncioTestCase):
    async def test_single_cancel_is_unknown_and_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = NikkeStore(directory)
            plugin.config = {"enable_cdk_redemption": True}
            plugin._account_or_error = lambda event: {"game_uid": "synthetic-game"}
            entered = asyncio.Event()
            async def redeem(*args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
            plugin.cdk_service = SimpleNamespace(redeem_single=AsyncMock(side_effect=redeem))
            event = SimpleNamespace(get_sender_id=lambda: "synthetic-user", plain_result=lambda x: x)
            async def consume():
                return [result async for result in plugin.cdk(event, "FAKE-CODE")]
            task = asyncio.create_task(consume())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            key = "cdk:synthetic-user:synthetic-game:" + hashlib.sha256(b"FAKE-CODE").hexdigest()
            self.assertEqual(plugin.store.get_run(key)["status"], "unknown")
            await consume()
            plugin.cdk_service.redeem_single.assert_awaited_once()
