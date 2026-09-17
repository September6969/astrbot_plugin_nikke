# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from pathlib import Path

from astrbot_plugin_nikke.features.character.costume_asset_resolver import CostumeAssetResolver


class CostumeAssetResolverTests(unittest.TestCase):
    def setUp(self):
        self.mapping_path = Path(__file__).resolve().parents[1] / "assets" / "mappings" / "costume_assets.json"
        self.resolver = CostumeAssetResolver(self.mapping_path)

    def test_resolver_loads_default_catalog_with_costumes(self):
        self.assertGreaterEqual(self.resolver.total_characters, 200)
        self.assertGreaterEqual(self.resolver.total_costumes, 170)

    def test_resolve_default_costume(self):
        for term in (None, 0, "0", "default", "默认", "原皮", ""):
            with self.subTest(costume_id=term):
                res = self.resolver.resolve("90", term)
                self.assertTrue(res.exact_match)
                self.assertIsNone(res.fallback_reason)
                self.assertEqual(res.spine_asset_id, "c090")
                self.assertEqual(res.si_asset_key, "si_c090_00_s")

    def test_resolve_known_costume(self):
        # 90 号角色拥有 30016 服装 (Office Therapy, c090_02)
        res = self.resolver.resolve("90", "30016")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.costume_id, "30016")
        self.assertEqual(res.spine_asset_id, "c090_02")
        self.assertEqual(res.si_asset_key, "si_c090_02_s")

    def test_unknown_costume_never_marked_as_exact_match(self):
        # 传入未知的 costume_id
        res = self.resolver.resolve("90", "999999")
        self.assertFalse(res.exact_match)
        self.assertEqual(res.fallback_reason, "unknown_costume")
        self.assertEqual(res.spine_asset_id, "c090")

    def test_owner_mismatch_costume_never_marked_as_exact_match(self):
        # 30016 属于 90，若作为 102 (Maxwell) 的皮肤传入，应被拒绝并标记为 owner_mismatch
        res = self.resolver.resolve("102", "30016")
        self.assertFalse(res.exact_match)
        self.assertEqual(res.fallback_reason, "owner_mismatch")
        self.assertEqual(res.spine_asset_id, "c102")

    def test_unknown_character_returns_not_exact(self):
        res = self.resolver.resolve("888888", "30016")
        self.assertFalse(res.exact_match)
        self.assertIn(res.fallback_reason, ("unknown_character", "owner_mismatch"))
