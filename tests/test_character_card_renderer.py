import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.features.character.models import EquipmentOption, OptionSummary
from astrbot_plugin_nikke.tests.test_card_builder import fallback_card_assets
from astrbot_plugin_nikke.ui.renderers.character import CharacterCardRenderer
from astrbot_plugin_nikke.ui.theme import character_theme
from astrbot_plugin_nikke.tests.test_card_builder import build_card


class HorizontalRendererTests(unittest.TestCase):
    def test_renderer_uses_the_prepared_costume_portrait(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.costume_id = "skin_01"
            portrait = Image.new("RGBA", (400, 900), "pink")
            assets = fallback_card_assets(card)
            assets.portrait = portrait
            with patch.object(renderer, "draw_character_area", wraps=renderer.draw_character_area) as draw:
                renderer.render_character(card, assets)
            self.assertIs(draw.call_args.args[3], portrait)

    def test_portrait_empty_equipment_and_long_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.name_cn = "爱丽丝：仙境兔女郎与超长角色名称测试"
            card.name_en = "ALICE IN WONDERLAND / LONG CHARACTER NAME"
            card.equipment["head"].equipped = False
            card.equipment["head"].options = [EquipmentOption("secret", "不应出现的残留词条", 1, "percent")]
            card.equipment["arm"].options = []
            card.option_totals = []
            assets = fallback_card_assets(card)
            assets.portrait = Image.new("RGBA", (400, 1000), "pink")
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                path = renderer.render_character(card, assets)
                strings = [str(call.args[2]) for call in text.call_args_list]
            self.assertNotIn("不应出现的残留词条", strings)
            self.assertIn("未装备", strings)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1800, 1000))

    def test_equipped_slot_keeps_three_option_rows_with_empty_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.equipment["head"].options = card.equipment["head"].options[:1]
            assets = fallback_card_assets(card)
            assets.portrait = Image.new("RGBA", (400, 1000), "pink")
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                renderer.render_character(card, assets)
                strings = [str(call.args[2]) for call in text.call_args_list]
            self.assertGreaterEqual(strings.count("空槽"), 2)
            self.assertGreaterEqual(strings.count("—"), 2)

    def test_equipment_rows_draw_verified_tier_badges(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.equipment["head"].options[0].tier = 15
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                renderer.render_character(card, fallback_card_assets(card))
                strings = [str(call.args[2]) for call in text.call_args_list]
            self.assertIn("T15", strings)

    def test_all_summary_entries_are_drawn_and_internal_ids_are_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.option_totals = [OptionSummary(f"超长中文装备词条汇总名称{i}", i / 100, "percent") for i in range(9)]
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                renderer.render_character(card, fallback_card_assets(card))
                strings = [str(call.args[2]) for call in text.call_args_list]
            for summary in card.option_totals:
                self.assertIn(summary.display_name, strings)
            joined = " ".join(strings)
            for forbidden in ["CODE", "RESOURCE", "StatChargeDamage", "100602", "1000304", "OpenID", "Cookie"]:
                self.assertNotIn(forbidden, joined)
