import json
import tempfile
import unittest
import zipfile
from datetime import datetime as RealDateTime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from astrbot_plugin_nikke.adapters.astrbot.runtime import AstrBotRuntimeAdapter
from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
from astrbot_plugin_nikke.integrations.web.service import BindingWebService

ROOT = Path(__file__).resolve().parents[1]

class ConfigurationTests(unittest.TestCase):
    def test_custom_site_and_invalid_urls(self):
        service = BindingWebService(None, None, Path('unused'), public_base_url='https://bot.example/')
        self.assertEqual(service.site_origin, 'https://bot.example')
        for url in ['http://bot.example', 'https://user:pass@bot.example', 'https://bot.example/path']:
            with self.assertRaises(ValueError):
                BindingWebService(None, None, Path('unused'), public_base_url=url)

    def test_download_manifest_uses_configured_site(self):
        with tempfile.TemporaryDirectory() as td:
            adapter = object.__new__(AstrBotRuntimeAdapter)
            adapter._plugin_dir = ROOT
            adapter._services = SimpleNamespace(
                extension_zip=Path(td) / 'extension.zip',
                web=SimpleNamespace(site_origin='https://bot.example'),
            )
            adapter._pack_extension()
            with zipfile.ZipFile(adapter._services.extension_zip) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['host_permissions'], ['https://*.blablalink.com/*', 'https://bot.example/*'])
                self.assertIsNone(archive.testzip())

    def test_schedule_date_uses_beijing_midnight(self):
        class Clock:
            @staticmethod
            def now(tz=None):
                return RealDateTime(
                    2026, 9, 4, 16, 5, tzinfo=timezone.utc
                ).astimezone(tz)

        with patch(
            'astrbot_plugin_nikke.core.lifecycle.scheduler.datetime', Clock
        ):
            scheduler = RuntimeScheduler(
                coordinator=RuntimeCoordinator(),
                store=SimpleNamespace(get_setting=lambda _key, default=None: default),
                config={
                    'daily_hour': 8,
                    'daily_minute': 10,
                    'summary_hour': 8,
                    'summary_minute': 30,
                },
                run_daily=lambda *_args, **_kwargs: None,
                send_summary=lambda _day: None,
                sync_announcements=lambda: None,
                sync_calendar=lambda: None,
                dispatch_announcements=lambda: None,
            )
            self.assertEqual(
                scheduler._clock().strftime('%Y-%m-%d %H:%M'),
                '2026-09-05 00:05',
            )
