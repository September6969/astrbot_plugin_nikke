"""RuntimeScheduler 的持久化时刻、周期刷新与统一 task factory 合同。"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler


class RuntimeSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tick_schedules_daily_summary_sync_and_push_via_coordinator(self):
        created = []

        def task_factory(awaitable):
            task = asyncio.create_task(awaitable)
            created.append(task)
            return task

        coordinator = RuntimeCoordinator(task_factory=task_factory)
        events = []
        local_time = datetime(2026, 9, 23, 8, 10, tzinfo=timezone(timedelta(hours=8)))

        def action(name):
            async def run(*args, **kwargs):
                events.append((name, args, kwargs))
            return run

        scheduler = RuntimeScheduler(
            coordinator=coordinator,
            store=SimpleNamespace(get_setting=lambda _key, default=None: default),
            config={
                "daily_hour": 8,
                "daily_minute": 10,
                "summary_hour": 8,
                "summary_minute": 10,
                "enable_announcement_push": True,
            },
            run_daily=action("daily"),
            send_summary=action("summary"),
            sync_announcements=action("announcements"),
            sync_calendar=action("calendar"),
            dispatch_announcements=action("push"),
            clock=lambda: local_time,
            unix_time=lambda: 5000.0,
        )

        await scheduler.tick()
        await asyncio.sleep(0)

        self.assertEqual(
            {entry[0] for entry in events},
            {"daily", "summary", "announcements", "calendar", "push"},
        )
        self.assertIn(("daily", ("2026-09-23",), {"stagger": True, "automatic": True}), events)
        self.assertIn(("summary", ("2026-09-23",), {}), events)
        self.assertEqual(len(created), 5)
        await coordinator.close()

    async def test_invalid_persisted_schedule_fields_keep_safe_defaults(self):
        coordinator = RuntimeCoordinator()
        events = []
        local_time = datetime(2026, 9, 23, 8, 10, tzinfo=timezone(timedelta(hours=8)))
        scheduler = RuntimeScheduler(
            coordinator=coordinator,
            store=SimpleNamespace(get_setting=lambda key, default=None: "invalid" if key.endswith("hour") else default),
            config={"daily_hour": 8, "daily_minute": 10, "summary_hour": 8, "summary_minute": 30},
            run_daily=lambda *_args, **_kwargs: action(events, "daily"),
            send_summary=lambda *_args: action(events, "summary"),
            sync_announcements=lambda: action(events, "announcements"),
            sync_calendar=lambda: action(events, "calendar"),
            dispatch_announcements=lambda: action(events, "push"),
            clock=lambda: local_time,
            unix_time=lambda: 0.0,
        )

        await scheduler.tick()
        await asyncio.sleep(0)

        self.assertIn("daily", events)
        self.assertNotIn("summary", events)
        await coordinator.close()


async def action(events, name):
    events.append(name)


if __name__ == "__main__":
    unittest.main()
