"""合成 atlas 验证版本、路径与预算，不需要运行时许可。"""
import tempfile
from pathlib import Path
from unittest import TestCase
from astrbot_plugin_nikke.scripts.inspect_spine_bundle import inspect


class SpineInspectionTests(TestCase):
    def test_multiple_pages_and_version_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas, skeleton = root / "sample.atlas", root / "sample.json"
            atlas.write_text("one.png\nsize: 10, 20\nregion\nsize: 1, 2\n\ntwo.png\nsize: 30, 40\n", encoding="utf-8")
            skeleton.write_text('{"skeleton":{"spine":"4.1.24"}}', encoding="utf-8")
            result = inspect(atlas, skeleton, "4.2")
            self.assertEqual(result["status"], "VERSION_MISMATCH")
            self.assertEqual(result["rgba_bytes_estimate"], 5600)
            self.assertEqual(result["missing_pages"], 2)
            self.assertFalse(result["render_verified"])

    def test_binary_is_unknown_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas, skeleton = root / "sample.atlas", root / "sample.skel"
            atlas.write_text("one.png\nregion\nsize: 10,20\n", encoding="utf-8")
            skeleton.write_bytes(b"synthetic")
            result = inspect(atlas, skeleton)
            self.assertEqual(result["status"], "SPINE_VERSION_UNKNOWN")
            self.assertIsNone(result["rgba_bytes_estimate"])
            atlas.write_text("../outside.png\nsize: 10,20\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                inspect(atlas, skeleton)
