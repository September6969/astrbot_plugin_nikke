"""后台任务完成、取消及关闭期间的登记行为。"""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock
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

    async def test_shutdown_is_idempotent(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False
        plugin._background_tasks = []
        plugin.feedback_manager = AsyncMock()
        plugin.web = AsyncMock()
        plugin.asset_manager = MagicMock()

        await plugin.terminate()
        await plugin.terminate()

        plugin.feedback_manager.close.assert_awaited_once()
        plugin.asset_manager.close.assert_called_once()
        plugin.web.stop.assert_awaited_once()

    async def test_concurrent_shutdown_waits_for_the_first_cleanup(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False
        plugin._background_tasks = []
        plugin.feedback_manager = AsyncMock()
        plugin.web = AsyncMock()

        async def delayed_stop():
            await asyncio.sleep(0)

        plugin.web.stop.side_effect = delayed_stop
        plugin.asset_manager = MagicMock()

        await asyncio.gather(plugin.terminate(), plugin.terminate())

        plugin.feedback_manager.close.assert_awaited_once()
        plugin.asset_manager.close.assert_called_once()
        plugin.web.stop.assert_awaited_once()

    async def test_cleanup_failure_keeps_shutdown_retryable(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False
        plugin._background_tasks = []
        plugin.feedback_manager = AsyncMock()
        plugin.web = AsyncMock()
        plugin.asset_manager = MagicMock()
        plugin.asset_manager.close.side_effect = [RuntimeError("synthetic close failure"), None]

        with self.assertRaisesRegex(RuntimeError, "synthetic close failure"):
            await plugin.terminate()
        self.assertFalse(getattr(plugin, "_terminated", False))

        await plugin.terminate()
        self.assertTrue(plugin._terminated)
        self.assertEqual(plugin.asset_manager.close.call_count, 2)

    async def test_shutdown_handles_partial_initialization_without_web(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False

        await plugin.terminate()

        self.assertTrue(plugin._terminated)

    async def test_shutdown_closes_falsey_injected_resources(self):
        class FalseyFeedback:
            def __bool__(self):
                return False

            async def close(self):
                self.closed = True

        class FalseyAssets:
            def __bool__(self):
                return False

            def close(self):
                self.closed = True

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False
        plugin._background_tasks = []
        plugin.feedback_manager = FalseyFeedback()
        plugin.asset_manager = FalseyAssets()
        plugin.web = AsyncMock()

        await plugin.terminate()

        self.assertTrue(plugin.feedback_manager.closed)
        self.assertTrue(plugin.asset_manager.closed)
        plugin.web.stop.assert_awaited_once()
