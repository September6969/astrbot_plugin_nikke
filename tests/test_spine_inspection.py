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

    def test_binary_header_reports_major_minor_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas, skeleton = root / "sample.atlas", root / "sample.skel"
            atlas.write_text("one.png\nregion\nsize: 10,20\n", encoding="utf-8")

            # Spine binary 头部是 8 字节 hash、version 字符串，长度使用 varint(length + 1)。
            skeleton.write_bytes(b"12345678\x074.0.47")
            result = inspect(atlas, skeleton, "4.0")
            self.assertEqual(result["status"], "VERSION_MATCH")
            self.assertEqual(result["major_minor"], "4.0")

    def test_atlas_utf8_bom_does_not_turn_page_into_missing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas, skeleton, texture = root / "sample.atlas", root / "sample.json", root / "one.png"
            atlas.write_text("one.png\nsize: 10, 20\nregion\n", encoding="utf-8-sig")
            skeleton.write_text('{"skeleton":{"spine":"4.0.47"}}', encoding="utf-8")
            texture.write_bytes(b"png fixture")
            result = inspect(atlas, skeleton, "4.0")
            self.assertEqual(result["missing_pages"], 0)
