"""竖版卡数字口径与有效收益回归。"""
from dataclasses import replace
from decimal import Decimal

from astrbot_plugin_nikke.card_models import EquipmentData, EquipmentOption
from astrbot_plugin_nikke.character_replica import build_summary, rounded_gain, cache_identity
from astrbot_plugin_nikke.tests.test_card_builder import build_card


def example_card():
    card = build_card()
    # 来自用户案例的展示数据，不冒充现场账号快照。
    definitions = {
        "attack": ("StatAttack", "攻击力增加"), "ammo": ("StatAmmoLoad", "最大装弹数增加"),
        "charge": ("StatChargeTime", "蓄力速度增加"), "element": ("StatElementDamage", "优越代码伤害增加"),
        "defense": ("StatDefense", "防御力增加"),
    }
    values = [[("attack", 900, 7), ("ammo", 4017, 4)],
              [("charge", 286, 4), ("ammo", 3195, 2), ("attack", 1181, 11)],
              [("element", 2356, 11), ("defense", 1181, 11), ("charge", 492, 11)],
              [("ammo", 6071, 9), ("charge", 286, 4), ("element", 1655, 6)]]
    card.equipment = {}
    for slot, rows in zip(("head", "torso", "arm", "leg"), values):
        options = [EquipmentOption(definitions[key][0], definitions[key][1], raw / 10000, "percent",
                                   tier=tier, raw_value=raw, effect_group_id=key) for key, raw, tier in rows]
        card.equipment[slot] = EquipmentData(slot, options=options, equipped=True, level=5)
    card.base_ammo = 6
    card.base_charge_seconds = "1"
    card.weapon_base_source = "user-example-conditional-base"
    return card


def test_example_sum_top_four_and_effective_gain():
    result = build_summary(example_card())
    assert result["total"] == 80 and result["complete"]
    assert [row["tier_sum"] for row in result["rows"]] == [19, 18, 17, 15]
    assert [row["value"] for row in result["rows"]] == ["11.00%", "20.81%", "40.11%", "132.83% (+8)"]


def test_unknown_tier_missing_base_and_empty_slots():
    card = example_card()
    card.equipment["head"].options[0].tier = None
    card.weapon_base_source = None
    result = build_summary(card)
    assert result["total"] == 73 and not result["complete"]
    charge = next(row for row in result["rows"] if row["key"] == "charge")
    assert charge["value"] == "10.64%" and charge["note"] == "纸面合计"
    assert all("(+" not in row["value"] for row in result["rows"])
    card.equipment = {}
    assert build_summary(card) == {"rows": [], "total": 0, "complete": True}


def test_ties_are_stable_and_do_not_depend_on_equipment_order():
    card = example_card()
    for item in card.equipment.values():
        for option in item.options:
            option.tier = 1
    first = build_summary(card)
    card.equipment = dict(reversed(list(card.equipment.items())))
    assert build_summary(card) == first


def test_round_half_up_and_identical_tier_grouping():
    options = [EquipmentOption("x", "x", .25, "percent", tier=1)]
    assert rounded_gain(options, Decimal(2), Decimal(1)) == 1
    # 相同两项必须先合并：0.6 + 0.6 合并后为 1，不能分别取整得到 2。
    options = [EquipmentOption("x", "x", .1, "percent", tier=1)] * 2
    assert rounded_gain(options, Decimal(6), Decimal(1)) == 1


def test_cache_identity_changes_with_costume_and_numbers():
    card = example_card()
    assert cache_identity(card) != cache_identity(replace(card, costume_id=30001))
    assert cache_identity(card) != cache_identity(replace(card, combat=card.combat + 1))
