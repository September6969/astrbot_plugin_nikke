# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
from astrbot_plugin_nikke.features.character.registries.overload import OverloadTierRegistry
from astrbot_plugin_nikke.features.character.registries.state_effect import StateEffectRegistry
from astrbot_plugin_nikke.core.assets.fallback_provider import FallbackAssetProvider
from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient, CHARACTER_DETAILS
from astrbot_plugin_nikke._version import PLUGIN_VERSION


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "character_details_sanitized.json"


def make_builder(*, state_effect_registry=None, overload_tier_registry=None, unknown_ol_inventory=None):
    assets = Path(__file__).resolve().parents[1] / "assets"
    state_effect_path = assets / "data" / "state_effects.json"
    if not state_effect_path.is_file():
        state_effect_path = assets / "state_effects.json"
    overload_tier_path = assets / "data" / "overload_tiers.json"
    if not overload_tier_path.is_file():
        overload_tier_path = assets / "overload_tiers.json"
    return CharacterCardBuilder(
        state_effect_registry=(
            state_effect_registry
            if state_effect_registry is not None
            else StateEffectRegistry.from_file(state_effect_path)
        ),
        overload_tier_registry=(
            overload_tier_registry
            if overload_tier_registry is not None
            else OverloadTierRegistry.from_file(overload_tier_path)
        ),
        unknown_ol_inventory=unknown_ol_inventory,
    )


def fallback_card_assets(card):
    return FallbackAssetProvider().resolve_character_assets(card)


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_card():
    fixture = load_fixture()
    payload = {
        "roster_item": fixture["roster_item"],
        "detail": fixture["character_details"][0],
        "state_effects": fixture["state_effects"],
    }
    return make_builder().build(
        account={"nickname": "测试指挥官"},
        directory=fixture["directory"],
        payload=payload,
        fetched_at="2026-09-05 05:30",
        plugin_version=PLUGIN_VERSION,
    )


class CharacterCardBuilderTests(unittest.TestCase):
    def test_builder_uses_injected_ports_without_file_or_identity_adapters(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "features" / "character" / "builder.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        imported_modules = {
            node.module or ""
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(any(name.startswith(".registries") for name in imported_modules))
        self.assertNotIn(".identity", imported_modules)
        self.assertNotIn("pathlib", imported_modules)
        self.assertNotIn(
            "astrbot_plugin_nikke.features.character.ol_unknown_inventory",
            imported_modules,
        )
        init_parameters = inspect.signature(CharacterCardBuilder.__init__).parameters
        self.assertIn("state_effect_registry", init_parameters)
        self.assertIn("overload_tier_registry", init_parameters)
        self.assertIn("unknown_ol_inventory", init_parameters)
        self.assertNotIn("unknown_ol_inventory_path", init_parameters)

    def test_costume_id_is_preserved_for_static_portrait_resolution(self):
        fixture = load_fixture()
        fixture["roster_item"]["costume_id"] = "skin_01"
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": fixture["character_details"][0], "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(card.costume_id, "skin_01")

    def test_costume_resolution_detail_costume_tid_wins_over_roster(self):
        fixture = load_fixture()
        fixture["roster_item"]["costume_id"] = 0
        detail = dict(fixture["character_details"][0])
        detail["costume_tid"] = 30049
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": detail, "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(card.costume_id, 30049)

    def test_costume_resolution_detail_overrides_stale_roster_costume_id(self):
        fixture = load_fixture()
        fixture["roster_item"]["costume_id"] = 99999
        detail = dict(fixture["character_details"][0])
        detail["costume_tid"] = 30049
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": detail, "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(card.costume_id, 30049)

    def test_costume_resolution_default_when_both_zero(self):
        fixture = load_fixture()
        fixture["roster_item"]["costume_id"] = 0
        detail = dict(fixture["character_details"][0])
        detail["costume_tid"] = 0
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": detail, "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertIn(card.costume_id, (0, None))

    def test_costume_resolution_roster_fallback_when_detail_missing_costume(self):
        fixture = load_fixture()
        fixture["roster_item"]["costume_id"] = 30049
        detail = {k: v for k, v in fixture["character_details"][0].items() if "costume" not in k}
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": detail, "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(card.costume_id, 30049)

    def test_display_name_prefers_official_names_over_query_alias(self):
        fixture = load_fixture()
        fixture["directory"]["name_zh_tw"] = "阿爾卡娜"
        fixture["directory"]["name_zh_cn_alias"] = "阿尔卡娜"
        fixture["directory"]["name_cn"] = "阿爾卡娜"
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": fixture["character_details"][0], "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        # 受控简中别名仅用于查询检索，卡片与展示名称严格遵循官方本地化 (zh_cn -> zh_tw/cn -> en -> code)
        self.assertEqual(card.name_cn, "阿爾卡娜")

        # 若存在官方确切 zh-CN 则优先展示
        fixture["directory"]["name_zh_cn"] = "官方简中名"
        card_with_sc = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": fixture["character_details"][0], "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(card_with_sc.name_cn, "官方简中名")

    def test_real_sanitized_fixture_preserves_four_equipment_slots(self):
        card = build_card()
        self.assertEqual(set(card.equipment), {"head", "torso", "arm", "leg"})
        self.assertTrue(all(item.equipped for item in card.equipment.values()))
        self.assertEqual(card.equipment["head"].equipment_id, "3111001")
        self.assertEqual(card.equipment["leg"].level, 3)

    def test_options_stay_in_their_original_slots(self):
        card = build_card()
        head = card.equipment["head"].options
        torso = card.equipment["torso"].options
        self.assertEqual([item.raw_type for item in head[:2]], ["StatAtk", "IncElementDmg"])
        self.assertEqual(len(head), 3)
        self.assertEqual([item.position for item in head], [1, 2, 3])
        self.assertEqual(
            [item.raw_type for item in torso],
            ["StatAtk", "StatAmmoLoad", "StatChargeDamage"],
        )

    def test_multiple_function_details_stay_in_one_option_position(self):
        fixture = load_fixture()
        fixture["state_effects"][0]["function_details"].append({
            "function_type": "StatAmmoLoad",
            "function_value": 1000,
            "function_value_type": "Percent",
            "level": 2,
        })
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"roster_item": fixture["roster_item"], "detail": fixture["character_details"][0], "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        option = card.equipment["head"].options[0]
        self.assertEqual(option.position, 1)
        self.assertEqual(len(option.components), 2)
        self.assertEqual(len(card.equipment["head"].options), 3)

    def test_percent_values_and_totals_use_raw_divided_by_10000(self):
        card = build_card()
        attack = card.equipment["head"].options[0]
        self.assertEqual(attack.value, 0.1322)
        totals = {(item.display_name, item.unit): item.value for item in card.option_totals}
        self.assertAlmostEqual(totals[("攻击力增加", "percent")], 0.2644)
        self.assertAlmostEqual(totals[("优越代码伤害增加", "percent")], 0.6365)

    def test_registry_and_fallback_option_values_are_identical(self):
        builder = make_builder()
        func = {
            "function_type": "StatAtk",
            "function_value": 1322,
            "function_value_type": "Percent",
            "level": 8,
        }
        fallback_option = builder._option_from_function(func)
        registry_option = builder._option_from_function_with_registry(func, option_id="7000813")
        self.assertEqual(fallback_option.value, 0.1322)
        self.assertEqual(registry_option.value, 0.1322)
        self.assertEqual(fallback_option.unit, "percent")
        self.assertEqual(registry_option.unit, "percent")
        self.assertEqual(fallback_option.value, registry_option.value)

    def test_ol_tier_registry_supplies_verified_level_when_detail_level_is_missing(self):
        fixture = load_fixture()
        detail = fixture["character_details"][0]
        detail["head_equip_option1_id"] = 7000813
        fixture["state_effects"] = [{
            "id": "7000813",
            "function_details": [{
                "function_type": "StatAtk",
                "function_value": 1322,
                "function_value_type": "Percent",
            }],
        }]
        card = make_builder().build(
            account={},
            directory=fixture["directory"],
            payload={
                "roster_item": fixture["roster_item"],
                "detail": detail,
                "state_effects": fixture["state_effects"],
            },
            fetched_at="test",
            plugin_version="test",
        )

        option = card.equipment["head"].options[0]
        self.assertEqual(option.level, 13)
        self.assertEqual(option.tier, 13)

    def test_unknown_options_are_visible_but_not_summed(self):
        fixture = load_fixture()
        detail = fixture["character_details"][0]
        detail["arm_equip_option3_id"] = 9999999
        fixture["state_effects"].append({
            "id": "9999999",
            "function_details": [{
                "function_type": "StatUnknownFake",
                "function_value": 500,
                "function_value_type": "Percent",
                "level": 1,
            }],
        })
        payload = {
            "roster_item": fixture["roster_item"],
            "detail": detail,
            "state_effects": fixture["state_effects"],
        }
        card = make_builder().build(
            account={"nickname": "测试指挥官"},
            directory=fixture["directory"],
            payload=payload,
            fetched_at="2026-09-05 05:30",
            plugin_version=PLUGIN_VERSION,
        )
        unknown = [
            option
            for equipment in card.equipment.values()
            for option in equipment.options
            if option.unit == "unknown"
        ]
        self.assertTrue(any(item.raw_type == "StatUnknownFake" for item in unknown))
        self.assertEqual(
            [item.display_name for item in unknown if item.raw_type == "StatUnknownFake"],
            ["未知词条 · ID 9999999"],
        )
        self.assertNotIn("未识别词条", {item.display_name for item in card.option_totals})

    def test_common_options_and_negative_charge_time(self):
        card = build_card()
        totals = {item.display_name: item.value for item in card.option_totals}
        self.assertAlmostEqual(totals["最大装弹数增加"], 2.0679)
        self.assertAlmostEqual(totals["蓄力速度增加"], 0.0228)
        self.assertAlmostEqual(totals["蓄力伤害增加"], 0.1463)
        charge_damage_unknown = [
            option
            for equipment in card.equipment.values()
            for option in equipment.options
            if option.raw_type == "StatChargeDamage"
        ]
        self.assertTrue(len(charge_damage_unknown) > 0)
        self.assertTrue(all(item.display_name == "蓄力伤害增加" for item in charge_damage_unknown))
        option = CharacterCardBuilder._option_from_function({
            "function_type": "StatCriticalDamage", "function_value": 688,
            "function_value_type": "Percent",
        })
        self.assertEqual(option.display_name, "暴击伤害增加")
        self.assertAlmostEqual(option.value, 0.0688)

    def test_known_integer_encoded_ol_regressions_keep_name_tier_and_percent(self):
        builder = make_builder()
        cases = {
            "7000909": ("StatChargeDamage", 1040, "蓄力伤害增加", 9, 0.104),
            "7001111": ("StatCritical", 571, "暴击率增加", 11, 0.0571),
            "7001211": ("StatCriticalDamage", 1644, "暴击伤害增加", 11, 0.1644),
        }
        for option_id, (raw_type, raw_value, label, tier, value) in cases.items():
            with self.subTest(option_id=option_id):
                option = builder._option_from_effect(
                    effect_id=option_id,
                    functions=[{
                        "function_type": raw_type,
                        "function_value": raw_value,
                        "function_value_type": "Integer",
                    }],
                    position=1,
                )
                self.assertEqual((option.display_name, option.tier, option.unit), (label, tier, "percent"))
                self.assertAlmostEqual(option.value, value)

    def test_known_ol_function_type_mismatch_keeps_authoritative_identity(self):
        builder = make_builder()
        with self.assertLogs("astrbot_plugin_nikke.card_builder", level="WARNING") as logs:
            option = builder._option_from_effect(
                effect_id="7001211",
                functions=[{
                    "function_type": "StatUnexpected",
                    "function_value": 1644,
                    "function_value_type": "Integer",
                }],
                position=1,
            )
        expected_label = builder.overload_tier_registry.resolve("7001211").label
        self.assertEqual((option.display_name, option.tier, option.unit), (expected_label, 11, "percent"))
        self.assertAlmostEqual(option.value, 0.1644)
        self.assertTrue(any("OL_FUNCTION_TYPE_MISMATCH" in line for line in logs.output))

    def test_unequipped_slot_drops_stale_options_and_totals(self):
        fixture = load_fixture()
        detail = fixture["character_details"][0]
        for slot in ("head", "torso", "arm", "leg"):
            detail[f"{slot}_equip_tid"] = 0
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={"detail": detail, "state_effects": fixture["state_effects"]},
            fetched_at="test", plugin_version="test",
        )
        self.assertFalse(card.option_totals)
        self.assertTrue(all(not item.options for item in card.equipment.values()))

    def test_roster_level_wins_and_optional_stats_remain_missing(self):
        card = build_card()
        self.assertEqual(card.level, 525)
        self.assertEqual(card.combat, 287405)
        self.assertIsNone(card.hp)
        self.assertIsNone(card.attack)
        self.assertIsNone(card.defense)
        self.assertIsNone(card.favorite_item.display_name)
        self.assertIsNone(card.cube.display_name)

    def test_direct_hp_attack_defense_fields_are_not_treated_as_verified(self):
        fixture = load_fixture()
        detail = fixture["character_details"][0]
        detail.update({"hp": "123456", "attack": 789, "defense": 456})
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={
                "roster_item": fixture["roster_item"],
                "detail": detail,
                "state_effects": fixture["state_effects"],
            },
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual((card.hp, card.attack, card.defense), (None, None, None))
        self.assertEqual(card.hp_source, "unavailable_missing_input")

    def test_malformed_required_numeric_fields_degrade_to_zero_without_crashing(self):
        fixture = load_fixture()
        roster = fixture["roster_item"]
        detail = fixture["character_details"][0]
        roster["lv"] = "525.5"
        roster["combat"] = "not-a-number"
        roster["grade"] = "unknown"
        roster["core"] = float("inf")
        detail["skill1_lv"] = True
        detail["skill2_lv"] = "NaN"
        detail["ulti_skill_lv"] = 4.5
        card = make_builder().build(
            account={}, directory=fixture["directory"],
            payload={
                "roster_item": roster,
                "detail": detail,
                "state_effects": fixture["state_effects"],
            },
            fetched_at="test", plugin_version="test",
        )
        self.assertEqual(
            (card.level, card.combat, card.skill1_level, card.skill2_level,
             card.burst_skill_level, card.grade, card.core),
            (0, 0, 0, 0, 0, 0, 0),
        )

    def test_invalid_function_value_is_unknown_instead_of_nan_or_crash(self):
        option = CharacterCardBuilder._option_from_function({
            "function_type": "StatCriticalDamage",
            "function_value": "NaN",
            "function_value_type": "Percent",
        })
        self.assertEqual((option.display_name, option.unit, option.value), ("未识别词条", "unknown", 0))


class CharacterDetailClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_target_name_code_is_requested(self):
        fixture = load_fixture()

        class TargetClient(BlaBlaClient):
            def __init__(self):
                super().__init__(5)
                self.detail_payload = None

            async def get_roster(self, account, include_details=True):
                self.assert_no_details(include_details)
                return [fixture["roster_item"], {"name_code": 9999, "lv": 1}]

            @staticmethod
            def assert_no_details(include_details):
                if include_details:
                    raise AssertionError("单角色查询不应请求全账号详情")

            async def _post(self, path, cookie, payload):
                if path != CHARACTER_DETAILS:
                    raise AssertionError(path)
                self.detail_payload = payload
                return {
                    "code": 0,
                    "data": {
                        "character_details": fixture["character_details"],
                        "state_effects": fixture["state_effects"],
                    },
                }

        client = TargetClient()
        account = {
            "cookie": "cookie-a",
            "game_openid": "openid-a",
            "area_id": "3",
        }
        result = await client.get_character_detail(account, "5101")
        self.assertEqual(client.detail_payload["name_codes"], ["5101"])
        self.assertEqual(result["roster_item"]["lv"], 525)


if __name__ == "__main__":
    unittest.main()
