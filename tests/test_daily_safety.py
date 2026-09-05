"""签到写后不确定结果不能自动重发。"""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from astrbot_plugin_nikke.client import BlaBlaClient, BlaBlaTimeoutError, BlaBlaNetworkError, UnknownAfterAction


class DailySafetyTests(IsolatedAsyncioTestCase):
    async def test_ambiguous_write_once(self):
        for error in [None, BlaBlaTimeoutError("超时"), BlaBlaNetworkError("断网")]:
            client = BlaBlaClient()
            client.get_daily_signin = AsyncMock(return_value={"found": True, "completed": False, "task_id": "fake"})
            client._community_request = AsyncMock(side_effect=error)
            with self.assertRaises(UnknownAfterAction):
                await client.perform_daily_signin({})
            self.assertEqual(client._community_request.await_count, 1)
            self.assertEqual(client.get_daily_signin.await_count, 2)

    async def test_timeout_confirmed_by_read(self):
        client = BlaBlaClient()
        client.get_daily_signin = AsyncMock(side_effect=[
            {"found": True, "completed": False, "task_id": "fake"}, {"completed": True}])
        client._community_request = AsyncMock(side_effect=BlaBlaTimeoutError("超时"))
        self.assertEqual(await client.perform_daily_signin({}), "签到成功")
        self.assertEqual(client._community_request.await_count, 1)
