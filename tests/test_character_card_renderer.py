import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.card_models import EquipmentOption, OptionSummary
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.card_theme import character_theme
from astrbot_plugin_nikke.tests.test_card_builder import build_card


class HorizontalRendererTests(unittest.TestCase):
    def test_costume_is_used_when_renderer_fetches_portrait_directly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            manager = AssetManager(td, td)
            renderer = CharacterCardRenderer(td, root / "fonts", manager)
            card = build_card()
            card.costume_id = "skin_01"
            with patch.object(manager, "get_character_portrait", return_value=Image.new("RGBA", (400, 900), "pink")) as portrait:
                renderer.draw_character_area(
                    Image.new("RGBA", (1800, 1000)), card, character_theme("TETRA", "Fire")
                )
            portrait.assert_called_once_with(card.name_code, card.resource_id, "skin_01")

    def test_portrait_empty_equipment_and_long_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            manager = AssetManager(td, td)
            renderer = CharacterCardRenderer(td, root / "fonts", manager)
            card = build_card()
            card.name_cn = "爱丽丝：仙境兔女郎与超长角色名称测试"
            card.name_en = "ALICE IN WONDERLAND / LONG CHARACTER NAME"
            card.equipment["head"].equipped = False
            card.equipment["head"].options = [EquipmentOption("secret", "不应出现的残留词条", 1, "percent")]
            card.equipment["arm"].options = []
            card.option_totals = []
            with patch.object(manager, "get_character_portrait", return_value=Image.new("RGBA", (400, 1000), "pink")):
                with patch.object(renderer, "_text", wraps=renderer._text) as text:
                    path = renderer.render_character(card)
                    strings = [str(call.args[2]) for call in text.call_args_list]
            self.assertNotIn("不应出现的残留词条", strings)
            self.assertIn("未装备", strings)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1800, 1000))

    def test_equipped_slot_keeps_three_option_rows_with_empty_placeholders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            manager = AssetManager(td, td)
            renderer = CharacterCardRenderer(td, root / "fonts", manager)
            card = build_card()
            card.equipment["head"].options = card.equipment["head"].options[:1]
            with patch.object(manager, "get_character_portrait", return_value=Image.new("RGBA", (400, 1000), "pink")):
                with patch.object(renderer, "_text", wraps=renderer._text) as text:
                    renderer.render_character(card)
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
                renderer.render_character(card)
                strings = [str(call.args[2]) for call in text.call_args_list]
            self.assertIn("T15", strings)

    def test_all_summary_entries_are_drawn_and_internal_ids_are_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(__file__).resolve().parents[1]
            renderer = CharacterCardRenderer(td, root / "fonts")
            card = build_card()
            card.option_totals = [OptionSummary(f"超长中文装备词条汇总名称{i}", i / 100, "percent") for i in range(9)]
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                renderer.render_character(card)
                strings = [str(call.args[2]) for call in text.call_args_list]
            for summary in card.option_totals:
                self.assertIn(summary.display_name, strings)
            joined = " ".join(strings)
            for forbidden in ["CODE", "RESOURCE", "StatChargeDamage", "100602", "1000304", "OpenID", "Cookie"]:
                self.assertNotIn(forbidden, joined)
