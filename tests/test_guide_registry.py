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

    def test_link_only_entry_and_https_whitelist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = dict(id="red", category="red_orbs", title="红球", files=[],
                        source="user", credit="未署名", license="授权", updated_at="2026-09-08", game_version="snapshot")
            base["links"] = ["https://nikkeoutpost.netlify.app/"]
            (root / "registry.json").write_text(json.dumps([base]), encoding="utf-8")
            self.assertEqual(GuideRegistry(root).entries[0].links, ("https://nikkeoutpost.netlify.app/",))
            for bad in ("http://nikkeoutpost.netlify.app/", "https://evil.example/", "https://user:pass@nikkeoutpost.netlify.app/"):
                base["links"] = [bad]
                (root / "registry.json").write_text(json.dumps([base]), encoding="utf-8")
                with self.assertRaises(ValueError):
                    GuideRegistry(root)

    def test_entry_rejects_when_both_files_and_links_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = dict(id="empty", category="test", title="空", files=[], links=[], source="user",
                       credit="未署名", license="授权", updated_at="2026-09-08", game_version="snapshot")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            with self.assertRaises(ValueError):
                GuideRegistry(root)
