# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from astrbot_plugin_nikke.card_theme import (
    CharacterTheme,
    character_theme,
    _extract_portrait_colors,
    _darken,
    _lighten,
)
from astrbot_plugin_nikke.profile_builder import ProfileBuilder
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer
from astrbot_plugin_nikke.profile_models import ProfileDashboardData
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
        self.assertEqual(result.max_level, 0)
        self.assertEqual(result.max_combat, 0)

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


class ProfileEmptyStateTests(unittest.TestCase):
    def _renderer(self, tmpdir):
        from pathlib import Path
        font_dir = Path(__file__).resolve().parents[1] / "fonts"
        return ProfileCardRenderer(tmpdir, font_dir)

    def test_empty_profile_renders_with_fallback_message(self):
        data = ProfileDashboardData(
            commander_name="\u6307\u6325\u5b98",
            area_id="",
            synchro_level=None,
            outpost_battle_level=None,
            normal_campaign=None,
            hard_campaign=None,
            character_count=0,
            max_level=0,
            max_combat=0,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.7",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = self._renderer(tmpdir)
            path = renderer.render_profile(data)
            self.assertTrue(path.endswith(".png"))
            img = Image.open(path)
            self.assertEqual(img.size[0], 1200)
            self.assertGreater(img.size[1], 200)
            img.close()

    def test_zero_level_shows_in_outpost_section(self):
        data = ProfileDashboardData(
            commander_name="Test",
            area_id="",
            synchro_level=0,
            outpost_battle_level=0,
            normal_campaign=None,
            hard_campaign=None,
            character_count=0,
            max_level=0,
            max_combat=0,
            fetched_at="2026-09-05 12:00",
            plugin_version="0.1.7",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = self._renderer(tmpdir)
            path = renderer.render_profile(data)
            img = Image.open(path)
            self.assertGreater(img.size[1], 200)
            img.close()


if __name__ == "__main__":
    unittest.main()