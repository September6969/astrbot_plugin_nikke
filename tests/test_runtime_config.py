# SPDX-License-Identifier: GPL-3.0-or-later
"""验证插件运行时配置的边界合同。"""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from astrbot_plugin_nikke.core.config import normalize_runtime_config, read_schedule_clock
from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_numeric_configuration_uses_safe_defaults(self) -> None:
        config = normalize_runtime_config(
            {
                "request_timeout": "not-a-number",
                "web_port": 70000,
                "daily_hour": True,
                "daily_minute": -1,
                "summary_hour": "23",
                "summary_minute": 60,
                "max_concurrency": 0,
                "enable_daily_actions": False,
            }
        )

        self.assertEqual(config["request_timeout"], 20)
        self.assertEqual(config["web_port"], 6210)
        self.assertEqual(config["daily_hour"], 8)
        self.assertEqual(config["daily_minute"], 10)
        self.assertEqual(config["summary_hour"], 23)
        self.assertEqual(config["summary_minute"], 30)
        self.assertEqual(config["max_concurrency"], 2)
        self.assertFalse(config["enable_daily_actions"])

    async def test_scheduler_survives_corrupt_persisted_clock(self) -> None:
        coordinator = RuntimeCoordinator()
        config = normalize_runtime_config({})
        persisted = {"daily_hour": "broken", "summary_minute": 99}
        store = SimpleNamespace(
            get_setting=lambda key, default=None: persisted.get(key, default)
        )
        events = []
        scheduler = RuntimeScheduler(
            coordinator=coordinator,
            store=store,
            config=config,
            run_daily=lambda day, **_kwargs: self._record(events, "daily", day),
            send_summary=lambda day: self._record(events, "summary", day),
            sync_announcements=lambda: self._record(events, "announcements"),
            sync_calendar=lambda: self._record(events, "calendar"),
            dispatch_announcements=lambda: self._record(events, "push"),
            clock=lambda: datetime(
                2026, 9, 23, config["daily_hour"], config["daily_minute"],
                tzinfo=timezone(timedelta(hours=8)),
            ),
            unix_time=lambda: 0.0,
        )

        await scheduler.tick()
        await asyncio.sleep(0)

        self.assertEqual(events, [("daily", "2026-09-23")])
        await coordinator.close()

    @staticmethod
    async def _record(events, *entry):
        events.append(entry)

    def test_malformed_persisted_json_is_scoped_to_one_clock_field(self) -> None:
        """持久化层解析异常只影响对应字段，另一字段仍按实际值读取。"""
        def read_setting(key: str, default=None):
            if key == "daily_hour":
                raise ValueError("invalid persisted JSON")
            if key == "daily_minute":
                return 42
            return default

        self.assertEqual(
            read_schedule_clock(
                read_setting,
                "daily",
                default_hour=8,
                default_minute=10,
            ),
            (8, 42),
        )


if __name__ == "__main__":
    unittest.main()
