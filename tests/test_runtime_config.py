# SPDX-License-Identifier: GPL-3.0-or-later
"""验证插件运行时配置的边界合同。"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.runtime_config import normalize_runtime_config, read_schedule_clock


class RuntimeConfigTests(unittest.TestCase):
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

    def test_scheduler_survives_corrupt_persisted_clock(self) -> None:
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin._closing = False
        plugin.config = normalize_runtime_config({})
        persisted = {"daily_hour": "broken", "summary_minute": 99}
        plugin.store = SimpleNamespace(
            get_setting=lambda key, default=None: persisted.get(key, default)
        )
        plugin._spawn_background_task = lambda coro: coro.close()

        async def stop_after_one_tick(_delay: int) -> None:
            plugin._closing = True

        with patch("astrbot_plugin_nikke.main.asyncio.sleep", new=stop_after_one_tick):
            asyncio.run(plugin._scheduler_loop())

        self.assertTrue(plugin._closing)

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
