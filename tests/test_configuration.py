import ast
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
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
        # 单独执行打包方法，避免为文件打包测试加载AstrBot运行时。
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_pack_extension')
        namespace = {'zipfile': zipfile, 'json': json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'main.py', 'exec'), namespace)
        with tempfile.TemporaryDirectory() as td:
            plugin = SimpleNamespace(plugin_dir=ROOT, extension_zip=Path(td)/'extension.zip', web=SimpleNamespace(site_origin='https://bot.example'))
            namespace['_pack_extension'](plugin)
            with zipfile.ZipFile(plugin.extension_zip) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['host_permissions'], ['https://*.blablalink.com/*', 'https://bot.example/*'])
                self.assertIsNone(archive.testzip())

    def test_schedule_date_uses_beijing_midnight(self):
        from datetime import datetime, timedelta, timezone
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == 'datetime' and n.func.attr == 'now']
        class Clock:
            @staticmethod
            def now(tz=None):
                return datetime(2026, 9, 4, 16, 5, tzinfo=timezone.utc).astimezone(tz)
        self.assertTrue(calls)
        for call in calls:
            value = eval(compile(ast.Expression(call), 'main.py', 'eval'),
                         {'datetime': Clock, 'timedelta': timedelta, 'timezone': timezone})
            self.assertEqual(value.strftime('%Y-%m-%d %H:%M'), '2026-09-05 00:05')
