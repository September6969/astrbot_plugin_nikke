"""后台任务完成、取消及关闭期间的登记行为。"""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from types import SimpleNamespace
from astrbot_plugin_nikke.main import NikkePlugin


class LifecycleTests(IsolatedAsyncioTestCase):
    async def test_shutdown_awaits_cleanup_before_resources(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._background_tasks = []
        events = []
        async def job():
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cancelled")
        plugin.web = SimpleNamespace(stop=AsyncMock(side_effect=lambda: events.append("web")))
        plugin._spawn_background_task(job())
        await asyncio.sleep(0)
        await plugin.terminate()
        self.assertEqual(events, ["cancelled", "web"])
        self.assertEqual(plugin._background_tasks, [])
        self.assertIsNone(plugin._spawn_background_task(job()))

    async def test_completed_task_removed(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._background_tasks = []
        task = plugin._spawn_background_task(asyncio.sleep(0))
        await task
        await asyncio.sleep(0)
        self.assertEqual(plugin._background_tasks, [])
