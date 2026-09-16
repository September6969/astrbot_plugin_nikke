# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.registries.static import StaticDataRegistry
from astrbot_plugin_nikke.features.character.replica import replica_font
from astrbot_plugin_nikke.ui.primitives import CardRenderer


class AssetsRefactorIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.assets_dir = cls.root / "assets"
        cls.fonts_dir = cls.root / "fonts"

    def test_assets_fonts_structure(self):
        """验证 assets/fonts/ 包含全套所需字体，且与根目录 fonts/ 保持完全一致。"""
        assets_fonts = self.assets_dir / "fonts"
        self.assertTrue(assets_fonts.is_dir(), "assets/fonts 目录必须存在")

        expected_fonts = ["NotoSansHans-Medium.otf", "NotoSansHans-Regular.otf", "ReplicaSans.otf"]
        for font_name in expected_fonts:
            asset_font = assets_fonts / font_name
            root_font = self.fonts_dir / font_name
            self.assertTrue(asset_font.is_file(), f"assets/fonts/{font_name} 必须存在")
            self.assertTrue(root_font.is_file(), f"fonts/{font_name} 必须保留以保证向后兼容")
            self.assertEqual(
                hashlib.sha256(asset_font.read_bytes()).hexdigest(),
                hashlib.sha256(root_font.read_bytes()).hexdigest(),
                f"字体文件哈希必须一致: {font_name}",
            )

    def test_assets_data_structure(self):
        """验证 assets/data/ 包含所有已规范化的数据清单，哈希与主清单一致。"""
        data_dir = self.assets_dir / "data"
        self.assertTrue(data_dir.is_dir(), "assets/data 目录必须存在")

        expected_data_files = [
            "campaign_stages.json",
            "campaign_stages.source.json",
            "character_aliases.json",
            "character_catalog.json",
            "character_master.json",
            "character_weapon_bases.json",
            "costumes.json",
            "cubes.json",
            "equipment.json",
            "face_anchors.json",
            "favorite_items.json",
            "overload_tiers.json",
            "raid_raid_list.json",
            "registry_manifest.json",
            "remote_sources.json",
            "sources.json",
            "spine_manifest.json",
            "spine_manifest.schema.json",
            "state_effects.json",
            "tower_floors.json",
            "voice_poke_map.json",
        ]
        for name in expected_data_files:
            data_file = data_dir / name
            self.assertTrue(data_file.is_file(), f"assets/data/{name} 必须存在")
            legacy_file = self.assets_dir / name
            if legacy_file.is_file():
                self.assertEqual(
                    hashlib.sha256(data_file.read_bytes()).hexdigest(),
                    hashlib.sha256(legacy_file.read_bytes()).hexdigest(),
                    f"数据文件哈希必须一致: {name}",
                )

    def test_assets_icons_structure(self):
        """验证 assets/icons/ 包含 cube, favorite, currency 子目录。"""
        icons_dir = self.assets_dir / "icons"
        self.assertTrue(icons_dir.is_dir(), "assets/icons 目录必须存在")
        for sub in ("cube", "favorite", "currency"):
            sub_dir = icons_dir / sub
            self.assertTrue(sub_dir.is_dir(), f"assets/icons/{sub} 必须存在")
            self.assertGreater(len(list(sub_dir.iterdir())), 0, f"assets/icons/{sub} 不可为空")

    def test_static_registry_loads_from_data_and_fallback(self):
        """验证 StaticDataRegistry 优先从 data/ 读取，并在无 data/ 时平滑 fallback。"""
        # 1. 正常从规范目录加载
        reg = StaticDataRegistry(self.assets_dir)
        self.assertTrue(reg.is_valid, f"StaticDataRegistry 加载失败: {reg.errors}")

        # 2. 从仅包含 data/ 子目录的临时目录加载
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            td_data = td_path / "data"
            td_data.mkdir(parents=True)
            for f in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json", "costumes.json"):
                (td_data / f).write_bytes((self.assets_dir / "data" / f).read_bytes())
            reg_isolated = StaticDataRegistry(td_path)
            self.assertTrue(reg_isolated.is_valid, f"仅 data/ 结构下 StaticDataRegistry 应当有效: {reg_isolated.errors}")

    def test_card_renderer_resolves_fonts_from_both_locations(self):
        """验证 CardRenderer 支持传入根目录 fonts 或 assets/fonts。"""
        with tempfile.TemporaryDirectory() as td:
            renderer_root = CardRenderer(td, self.fonts_dir)
            self.assertTrue(Path(renderer_root.regular_path).is_file())

            renderer_assets = CardRenderer(td, self.assets_dir / "fonts")
            self.assertTrue(Path(renderer_assets.regular_path).is_file())

    def test_replica_font_resolution(self):
        """验证 replica_font 能正常读取 ReplicaSans.otf 并返回 data URI。"""
        uri = replica_font()
        self.assertIsNotNone(uri)
        self.assertTrue(uri.startswith("data:font/otf;base64,"))

    def test_asset_manager_loads_icons_from_structured_path(self):
        """验证 AssetManager 能够从 assets/icons/ 载入图标。"""
        with tempfile.TemporaryDirectory() as td:
            am = AssetManager(cache_dir=td, asset_dir=self.assets_dir)
            icon = am.get_currency_icon(2000)
            self.assertIsNotNone(icon)
            self.assertIsInstance(icon, Image.Image)


if __name__ == "__main__":
    unittest.main()
