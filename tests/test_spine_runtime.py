# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine Runtime 核心契约与骨骼解析器测试。"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from PIL import Image

from astrbot_plugin_nikke.integrations.spine.runtime import (
    SpineBundle,
    SpineSkeletonParser,
    SpineMemoryCache,
    RenderedCharacter,
    detect_spine_version,
)
from astrbot_plugin_nikke.integrations.spine.renderer import SpineRenderer
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpineRenderError


class SpineRuntimeTests(TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _make_json_bundle(self, version="4.1.20", extra_pages=False) -> SpineBundle:
        tex1 = self.root / "tex_00.png"
        Image.new("RGBA", (128, 128), (255, 255, 255, 255)).save(tex1)
        textures = [tex1]

        atlas_content = "tex_00.png\nsize: 128, 128\nformat: RGBA8888\n"
        if extra_pages:
            tex2 = self.root / "tex_01.png"
            Image.new("RGBA", (128, 128), (200, 200, 200, 255)).save(tex2)
            textures.append(tex2)
            atlas_content += "\ntex_01.png\nsize: 128, 128\nformat: RGBA8888\n"

        atlas = self.root / "model.atlas"
        atlas.write_text(atlas_content, encoding="utf-8")

        skel_data = {
            "skeleton": {"spine": version, "x": -500, "y": -200, "width": 1000, "height": 1200},
            "bones": [
                {"name": "root", "x": 0, "y": 0, "rotation": 0},
                {"name": "body", "parent": "root", "x": 0, "y": 400, "rotation": 0},
                {"name": "c_head", "parent": "body", "x": 0, "y": 500, "rotation": 0},
            ],
            "slots": [{"name": "slot_head", "bone": "c_head"}],
            "animations": {"idle": {"duration": 2.0}},
        }
        skel = self.root / "model.json"
        skel.write_text(json.dumps(skel_data), encoding="utf-8")

        return SpineBundle.from_files(
            skeleton=skel,
            atlas=atlas,
            textures=textures,
            spine_version="4.1" if version.startswith("4.1") else "4.0",
        )

    def test_complete_json_bundle_validates_and_parses(self):
        bundle = self._make_json_bundle()
        self.assertEqual(bundle.validate_integrity(), "complete")
        self.assertTrue(bundle.is_valid())

        parsed = SpineSkeletonParser.parse(bundle.skeleton)
        self.assertEqual(parsed.version, "4.1")
        self.assertEqual(len(parsed.bones), 3)
        self.assertIn("c_head", parsed.bone_name_map)

        norm = parsed.compute_normalized_points()
        self.assertIn("c_head", norm)
        # 头部位于顶端附近 (y 翻转，0 在顶部)
        self.assertLess(norm["c_head"][1], 0.35)

    def test_multi_texture_atlas_validation(self):
        bundle = self._make_json_bundle(extra_pages=True)
        self.assertEqual(bundle.validate_integrity(), "complete")
        self.assertEqual(len(bundle.textures), 2)

    def test_missing_texture_fails_validation(self):
        bundle = self._make_json_bundle()
        bundle.textures[0].unlink()
        self.assertEqual(bundle.validate_integrity(), "missing_texture")

    def test_unsupported_spine_version(self):
        bundle = self._make_json_bundle(version="3.8.99")
        bundle_unsupported = SpineBundle.from_files(
            skeleton=bundle.skeleton,
            atlas=bundle.atlas,
            textures=bundle.textures,
            spine_version="3.8",
        )
        self.assertEqual(bundle_unsupported.validate_integrity(), "unsupported_runtime")

    def test_renderer_outputs_transparent_rgba_and_preserves_animation(self):
        bundle = self._make_json_bundle()
        renderer = SpineRenderer()
        result = renderer.render(bundle, animation="idle", time=0.5)

        self.assertIsInstance(result, RenderedCharacter)
        self.assertEqual(result.image.mode, "RGBA")
        self.assertIsNotNone(result.alpha_bbox)
        self.assertEqual(result.source_animation, "idle")
        self.assertEqual(result.source_time, 0.5)
        self.assertIn("c_head", result.skeleton_points)

    def test_memory_cache_deduplicates_renders(self):
        bundle = self._make_json_bundle()
        cache = SpineMemoryCache(max_entries=10, ttl_seconds=60.0)
        renderer = SpineRenderer(cache=cache)

        res1 = renderer.render(bundle, animation="idle", time=0.0)
        res2 = renderer.render(bundle, animation="idle", time=0.0)
        self.assertIs(res1, res2)

    def test_local_binary_c470_bundle_parses_cleanly(self):
        c470_dir = Path(__file__).resolve().parent.parent.parent / "scratch" / "c470_bundle"
        if not (c470_dir / "skel.skel").is_file():
            return
        skel_path = c470_dir / "skel.skel"
        ver = detect_spine_version(skel_path)
        self.assertEqual(ver, "4.1")

        parsed = SpineSkeletonParser.parse(skel_path)
        self.assertEqual(parsed.version, "4.1")
        self.assertGreater(len(parsed.bones), 300)
        self.assertIn("c_head", parsed.bone_name_map)
        self.assertIn("lower_boddy", parsed.bone_name_map)
