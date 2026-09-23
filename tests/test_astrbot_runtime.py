"""AstrBot runtime adapter 的本地生命周期与假传输合同。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_nikke.adapters.astrbot.runtime import AstrBotRuntimeAdapter
from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator


class AstrBotRuntimeAdapterTests(unittest.IsolatedAsyncioTestCase):
    def _services(self, events: list[str], initialized: asyncio.Event):
        async def get_directory():
            return [{"name": "synthetic"}]

        async def start_web(_host: str, _port: int) -> None:
            events.append("web-start")

        web = SimpleNamespace(
            start=AsyncMock(side_effect=start_web),
            stop=AsyncMock(side_effect=lambda: events.append("web")),
            site_origin="https://fake.invalid",
        )
        services = SimpleNamespace(
            extension_zip=None,
            store=SimpleNamespace(get_setting=lambda _key, default=None: default),
            web=web,
            asset_manager=SimpleNamespace(
                close=lambda: events.append("assets"),
                nikke_db=SimpleNamespace(
                    get_l2d_index=lambda **_kwargs: {"synthetic": True}
                ),
            ),
            voice_application=SimpleNamespace(
                close=AsyncMock(side_effect=lambda: events.append("voice"))
            ),
            feedback_manager=SimpleNamespace(
                close=AsyncMock(side_effect=lambda: events.append("feedback"))
            ),
            tower_application=SimpleNamespace(preload=AsyncMock()),
            client=SimpleNamespace(get_directory=AsyncMock(side_effect=get_directory)),
            campaign_application=SimpleNamespace(update_directory=Mock()),
            character_application=SimpleNamespace(
                preload_stat_resources=AsyncMock()
            ),
            announcement_application=SimpleNamespace(
                sync_announcements=AsyncMock(),
                dispatch_pushes=AsyncMock(),
            ),
            calendar_application=SimpleNamespace(refresh_schedule=AsyncMock()),
        )
        return services

    async def test_start_and_close_are_coordinated_once_in_reverse_dependency_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "plugin"
            extension_dir = plugin_dir / "extension"
            extension_dir.mkdir(parents=True)
            (extension_dir / "manifest.json").write_text(
                '{"manifest_version": 3}', encoding="utf-8"
            )
            events: list[str] = []
            initialized = asyncio.Event()
            services = self._services(events, initialized)
            services.extension_zip = root / "extension.zip"
            coordinator = RuntimeCoordinator()

            def on_directory_loaded(directory_data):
                services.campaign_application.update_directory(directory_data)
                initialized.set()

            runtime = AstrBotRuntimeAdapter(
                coordinator=coordinator,
                services=services,
                context=SimpleNamespace(send_message=AsyncMock()),
                plugin_dir=plugin_dir,
                config={
                    "daily_hour": 23,
                    "daily_minute": 10,
                    "summary_hour": 23,
                    "summary_minute": 30,
                    "enable_announcement_push": False,
                },
                web_host="127.0.0.1",
                web_port=6210,
                run_daily=AsyncMock(),
                send_summary=AsyncMock(),
                on_directory_loaded=on_directory_loaded,
            )

            first = runtime.start()
            self.assertIs(first, runtime.start())
            await asyncio.wait_for(initialized.wait(), timeout=2)
            await asyncio.sleep(0.02)
            self.assertTrue(services.extension_zip.exists())
            self.assertEqual(
                services.campaign_application.update_directory.call_args.args[0],
                [{"name": "synthetic"}],
            )

            await runtime.close()
            await runtime.close()

            self.assertEqual(events[-4:], ["feedback", "voice", "assets", "web"])
            self.assertEqual(services.web.stop.await_count, 1)
            self.assertTrue(coordinator.closed)
            self.assertEqual(coordinator.active_task_count, 0)
            self.assertIsNone(runtime.request_calendar_refresh())

    async def test_announcement_dispatch_stays_off_without_explicit_configuration(self):
        coordinator = RuntimeCoordinator()
        application = SimpleNamespace(dispatch_pushes=AsyncMock())
        context = SimpleNamespace(send_message=AsyncMock())
        runtime = object.__new__(AstrBotRuntimeAdapter)
        runtime._coordinator = coordinator
        runtime._config = {}
        runtime._context = context
        runtime._services = SimpleNamespace(announcement_application=application)

        await runtime._dispatch_announcements()

        application.dispatch_pushes.assert_not_awaited()
        context.send_message.assert_not_awaited()
        await coordinator.close()

    async def test_enabled_announcement_transport_uses_only_fake_target(self):
        coordinator = RuntimeCoordinator()
        context = SimpleNamespace(send_message=AsyncMock())

        async def dispatch(sender):
            self.assertTrue(await sender("fake-session", "synthetic notice"))

        application = SimpleNamespace(dispatch_pushes=AsyncMock(side_effect=dispatch))
        runtime = object.__new__(AstrBotRuntimeAdapter)
        runtime._coordinator = coordinator
        runtime._config = {"enable_announcement_push": True}
        runtime._context = context
        runtime._services = SimpleNamespace(announcement_application=application)

        await runtime._dispatch_announcements()

        application.dispatch_pushes.assert_awaited_once()
        context.send_message.assert_awaited_once()
        self.assertEqual(context.send_message.await_args.args[0], "fake-session")
        await coordinator.close()


if __name__ == "__main__":
    unittest.main()
