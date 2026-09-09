"""真实面板样本的离线回放；不是测试期间执行账号访问。"""

from astrbot_plugin_nikke.character_stat_calculator import CharacterStatCalculator, CharacterStatTables


def test_arcana_level_526_matches_user_game_panel():
    # 仅摘录已下载静态表中此样本所需字段，来源与截图 hash 见证据登记。
    tables = CharacterStatTables(
        level_stats={
            "statEnhance": {"grade_ratio": 200, "grade_hp": 3000, "grade_attack": 20,
                            "grade_defence": 100, "core_hp": 200, "core_attack": 200,
                            "core_defence": 200},
            "curves": {"supporter": {"hp": [None] * 525 + [4444355],
                                      "atk": [None] * 525 + [148145],
                                      "defByWeapon": {"RL": [None] * 525 + [28905]}}},
        },
        research_table={"records": [
            {"id": 1001, "hp": 450, "attack": 0, "defence": 0},
            {"id": 1103, "hp": 750, "attack": 0, "defence": 5},
            {"id": 1201, "hp": 0, "attack": 25, "defence": 5},
        ]},
        attractive_table={"records": [{"attractive_level": 30, "supporter_hp_rate": 40997,
                                         "supporter_attack_rate": 1367, "supporter_defence_rate": 273}]},
        equipment_table={"records": [
            {"id": tid, "stat": [{"stat_type": key, "stat_value": value} for key, value in stats]}
            for tid, stats in (
                (3131001, (("Atk", 5012), ("Hp", 54646))),
                (3231001, (("Atk", 911), ("Hp", 177600))),
                (3331001, (("Atk", 3189), ("Defence", 727))),
                (3431001, (("Defence", 1090), ("Hp", 40985))),
            )
        ]},
        verified=True,
    )
    result = CharacterStatCalculator(tables).calculate({
        "class_name": "Supporter", "corporation": "ELYSION", "weapon_type": "RL",
        "level": 526, "grade": 3, "core": 2, "bond_level": 30,
        "research_levels": {"general": 240, "supporter": 119, "elysion": 116},
        "equipment": [{"tid": tid, "level": 0, "corporation_type": 0}
                      for tid in (3131001, 3231001, 3331001, 3431001)],
        "cube": {"tid": 0, "level": 0}, "favorite_item": {"tid": 0, "level": 0},
    })
    assert result.reason is None
    assert (result.hp, result.attack, result.defense) == (5429825, 176926, 35499)
