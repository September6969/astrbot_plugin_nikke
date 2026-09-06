"""授权 metadata、目录逃逸及图片顺序回归。"""
import json
import tempfile
from pathlib import Path
from datetime import date
from unittest import TestCase
from astrbot_plugin_nikke.guide_registry import GuideRegistry


class GuideTests(TestCase):
    def test_order_pagination_and_age(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["b.png", "a.png"]:
                (root / name).write_bytes(b"test")
            row = dict(id="test", category="training", title="测试", files=["b.png", "a.png"],
                       source="local", credit="作者", license="自有", updated_at="2026-01-01", game_version="test")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            registry = GuideRegistry(root)
            self.assertEqual([p.name for p in registry.page("training")[0].files], ["b.png", "a.png"])
            self.assertEqual(registry.page("training", 2), [])
            self.assertIn("可能过期", registry.entries[0].caption(date(2026, 9, 5)))
            row["files"] = ["../outside.png"]
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            with self.assertRaises(ValueError):
                GuideRegistry(root)

    def test_empty_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(GuideRegistry(Path(directory)).page("training"), [])
