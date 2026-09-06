"""命令分页按索引顺序读取，越界不回退到首图。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from astrbot_plugin_nikke.main import NikkePlugin


class GuidePaginationTests(IsolatedAsyncioTestCase):
    async def test_unregistered_directory_is_not_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.plugin_dir = Path(directory)
            root = plugin.plugin_dir / "assets/guides/progression"
            root.mkdir(parents=True)
            (root / "unregistered.png").write_bytes(b"synthetic")
            event = SimpleNamespace(plain_result=lambda x: x, image_result=lambda x: self.fail("不得发送裸目录素材"))
            result = [x async for x in plugin.guide(event, "练度")]
            self.assertIn("占位", result[0])

    async def test_command_second_page_and_invalid_page(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.plugin_dir = Path(directory)
            root = plugin.plugin_dir / "assets/guides"
            root.mkdir(parents=True)
            (root / "synthetic.png").write_bytes(b"synthetic")
            rows = [dict(id=str(i), category="progression", title=f"fixture-{i}", files=["synthetic.png"],
                source="synthetic", credit="test", license="self", updated_at="2026-09-05", game_version="test") for i in range(4)]
            (root / "registry.json").write_text(json.dumps(rows), encoding="utf-8")
            event = SimpleNamespace(plain_result=lambda x: x, image_result=lambda x: "image")
            result = [x async for x in plugin.nikke(event, "攻略", "练度", "2")]
            self.assertIn("第 2/2 页", result[0])
            self.assertTrue(any("fixture-3" in value for value in result))
            self.assertFalse(any("fixture-0" in value for value in result))
            self.assertEqual([x async for x in plugin.nikke(event, "攻略", "练度", "3")], ["该攻略页不存在。"])
            self.assertIn("页码", [x async for x in plugin.nikke(event, "攻略", "练度", "-1")][0])
