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

        missing_value_source_hash = record(
            value_source_url="https://example.com/formatter.js",
        )
        registry = StateEffectRegistry.from_records([missing_value_source_hash])
        self.assertFalse(registry.is_valid)
        self.assertIsNone(registry.resolve("7000915", "StatChargeDamage"))

        first = record(option_id="7000001", label="A")
        second = record(option_id="7000002", label="B")
        registry = StateEffectRegistry.from_records([first, second])
        self.assertIsNone(registry.resolve("unknown", "StatChargeDamage"))

    def test_function_type_alone_never_resolves(self):
        registry = StateEffectRegistry.from_records([record()])
        self.assertIsNone(registry.resolve("7000999", "StatChargeDamage"))

    def test_live_registry_uses_exact_option_identity_and_explicit_divisor(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "state_effects.json"
        registry = StateEffectRegistry.from_file(path)
        expected = {
            "7000611": ("命中率增加", "percent", 100.0),
            "7001011": ("蓄力速度增加", "percent", 100.0),
            "7001111": ("暴击率增加", "unknown", None),
            "7001211": ("暴击伤害增加", "unknown", None),
        }
        self.assertTrue(registry.is_valid)
        self.assertGreaterEqual(len(registry.entries), 100)
        for option_id, (label, kind, divisor) in expected.items():
            metadata = registry.resolve(option_id, {
                "7000611": "StatAccuracyCircle",
                "7001011": "StatChargeTime",
                "7001111": "StatCritical",
                "7001211": "StatCriticalDamage",
            }[option_id])
            self.assertIsNotNone(metadata)
            self.assertEqual(metadata.label, label)
            self.assertEqual(metadata.value_kind, kind)
            self.assertEqual(metadata.value_divisor, divisor)
            expected_value = (16.44, "percent") if kind == "percent" else (1644.0, "unknown")
            self.assertEqual(metadata.format_value(1644), expected_value)

    def test_integer_live_values_remain_unknown_until_unit_is_confirmed(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "state_effects.json"
        registry = StateEffectRegistry.from_file(path)
        self.assertTrue(registry.is_valid)
        metadata = registry.resolve("7001101", "StatCritical")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.value_kind, "unknown")
        self.assertEqual(metadata.format_value(1644), (1644.0, "unknown"))


if __name__ == "__main__":
    unittest.main()
