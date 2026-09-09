import unittest

from astrbot_plugin_nikke.character_stat_calculator import (
    CharacterStatCalculator,
    CharacterStatTables,
)


def verified_tables():
    return CharacterStatTables(
        level_stats={
            "statEnhance": {
                "grade_ratio": 100,
                "grade_hp": 10,
                "grade_attack": 2,
                "grade_defence": 1,
                "core_hp": 100,
                "core_attack": 200,
                "core_defence": 300,
            },
            "curves": {
                "attacker": {
                    "hp": [90, 100], "atk": [45, 50],
                    "defByWeapon": {weapon: [18, 20] for weapon in ("AR", "MG", "RL", "SG", "SMG", "SR")},
                },
            },
        },
        research_table=[
            {"id": "1001", "hp": 1, "attack": 2, "defence": 1},
            {"id": "1101", "hp": 1, "attack": 2, "defence": 1},
            {"id": "1201", "hp": 1, "attack": 2, "defence": 1},
        ],
        attractive_table=[{
            "attractive_level": 1,
            "attacker_hp_rate": 5,
            "attacker_attack_rate": 4,
            "attacker_defence_rate": 3,
        }],
        equipment_table=[
            {"id": str(index), "stat": [
                {"stat_type": "Hp", "stat_value": 10},
                {"stat_type": "Atk", "stat_value": 5},
                {"stat_type": "Defence", "stat_value": 2},
            ]}
            for index in range(1, 5)
        ],
        cube_records={"cube": {"hp": [1, 2], "atk": [2, 3], "def": [1, 1]}},
        favorite_records={"favorite": {"hp": [3, 4], "atk": [4, 5], "def": [2, 2]}},
        verified=True,
        source_ref="https://github.com/ExiaProject/ExiaInvasion",
        checked_at="2026-09-09",
    )


class CharacterStatCalculatorTests(unittest.TestCase):
    def test_missing_verified_tables_returns_all_values_unavailable(self):
        result = CharacterStatCalculator().calculate({}, None)
        self.assertEqual((result.hp, result.attack, result.defense), (None, None, None))
        self.assertEqual(result.hp_source, "unavailable_missing_input")

    def test_complete_inputs_calculate_in_documented_order(self):
        calculator = CharacterStatCalculator(verified_tables())
        result = calculator.calculate({
            "class_name": "Attacker",
            "corporation": "ELYSION",
            "weapon_type": "AR",
            "level": 2,
            "grade": 3,
            "core": 2,
            "bond_level": 1,
            "research_levels": {"general": 1, "attacker": 1, "elysion": 1},
            "equipment": [
                {"tid": str(index), "level": 1, "corporation_type": "ELYSION"}
                for index in range(1, 5)
            ],
            "cube": {"tid": "cube", "level": 2},
            "favorite_item": {"tid": "favorite", "level": 1},
        })
        self.assertEqual((result.hp, result.attack, result.defense), (206, 106, 46))
        self.assertEqual(result.hp_source, "calculated_verified")

    def test_partial_equipment_input_does_not_return_partial_estimate(self):
        calculator = CharacterStatCalculator(verified_tables())
        result = calculator.calculate({
            "class_name": "Attacker", "corporation": "ELYSION", "weapon_type": "AR",
            "level": 2, "grade": 0, "core": 0,
            "research_levels": {"general": 0, "attacker": 0, "elysion": 0},
            "equipment": [{"tid": "1", "level": 1}],
        })
        self.assertEqual((result.hp, result.attack, result.defense), (None, None, None))
        self.assertIn("四件装备", result.reason)

