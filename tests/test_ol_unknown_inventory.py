# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.card_builder import CharacterCardBuilder
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.ol_unknown_inventory import UnknownOlInventory


class UnknownOlInventoryTests(unittest.TestCase):
    def test_unknown_option_keeps_id_visible_and_is_counted_without_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ol_unknown_inventory.json"
            builder = CharacterCardBuilder(unknown_ol_inventory_path=path)
            option = builder._option_from_effect(
                effect_id="7999999",
                functions=[{
                    "function_type": "StatUnmapped", "function_value": 500,
                    "function_value_type": "Integer",
                }],
                position=1,
            )
            self.assertEqual(option.display_name, "未知词条 · ID 7999999")
            self.assertEqual(CharacterCardRenderer._option_value(option), "待确认")

            builder.unknown_ol_inventory.observe(option.option_id, option.raw_type)
            builder.unknown_ol_inventory.observe(option.option_id, option.raw_type)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "UNKNOWN_OL_OPTION")
            self.assertEqual(data["entries"][0]["raw_id"], "7999999")
            self.assertEqual(data["entries"][0]["raw_key"], "StatUnmapped")
            self.assertEqual(data["entries"][0]["occurrence"], 2)
            self.assertNotIn("account", json.dumps(data).casefold())

    def test_invalid_external_values_are_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ol_unknown_inventory.json"
            inventory = UnknownOlInventory(path)
            inventory.observe(True, {"not": "scalar"})
            self.assertFalse(path.exists())
