# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.asset_manager import AssetManager, AssetResult
from astrbot_plugin_nikke.card_models import SpineBundle


class VisualAssetManagerTests(unittest.TestCase):
    def setUp(self):
        self.assets_dir = Path(__file__).resolve().parents[1] / "assets"

    def test_get_character_icon_local_hit(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = AssetManager(td, self.assets_dir, remote=False)
            try:
                res = mgr.get_character_asset(10, kind="icon")
                self.assertIsInstance(res, AssetResult)
                self.assertTrue(res.exact_match)
                self.assertEqual(res.requested_kind, "icon")
                self.assertEqual(res.resolved_kind, "icon")
                self.assertIsNotNone(res.image)
                self.assertEqual(res.image.size, (128, 128))

                # 便捷方法测试
                icon_img = mgr.get_character_icon(10)
                self.assertEqual(icon_img.size, (128, 128))
            finally:
                mgr.close()

    def test_get_character_asset_costume_rendered_hit(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = AssetManager(td, self.assets_dir, remote=False)
            try:
                # 10005 (Rapi Classic Vacation) 具有本地预渲染立绘
                res = mgr.get_character_asset(10, "10005", kind="fullbody")
                self.assertTrue(res.exact_match)
                self.assertIsNone(res.fallback_reason)
                self.assertEqual(res.requested_kind, "fullbody")
                self.assertEqual(res.resolved_kind, "fullbody")
                self.assertIsNotNone(res.image)
                self.assertGreater(res.image.width, 200)
                self.assertGreater(res.image.height, 400)
            finally:
                mgr.close()

    def test_get_character_asset_costume_fullbody_missing_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = AssetManager(td, self.assets_dir, remote=False)
            try:
                # 30037 (Helm costume) 缺少专用 fullbody，降级到默认
                res = mgr.get_character_asset(352, "30037", kind="fullbody")
                self.assertFalse(res.exact_match)
                self.assertEqual(res.fallback_reason, "costume_fullbody_missing")
                self.assertEqual(res.requested_kind, "fullbody")
                self.assertIsNotNone(res.image)
            finally:
                mgr.close()

    def test_get_character_spine_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = AssetManager(td, self.assets_dir, remote=False)
            try:
                # 10005 具备 Spine Bundle
                res = mgr.get_character_asset(10, "10005", kind="spine")
                self.assertTrue(res.exact_match)
                self.assertIsNotNone(res.bundle)
                self.assertIsInstance(res.bundle, SpineBundle)
                self.assertEqual(res.bundle.format, "skel")
                self.assertIn("spine/c010_03/c010_02.png", res.bundle.textures)

                # 便捷方法测试
                bundle = mgr.get_character_spine(10, "10005")
                self.assertIsNotNone(bundle)
                self.assertEqual(bundle.format, "skel")
            finally:
                mgr.close()

    def test_costume_portrait_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = AssetManager(td, self.assets_dir, remote=False)
            try:
                # 正常皮肤
                res = mgr.get_costume_portrait("10", "10005")
                self.assertTrue(res.exact_match)
                self.assertIsNone(res.fallback_reason)

                # 未知皮肤
                res_unknown = mgr.get_costume_portrait("10", "999999")
                self.assertFalse(res_unknown.exact_match)
                self.assertEqual(res_unknown.fallback_reason, "unknown_costume")

                # 所有者不匹配
                res_mismatch = mgr.get_costume_portrait("102", "10005")
                self.assertFalse(res_mismatch.exact_match)
                self.assertIn(res_mismatch.fallback_reason, ("owner_mismatch", "costume_owner_mismatch"))

                # 通过新接口验证精确的 costume_owner_mismatch
                res_visual = mgr.get_character_asset("102", "10005", kind="fullbody")
                self.assertFalse(res_visual.exact_match)
                self.assertEqual(res_visual.fallback_reason, "costume_owner_mismatch")
            finally:
                mgr.close()
