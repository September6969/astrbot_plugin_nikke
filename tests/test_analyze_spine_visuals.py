# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.scripts.analyze_spine_visuals import analyze


class AnalyzeSpineVisualsTests(unittest.TestCase):
    def test_marks_empty_png_as_suspect_without_claiming_visual_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rendered = root / "rendered"
            rendered.mkdir()
            Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(rendered / "c001.png")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"assets": {"c001": {"rendered_png": "c001.png", "runtime_version": "4.0"}}}), encoding="utf-8")
            report = analyze(manifest, rendered, root / "out", {"c001": "测试"})
            self.assertFalse(report["visual_validated"])
            self.assertEqual(report["suspect_count"], 1)
            self.assertIn("VISUAL_EMPTY", report["suspects"][0]["suspects"])
            self.assertTrue((root / "out" / "spine_visual_suspects.json").is_file())

    def test_marks_fragmented_alpha_as_suspect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rendered = root / "rendered"
            rendered.mkdir()
            image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            for x in range(0, 128, 16):
                for y in range(0, 128, 16):
                    image.putpixel((x, y), (255, 255, 255, 255))
            image.save(rendered / "c002.png")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"assets": {"c002": {"rendered_png": "c002.png"}}}), encoding="utf-8")
            report = analyze(manifest, rendered, root / "out", {})
            self.assertIn("VISUAL_ALPHA_FRAGMENTED", report["suspects"][0]["suspects"])
            self.assertLess(report["suspects"][0]["metrics"]["largest_alpha_component_ratio"], 0.5)
