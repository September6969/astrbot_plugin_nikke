# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager, AssetResult


class ResourceLayerAssetManagerTests(unittest.TestCase):
    def setUp(self):
        self.assets_dir = Path(__file__).resolve().parents[1] / "assets"

    def test_skill_icon_local_cache_hit(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            manager = AssetManager(cache_dir, self.assets_dir, remote=False)
            try:
                # 预置本地缓存
                rel = "skills/generic/icn_skill_statreloadtime_01.png"
                target = cache_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (128, 128), "blue").save(target)

                img = manager.get_skill_icon(102, "s1")
                self.assertEqual(img.size, (128, 128))
                self.assertEqual(img.getpixel((10, 10)), (0, 0, 255, 255))
            finally:
                manager.close()

    def test_skill_icon_remote_success_and_cache_writing(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            assets_dir = Path(td) / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.assets_dir / "mappings", assets_dir / "mappings")
            manager = AssetManager(cache_dir, assets_dir, remote=True)
            try:
                # 合法 PNG 字节模拟远程成功响应
                mock_png = io.BytesIO()
                Image.new("RGBA", (128, 128), "red").save(mock_png, format="PNG")
                mock_bytes = mock_png.getvalue()

                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.iter_bytes = MagicMock(return_value=[mock_bytes])

                with patch("astrbot_plugin_nikke.core.assets.downloader.httpx.stream") as mock_stream:
                    mock_stream.return_value.__enter__.return_value = mock_resp

                    img = manager.get_skill_icon(102, "s1")
                    self.assertEqual(img.size, (128, 128))
                    self.assertEqual(img.getpixel((10, 10)), (255, 0, 0, 255))

                    # 验证文件已缓存
                    cached_file = cache_dir / "skills" / "generic" / "icn_skill_statreloadtime_01.png"
                    self.assertTrue(cached_file.is_file())
            finally:
                manager.close()

    def test_skill_icon_corrupted_download_rejected_and_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            assets_dir = Path(td) / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.assets_dir / "mappings", assets_dir / "mappings")
            manager = AssetManager(cache_dir, assets_dir, remote=True)
            try:
                # 模拟远程返回 HTML 404 页面
                bad_bytes = b"<!DOCTYPE html><html><body>404 Not Found</body></html>"
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.iter_bytes = MagicMock(return_value=[bad_bytes])

                with patch("astrbot_plugin_nikke.core.assets.downloader.httpx.stream") as mock_stream:
                    mock_stream.return_value.__enter__.return_value = mock_resp

                    img = manager.get_skill_icon(102, "s1")
                    # 下载失败，应安全走 S1 fallback，且不写入缓存
                    self.assertEqual(img.size, (128, 128))
                    cached_file = cache_dir / "skills" / "generic" / "icn_skill_statreloadtime_01.png"
                    self.assertFalse(cached_file.is_file())
            finally:
                manager.close()

    def test_skill_icon_semantic_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, self.assets_dir, remote=False)
            try:
                s1_fallback = manager.fallback("s1")
                self.assertEqual(s1_fallback.size, (128, 128))

                s2_fallback = manager.fallback("s2")
                self.assertEqual(s2_fallback.size, (128, 128))

                burst_fallback = manager.fallback("burst")
                self.assertEqual(burst_fallback.size, (128, 128))

                # 未知角色回退
                unknown_img = manager.get_skill_icon(999999, "s1")
                self.assertEqual(unknown_img.size, (128, 128))
            finally:
                manager.close()

    def test_get_costume_portrait_returns_asset_result_with_status(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, self.assets_dir, remote=False)
            try:
                # 1. 默认服装 exact_match 为 True
                res_default = manager.get_costume_portrait("90", None)
                self.assertIsInstance(res_default, AssetResult)
                self.assertTrue(res_default.exact_match)
                self.assertIsNone(res_default.fallback_reason)

                # 2. 已知服装 exact_match 为 True
                res_known = manager.get_costume_portrait("90", "30016")
                self.assertTrue(res_known.exact_match)
                self.assertIsNone(res_known.fallback_reason)
                self.assertEqual(res_known.asset_key, "c090_02")

                # 3. 未知服装 exact_match 必须为 False
                res_unknown = manager.get_costume_portrait("90", "999999")
                self.assertFalse(res_unknown.exact_match)
                self.assertEqual(res_unknown.fallback_reason, "unknown_costume")

                # 4. 角色不匹配 exact_match 必须为 False
                res_mismatch = manager.get_costume_portrait("102", "30016")
                self.assertFalse(res_mismatch.exact_match)
                self.assertEqual(res_mismatch.fallback_reason, "owner_mismatch")
            finally:
                manager.close()

    def test_cube_and_favorite_item_getters_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, self.assets_dir, remote=False)
            try:
                # Cube
                cube_img = manager.get_cube_icon(1000301)
                self.assertIn(cube_img.size, ((128, 128), (256, 256)))
                cube_unknown = manager.get_cube_icon(999999)
                self.assertEqual(cube_unknown.size, (128, 128))

                # Favorite item
                fav_img = manager.get_favorite_item_icon(200101)
                self.assertIn(fav_img.size, ((128, 128), (256, 256)))
                fav_unknown = manager.get_favorite_item_icon(999999)
                self.assertEqual(fav_unknown.size, (128, 128))
            finally:
                manager.close()

    def test_ui_icons_getters(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, self.assets_dir, remote=False)
            try:
                # Class
                cls_img = manager.get_class_icon("attacker")
                self.assertEqual(cls_img.mode, "RGBA")
                self.assertGreater(cls_img.width, 0)

                # Manufacturer
                mfg_img = manager.get_manufacturer_icon("elysion")
                self.assertEqual(mfg_img.mode, "RGBA")
                self.assertGreater(mfg_img.width, 0)

                # Rarity
                rar_img = manager.get_rarity_icon("ssr")
                self.assertEqual(rar_img.mode, "RGBA")
                self.assertGreater(rar_img.width, 0)
            finally:
                manager.close()
