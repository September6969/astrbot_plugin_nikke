# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from pathlib import Path

from astrbot_plugin_nikke.character_visual_resolver import CharacterVisualAssetResolver


class CharacterVisualAssetResolverTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1]
        catalog_path = base / "assets" / "mappings" / "costume_visual_assets.json"
        spine_path = base / "assets" / "mappings" / "spine_metadata.json"
        self.resolver = CharacterVisualAssetResolver(catalog_path, spine_path)

    def test_resolver_total_counts(self):
        self.assertEqual(self.resolver.total_characters, 200)
        self.assertEqual(self.resolver.total_costumes, 178)

    def test_default_character_icon_resolved(self):
        res = self.resolver.resolve(10, None, kind="icon")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.requested_kind, "icon")
        self.assertEqual(res.resolved_kind, "icon")
        self.assertTrue(res.is_default)
        self.assertIn("si_c010_00_s.webp", res.logical_key)

    def test_default_character_fullbody_resolved(self):
        # Rapi has Nikke-db FB: FB/c010_00.png
        res = self.resolver.resolve(10, None, kind="fullbody")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.requested_kind, "fullbody")
        self.assertEqual(res.resolved_kind, "fullbody")
        self.assertEqual(res.logical_key, "FB/c010_00.png")

    def test_known_costume_icon_resolved(self):
        # 10005 (Classic Vacation) belongs to Rapi (10)
        res = self.resolver.resolve(10, "10005", kind="icon")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.requested_kind, "icon")
        self.assertEqual(res.resolved_kind, "icon")
        self.assertFalse(res.is_default)
        self.assertEqual(res.costume_id, "10005")
        self.assertIn("si_c010_02_s.webp", res.logical_key)

    def test_known_costume_with_rendered_fullbody_resolved(self):
        # 10005 (Classic Vacation) has rendered fullbody in assets/spine-rendered/c010_03.png
        res = self.resolver.resolve(10, "10005", kind="fullbody")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.requested_kind, "fullbody")
        self.assertEqual(res.resolved_kind, "fullbody")
        self.assertEqual(res.logical_key, "assets/spine-rendered/c010_03.png")

    def test_costume_fullbody_missing_never_marked_exact(self):
        # 30037 belongs to Helm (352), has icon but no fullbody
        res = self.resolver.resolve(352, "30037", kind="fullbody")
        self.assertFalse(res.exact_match)
        self.assertEqual(res.fallback_reason, "costume_fullbody_missing")
        self.assertEqual(res.requested_kind, "fullbody")
        # 降级到默认 fullbody
        self.assertEqual(res.resolved_kind, "fullbody")
        self.assertEqual(res.logical_key, "FB/c352_00.png")

    def test_unknown_costume_never_marked_exact(self):
        res = self.resolver.resolve(10, "999999", kind="fullbody")
        self.assertFalse(res.exact_match)
        self.assertEqual(res.fallback_reason, "unknown_costume")
        self.assertEqual(res.requested_kind, "fullbody")

    def test_owner_mismatch_costume_never_marked_exact(self):
        # 10005 belongs to 10, passing to 102 (Maxwell)
        res = self.resolver.resolve(102, "10005", kind="fullbody")
        self.assertFalse(res.exact_match)
        self.assertEqual(res.fallback_reason, "costume_owner_mismatch")
        self.assertEqual(res.requested_kind, "fullbody")

    def test_spine_resolution(self):
        # 10005 has spine bundle
        res = self.resolver.resolve(10, "10005", kind="spine")
        self.assertTrue(res.exact_match)
        self.assertIsNone(res.fallback_reason)
        self.assertEqual(res.requested_kind, "spine")
        self.assertEqual(res.resolved_kind, "spine")
        self.assertIsNotNone(res.spine_bundle)
        self.assertEqual(res.spine_bundle.format, "skel")
        self.assertIn("spine/c010_03/c010_02.png", res.spine_bundle.textures)

    def test_default_term_normalization(self):
        for term in (None, 0, "0", "default", "默认", "原皮", ""):
            with self.subTest(term=term):
                res = self.resolver.resolve(10, term, kind="icon")
                self.assertTrue(res.is_default)
                self.assertIsNone(res.costume_id)
                self.assertTrue(res.exact_match)
