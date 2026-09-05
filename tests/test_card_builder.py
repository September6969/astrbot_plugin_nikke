# SPDX-License-Identifier: GPL-3.0-or-later

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.card_builder import CharacterCardBuilder
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.client import BlaBlaClient, CHARACTER_DETAILS
from astrbot_plugin_nikke._version import PLUGIN_VERSION


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "character_details_sanitized.json"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_card():
    fixture = load_fixture()
    payload = {
        "roster_item": fixture["roster_item"],
        "detail": fixture["character_details"][0],
        "state_effects": fixture["state_effects"],
    }
    return CharacterCardBuilder().build(
        account={"nickname": "测试指挥官"},
        directory=fixture["directory"],
        payload=payload,
        fetched_at="2026-09-05 05:30",
        plugin_version=PLUGIN_VERSION,
    )


class CharacterCardBuilderTests(unittest.TestCase):
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
        self.assertEqual([item.raw_type for item in head], ["StatAtk", "IncElementDmg"])
        self.assertEqual(
            [item.raw_type for item in torso],
            ["StatAtk", "StatAmmoLoad", "StatChargeDamage"],
        )

    def test_percent_values_and_totals_use_raw_divided_by_10000(self):
        card = build_card()
        attack = card.equipment["head"].options[0]
        self.assertEqual(attack.value, 0.1322)
        totals = {(item.display_name, item.unit): item.value for item in card.option_totals}
        self.assertAlmostEqual(totals[("攻击力增加", "percent")], 0.2644)
        self.assertAlmostEqual(totals[("优越代码伤害增加", "percent")], 0.6365)

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
        card = CharacterCardBuilder().build(
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
        self.assertTrue(all(item.display_name == "未识别词条" for item in unknown))
        self.assertNotIn("未识别词条", {item.display_name for item in card.option_totals})

    def test_common_options_and_negative_charge_time(self):
        card = build_card()
        totals = {item.display_name: item.value for item in card.option_totals}
        self.assertAlmostEqual(totals["最大装弹数增加"], 2.0679)
        self.assertAlmostEqual(totals["蓄力速度增加"], 0.0228)
        self.assertNotIn("蓄力伤害增加", totals)
        charge_damage_unknown = [
            option
            for equipment in card.equipment.values()
            for option in equipment.options
            if option.raw_type == "StatChargeDamage"
        ]
        self.assertTrue(len(charge_damage_unknown) > 0)
        self.assertTrue(all(item.display_name == "未识别词条" for item in charge_damage_unknown))
        option = CharacterCardBuilder._option_from_function({
            "function_type": "StatCriticalDamage", "function_value": 688,
            "function_value_type": "Percent",
        })
        self.assertEqual(option.display_name, "暴击伤害增加")
        self.assertAlmostEqual(option.value, 0.0688)

    def test_unequipped_slot_drops_stale_options_and_totals(self):
        fixture = load_fixture()
        detail = fixture["character_details"][0]
        for slot in ("head", "torso", "arm", "leg"):
            detail[f"{slot}_equip_tid"] = 0
        card = CharacterCardBuilder().build(
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
        self.assertFalse(hasattr(card, "ael"))


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


class CharacterCardRendererTests(unittest.TestCase):
    def test_renderer_outputs_fixed_horizontal_card(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            renderer = CharacterCardRenderer(td, root / "fonts")
            path = renderer.render_character(build_card())
            with Image.open(path) as image:
                self.assertEqual(image.size, (1800, 1000))
                self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
