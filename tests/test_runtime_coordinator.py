"""RuntimeCoordinator 的集中任务登记与生命周期合同。"""

from __future__ import annotations

import asyncio
import unittest

from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator


class RuntimeCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_is_idempotent_and_close_cancels_tasks_before_reverse_cleanup(self):
        coordinator = RuntimeCoordinator()
        events: list[str] = []
        started = asyncio.Event()

        async def child():
            try:
                await asyncio.Event().wait()
            finally:
                events.append("child-cancelled")

        async def initialize():
            events.append("initialize")
            coordinator.create_task(child())

        async def scheduler():
            events.append("scheduler")
            started.set()
            await asyncio.Event().wait()

        async def first_cleanup():
            events.append("first-cleanup")

        async def second_cleanup():
            events.append("second-cleanup")

        coordinator.register_cleanup("first", first_cleanup)
        coordinator.register_cleanup("second", second_cleanup)
        first = coordinator.start(initialize, scheduler)
        second = coordinator.start(lambda: asyncio.sleep(0), lambda: asyncio.sleep(0))
        self.assertIs(first, second)
        await started.wait()

        await coordinator.close()
        await coordinator.close()

        self.assertEqual(
            events,
            ["initialize", "scheduler", "child-cancelled", "second-cleanup", "first-cleanup"],
        )
        self.assertTrue(coordinator.closed)
        self.assertEqual(coordinator.active_task_count, 0)

    async def test_tasks_created_after_close_are_closed_without_scheduling(self):
        coordinator = RuntimeCoordinator()
        await coordinator.close()
        coroutine = asyncio.sleep(0)

        self.assertIsNone(coordinator.create_task(coroutine))
        self.assertIsNone(coroutine.cr_frame)

    async def test_startup_failure_unwinds_partial_initialization(self):
        coordinator = RuntimeCoordinator()
        cleaned = []
        coordinator.register_cleanup("resource", lambda: cleaned.append("closed"))

        async def fail_startup():
            raise RuntimeError("synthetic startup failure")

        root = coordinator.start(fail_startup, lambda: asyncio.sleep(0))
        with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
            await root

        self.assertEqual(cleaned, ["closed"])
        self.assertTrue(coordinator.closed)
        self.assertEqual(coordinator.state, "FAILED")

    async def test_cleanup_retry_repeats_only_failed_action(self):
        coordinator = RuntimeCoordinator()
        events = []
        attempts = 0

        async def flaky_cleanup():
            nonlocal attempts
            attempts += 1
            events.append("flaky")
            if attempts == 1:
                raise RuntimeError("synthetic cleanup failure")

        async def stable_cleanup():
            events.append("stable")

        coordinator.register_cleanup("flaky", flaky_cleanup)
        coordinator.register_cleanup("stable", stable_cleanup)

        with self.assertRaisesRegex(RuntimeError, "synthetic cleanup failure"):
            await coordinator.close()
        await coordinator.close()

        self.assertEqual(events, ["stable", "flaky", "flaky"])
        self.assertTrue(coordinator.closed)


if __name__ == "__main__":
    unittest.main()
