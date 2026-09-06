"""公开塔层查询不需要绑定账号，并安全处理未知层数。"""
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from astrbot_plugin_nikke.tower_registry import TowerRegistry
from astrbot_plugin_nikke.main import NikkePlugin


class TowerTests(IsolatedAsyncioTestCase):
    def test_snapshot_and_unknown(self):
        registry = TowerRegistry(Path(__file__).resolve().parents[1] / "assets/tower_floors.json")
        self.assertIn("7,740", registry.describe("极乐净土", "1"))
        self.assertIn("未收录", registry.describe("elysion", "9999"))
        self.assertIn("用法", registry.describe("other", "1"))
        self.assertIn("用法", registry.describe("tribe", "-1"))

    async def test_command_does_not_need_account(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        event = SimpleNamespace(plain_result=lambda x: x)
        result = [x async for x in plugin.nikke(event, "塔层", "极乐净土", "1")]
        self.assertEqual(len(result), 1)
        self.assertIn("7,740", result[0])
