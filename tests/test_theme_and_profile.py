# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from astrbot_plugin_nikke.ui.theme import (
    CharacterTheme,
    character_theme,
    _extract_portrait_colors,
    _extract_portrait_palette,
    _darken,
    _lighten,
)
from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
from astrbot_plugin_nikke.features.profile.models import ProfileDashboardData
from PIL import Image
import tempfile


class AutoThemeTests(unittest.TestCase):
    def test_default_theme_when_no_inputs(self):
        theme = character_theme(None, None)
        self.assertIsInstance(theme, CharacterTheme)
        self.assertTrue(theme.background.startswith("#"))
        self.assertTrue(theme.primary.startswith("#"))

    def test_corporation_changes_accent(self):
        tetra = character_theme("TETRA", None)
        elysion = character_theme("ELYSION", None)
        self.assertNotEqual(tetra.accent, elysion.accent)

    def test_element_tints_accent(self):
        no_elem = character_theme("TETRA", None)
        fire = character_theme("TETRA", "Fire")
        self.assertNotEqual(no_elem.accent, fire.accent)

    def test_portrait_extract_returns_none_for_tiny_image(self):
        img = Image.new("RGB", (2, 2), (0, 0, 0))
        dominant, saturated = _extract_portrait_colors(img)
        self.assertIsNone(dominant)
        self.assertFalse(saturated)

    def test_portrait_extract_returns_none_for_none(self):
        dominant, saturated = _extract_portrait_colors(None)
        self.assertIsNone(dominant)
        self.assertFalse(saturated)

    def test_portrait_extract_finds_dominant_color(self):
        img = Image.new("RGB", (32, 32), (200, 50, 50))
        dominant, saturated = _extract_portrait_colors(img)
        self.assertIsNotNone(dominant)
        self.assertTrue(saturated)

    def test_portrait_influences_theme(self):
        plain = character_theme("TETRA", "Fire")
        img = Image.new("RGB", (32, 32), (50, 200, 50))
        with_portrait = character_theme("TETRA", "Fire", img)
        self.assertNotEqual(plain.accent, with_portrait.accent)

    def test_transparent_pixels_do_not_pollute_portrait_palette(self):
        img = Image.new("RGBA", (32, 32), (255, 0, 0, 0))
        for x in range(8, 24):
            for y in range(8, 24):
                img.putpixel((x, y), (20, 180, 80, 255))
        dominant, secondary, dark, saturated = _extract_portrait_palette(img)
        self.assertTrue(saturated)
        self.assertIsNotNone(dominant)
        self.assertIsNotNone(secondary)
        self.assertIsNotNone(dark)

    def test_abnormal_uses_deep_purple_black_background(self):
        theme = character_theme("ABNORMAL", "Iron", Image.new("RGB", (32, 32), (160, 40, 180)))
        red, green, blue = tuple(int(theme.background[index:index + 2], 16) for index in (1, 3, 5))
        self.assertLess(max(red, green, blue), 70)
        self.assertGreaterEqual(blue, green)

    def test_darken_and_lighten_round_trip(self):
        original = "#808080"
        darker = _darken(original, 0.5)
        lighter = _lighten(darker, 0.5)
        r_orig = int(original[1:3], 16)
        r_light = int(lighter[1:3], 16)
        self.assertGreater(r_light, int(darker[1:3], 16))

    def test_theme_is_frozen(self):
        theme = character_theme("TETRA", "Fire")
        with self.assertRaises(AttributeError):
            theme.primary = "#000000"


class ProfileBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = ProfileBuilder()

    def test_basic_fields_from_profile(self):
        result = self.builder.build(
            account={"area_id": "3"},
            basic={
                "nickname": "TestCommander",
                "progress_normal_campaign": "35-1",
                "progress_hard_campaign": "20-3",
            },
            outpost={"synchro_level": 200, "outpost_battle_level": 15},
            roster=[{"lv": 100, "combat": 50000}, {"lv": 200, "combat": 80000}],
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.7",
        )
        self.assertEqual(result.commander_name, "TestCommander")
        self.assertEqual(result.area_id, "3")
        self.assertEqual(result.synchro_level, 200)
        self.assertEqual(result.outpost_battle_level, 15)
        self.assertEqual(result.normal_campaign, "35-1")
        self.assertEqual(result.hard_campaign, "20-3")
        self.assertEqual(result.character_count, 2)
        self.assertEqual(result.max_level, 200)
        self.assertEqual(result.max_combat, 80000)

    def test_legacy_field_names_are_supported(self):
        result = self.builder.build(
            account={},
            basic={
                "progress_campaign_normal": "10-1",
                "progress_campaign_hard": "5-1",
            },
            outpost={},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.normal_campaign, "10-1")
        self.assertEqual(result.hard_campaign, "5-1")

    def test_empty_roster_returns_zeros(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.character_count, 0)
        self.assertIsNone(result.max_level)
        self.assertIsNone(result.max_combat)

    def test_roster_failure_preserves_basic_character_and_costume_count_and_sets_maxes_none(self):
        # 120 名角色 + 15 套时装 + roster failure
        basic = {
            "nickname": "指挥官",
            "character_count": 120,
            "character_costume_count": 15,
            "icon_id": "secret_icon_999",
        }
        result = self.builder.build(
            account={"area_id": "1"},
            basic=basic,
            outpost={},
            roster=None,
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.character_count, 120)
        self.assertEqual(result.character_costume_count, 15)
        self.assertIsNone(result.max_level)
        self.assertIsNone(result.max_combat)

    def test_none_synchro_level_becomes_none(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={"synchro_level": None},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertIsNone(result.synchro_level)

    def test_zero_synchro_level_is_valid(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={"synchro_level": "0"},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.synchro_level, 0)

    def test_zero_outpost_battle_level_is_valid(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={"outpost_battle_level": 0},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.outpost_battle_level, 0)

    def test_commander_name_fallback_chain(self):
        result = self.builder.build(
            account={"role_name": "Fallback"},
            basic={},
            outpost={},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.commander_name, "Fallback")

    def test_commander_name_default(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={},
            roster=[],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.commander_name, "指挥官")

    def test_max_combat_is_single_character_max(self):
        result = self.builder.build(
            account={},
            basic={},
            outpost={},
            roster=[
                {"lv": 100, "combat": 30000},
                {"lv": 150, "combat": 60000},
                {"lv": 120, "combat": 45000},
            ],
            fetched_at="test",
            plugin_version="test",
        )
        self.assertEqual(result.max_combat, 60000)
        self.assertEqual(result.max_level, 150)




if __name__ == "__main__":
    unittest.main()
