import hashlib
import unittest
from pathlib import Path

from astrbot_plugin_nikke.card_builder import CharacterCardBuilder
from astrbot_plugin_nikke.state_effect_registry import StateEffectRegistry
from astrbot_plugin_nikke.tests.test_card_builder import load_fixture


def record(**overrides):
    base = {
        "option_id": "7000915",
        "state_effect_id": "7000915",
        "group_id": "70009",
        "function_type": "StatChargeDamage",
        "label": "蓄力伤害",
        "value_kind": "percent",
        "value_divisor": 10000,
        "locale": "zh-CN",
        "source_url": "https://www.blablalink.com/equip_table.json",
        "source_sha256": hashlib.sha256(b"verified-equip-table").hexdigest(),
        "checked_at": "2026-09-09",
    }
    base.update(overrides)
    return base


class StateEffectRegistryTests(unittest.TestCase):
    def test_source_backed_formatter_is_used_by_builder(self):
        registry = StateEffectRegistry.from_records([record()])
        self.assertTrue(registry.is_valid)
        metadata = registry.resolve("7000915", "StatChargeDamage")
        self.assertEqual(metadata.label, "蓄力伤害")
        self.assertEqual(metadata.format_value(1463), (0.1463, "percent"))

        fixture = load_fixture()
        card = CharacterCardBuilder(state_effect_registry=registry).build(
            account={}, directory=fixture["directory"],
            payload={
                "roster_item": fixture["roster_item"],
                "detail": fixture["character_details"][0],
                "state_effects": fixture["state_effects"],
            },
            fetched_at="test", plugin_version="test",
        )
        option = card.equipment["torso"].options[2]
        self.assertEqual(option.display_name, "蓄力伤害")
        self.assertEqual(option.unit, "percent")
        self.assertAlmostEqual(option.value, 0.1463)

    def test_missing_source_or_ambiguous_function_type_is_not_accepted(self):
        missing_source = record(source_sha256="bad")
        registry = StateEffectRegistry.from_records([missing_source])
        self.assertFalse(registry.is_valid)
        self.assertIsNone(registry.resolve("7000915", "StatChargeDamage"))

        first = record(option_id="7000001", label="A")
        second = record(option_id="7000002", label="B")
        registry = StateEffectRegistry.from_records([first, second])
        self.assertIsNone(registry.resolve("unknown", "StatChargeDamage"))

    def test_empty_checked_in_registry_remains_pending(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "state_effects.json"
        registry = StateEffectRegistry.from_file(path)
        self.assertTrue(registry.is_valid)
        self.assertEqual(registry.entries, ())


if __name__ == "__main__":
    unittest.main()
