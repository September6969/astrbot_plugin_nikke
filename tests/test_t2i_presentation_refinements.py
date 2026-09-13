import re
from pathlib import Path
import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.t2i_payloads import (
    format_compact_number,
    display_number,
    CharacterT2IPayloadBuilder,
    ProfileT2IPayloadBuilder,
    T2IAssetResolver,
)
from astrbot_plugin_nikke.static_registry import StaticDataRegistry
from astrbot_plugin_nikke.profile_builder import ProfileBuilder
from astrbot_plugin_nikke.currency_registry import CurrencyRegistry
from astrbot_plugin_nikke.tower_registry import TowerRegistry
from astrbot_plugin_nikke.card_models import (
    CharacterCardData,
    EquipmentData,
    EquipmentOption,
    OptionSummary,
    CubeData,
    FavoriteItemData,
    CostumeSelection,
)

ROOT = Path(__file__).resolve().parents[1]


def render(page, data):
    return Environment().from_string(T2ITemplateLoader().load(page)).render(**data)


class DummyCardAssets:
    def __init__(self):
        self.portrait = None
        self.equipment = {}
        self.favorite_item = None
        self.cube = None
        self.element = None
        self.corporation = None
        self.weapon = None
        self.burst = None


def _make_dummy_character(summary_count):
    option_totals = [
        OptionSummary(display_name=f"词条{i+1}", unit="percent", value=float(i + 1))
        for i in range(summary_count)
    ]
    equipment = {
        slot: EquipmentData(slot=slot, equipment_id="1", level=5, options=[], equipped=True)
        for slot in ("head", "body", "arm", "leg")
    }
    return CharacterCardData(
        commander_name="指挥官",
        fetched_at="2026-09-13 12:00",
        plugin_version="v1.0",
        name_code="c010",
        name_cn="测试角色",
        name_en="TEST",
        resource_id="10",
        costume_id=None,
        rarity="SSR",
        element="Fire",
        weapon="AR",
        burst="III",
        corporation="Elysion",
        level=200,
        combat=100000,
        hp=100000,
        attack=20000,
        defense=3000,
        skill1_level=10,
        skill2_level=10,
        burst_skill_level=10,
        grade=3,
        core=0,
        bond_level=30,
        favorite_item=None,
        cube=None,
        equipment=equipment,
        option_totals=option_totals,
        hp_source="base",
        attack_source="base",
        defense_source="base",
    )


# ==============================================================================
# 1. CHARACTER OL SUMMARY OVERFLOW & DENSITY ADAPTATION
# ==============================================================================

def test_character_ol_density_classes():
    builder = CharacterT2IPayloadBuilder(resolver=T2IAssetResolver())
    assets = DummyCardAssets()

    # <= 6 -> ol-normal
    for count in (0, 1, 5, 6):
        payload = builder.build(_make_dummy_character(count), assets)
        assert payload["ol_density_class"] == "ol-normal", f"count={count}"
        html = render("character", payload)
        assert "ol-summary ol-normal" in html
        assert len(payload["summary"]) == count

    # 7 - 9 -> ol-compact
    for count in (7, 8, 9):
        payload = builder.build(_make_dummy_character(count), assets)
        assert payload["ol_density_class"] == "ol-compact", f"count={count}"
        html = render("character", payload)
        assert "ol-summary ol-compact" in html
        assert len(payload["summary"]) == count

    # >= 10 -> ol-dense
    for count in (10, 12, 16):
        payload = builder.build(_make_dummy_character(count), assets)
        assert payload["ol_density_class"] == "ol-dense", f"count={count}"
        html = render("character", payload)
        assert "ol-summary ol-dense" in html
        assert len(payload["summary"]) == count


def test_character_ol_summary_preserves_all_entries():
    builder = CharacterT2IPayloadBuilder(resolver=T2IAssetResolver())
    assets = DummyCardAssets()
    payload = builder.build(_make_dummy_character(12), assets)
    html = render("character", payload)
    assert len(payload["summary"]) == 12
    for item in payload["summary"]:
        assert item["label"] in html
        assert item["value"] in html


# ==============================================================================
# 2. CHARACTER FAVORITE / CUBE DISPLAY NAME RESOLUTION
# ==============================================================================

def test_static_registry_cube_and_favorite_resolution():
    # Known cubes
    assert StaticDataRegistry.resolve_display_name("cube", 1000301) == "遗迹突击魔方"
    assert StaticDataRegistry.resolve_display_name("cube", "1000302") == "战术突击魔方"
    assert StaticDataRegistry.resolve_display_name("cube", 1000303) == "遗迹巨熊魔方"
    assert StaticDataRegistry.resolve_display_name("cube", "1000304") == "战术巨熊魔方"
    assert StaticDataRegistry.resolve_display_name("cube", 1000314) == "遗迹穿透魔方"
    assert StaticDataRegistry.resolve_display_name("cube", 9999999) is None
    assert StaticDataRegistry.resolve_display_name("cube", None) is None

    # Known favorite items / dolls
    assert StaticDataRegistry.resolve_display_name("favorite", 100101) == "料理指挥官娃娃"
    assert StaticDataRegistry.resolve_display_name("favorite", 100102) == "料理指挥官娃娃（限量版）"
    assert StaticDataRegistry.resolve_display_name("favorite", 100601) == "午睡指挥官娃娃"
    assert StaticDataRegistry.resolve_display_name("favorite", 100602) == "午睡指挥官娃娃（限量版）"
    assert StaticDataRegistry.resolve_display_name("favorite", 200101) == "玩具火车套组"
    assert StaticDataRegistry.resolve_display_name("favorite", 9999999) is None
    assert StaticDataRegistry.resolve_display_name("favorite", None) is None


def test_character_payload_cube_and_favorite_fallback_and_resolved():
    builder = CharacterT2IPayloadBuilder(resolver=T2IAssetResolver())
    assets = DummyCardAssets()

    # 1. Fully equipped with known IDs
    char = _make_dummy_character(3)
    char.cube = CubeData(tid=1000304, level=7, display_name=None)
    char.favorite_item = FavoriteItemData(tid=100602, level=3, display_name=None)
    payload = builder.build(char, assets)
    assert payload["cube"]["name"] == "战术巨熊魔方"
    assert payload["cube"]["level"] == "LV.7"
    assert payload["favorite"]["name"] == "午睡指挥官娃娃（限量版）"
    assert payload["favorite"]["level"] == "LV.3"

    # 2. Equipped but unknown ID
    char.cube = CubeData(tid=9999999, level=1, display_name=None)
    char.favorite_item = FavoriteItemData(tid=8888888, level=1, display_name=None)
    payload = builder.build(char, assets)
    assert payload["cube"]["name"] == "已装备 · 名称 Unknown"
    assert payload["favorite"]["name"] == "已装备 · 名称 Unknown"

    # 3. Not equipped (tid=0)
    char.cube = CubeData(tid=0, level=0, display_name=None)
    char.favorite_item = FavoriteItemData(tid=0, level=0, display_name=None)
    payload = builder.build(char, assets)
    assert payload["cube"]["name"] == "未佩戴魔方"
    assert payload["favorite"]["name"] == "未装配珍藏品/收藏品"

    # 4. None entirely
    char.cube = None
    char.favorite_item = None
    payload = builder.build(char, assets)
    assert payload["cube"]["name"] == "未佩戴魔方"
    assert payload["favorite"]["name"] == "未装配珍藏品/收藏品"


# ==============================================================================
# 3. PROFILE RESOURCES COMPACT UNITS (K/M/B)
# ==============================================================================

def test_format_compact_number():
    # Exact under 1,000
    assert format_compact_number(0) == "0"
    assert format_compact_number(1) == "1"
    assert format_compact_number(999) == "999"

    # Thousands (K)
    assert format_compact_number(1000) == "1.00K"
    assert format_compact_number(1234) == "1.23K"
    assert format_compact_number(12345) == "12.3K"
    assert format_compact_number(123456) == "123K"
    assert format_compact_number(999400) == "999K"

    # Millions (M)
    assert format_compact_number(1000000) == "1.00M"
    assert format_compact_number(1234567) == "1.23M"
    assert format_compact_number(92192744) == "92.2M"
    assert format_compact_number(123456789) == "123M"
    assert format_compact_number(999400000) == "999M"

    # Billions (B)
    assert format_compact_number(1000000000) == "1.00B"
    assert format_compact_number(1050000000) == "1.05B"
    assert format_compact_number(1234567890) == "1.23B"
    assert format_compact_number(12345678901) == "12.3B"

    # None and invalid
    assert format_compact_number(None) == "Unknown"
    assert format_compact_number("invalid") == "invalid"


def test_combat_numbers_remain_exact_not_compact():
    # Combat numbers must retain exact commas, never K/M/B
    assert display_number(1286600) == "1,286,600"
    assert display_number(92192744) == "92,192,744"
    assert display_number(1000) == "1,000"


# ==============================================================================
# 4. PROFILE REMOVE EXTRA RESOURCES FROM PRESENTATION
# ==============================================================================

def test_profile_html_does_not_render_extra_resources():
    basic = {
        "nickname": "测试指挥官", "lv": 300, "team_combat": 1000000,
        "currencies": [
            {"type": kind, "value": 50000} for kind in CurrencyRegistry.DEFINITIONS
        ] + [
            {"type": 99901, "value": 12345, "name": "未知诊断资源1"},
            {"type": 99902, "value": 67890, "name": "未知诊断资源2"},
        ]
    }
    profile_data = ProfileBuilder().build(account={}, basic=basic, outpost={}, daily={}, roster=None, fetched_at="2026-09-13 12:00", plugin_version="test")
    payload = ProfileT2IPayloadBuilder().build(profile_data)

    # Diagnostics still present in payload
    assert len(payload["extra_resources"]) > 0

    # But HTML presentation completely strips them
    html = render("profile", payload)
    assert "额外返回资源" not in html
    assert "未纳入八项资源区" not in html
    assert "未知诊断资源" not in html
    assert "未知资源" not in html

    # The 8 core resources are displayed with compact numbers
    for res in payload["resources"]:
        assert res["label"] in html
        assert res["value"] in html
        assert res["value"] == "50.0K"


# ==============================================================================
# 5. PROFILE PARTIAL STATUS SECTION-LEVEL ONLY
# ==============================================================================

def test_profile_partial_status_is_section_level_only():
    basic = {
        "nickname": "测试指挥官", "lv": 300, "team_combat": 1000000,
        "currencies": [{"type": kind, "value": 50000} for kind in CurrencyRegistry.DEFINITIONS]
    }
    daily = {
        "outpost_battle_storage_fullness": 0.5,
        "intercept_remaining_tickets": "unverified",
    }
    outpost = {
        "synchro_level": 300,
        "outpost_battle_level": 200,
        "infra_core_level": "20",
    }
    profile_data = ProfileBuilder().build(account={}, basic=basic, outpost=outpost, daily=daily, roster=None, fetched_at="2026-09-13 12:00", plugin_version="test")
    payload = ProfileT2IPayloadBuilder().build(profile_data)

    assert payload["today_state"] == "PARTIAL"

    html = render("profile", payload)

    # Section-level badge must exist
    assert '<span class="badge state-partial">PARTIAL</span>' in html

    # Individual rows/fields must NOT contain PARTIAL small tag
    assert '<small>PARTIAL</small>' not in html
    assert '<small>AVAILABLE</small>' not in html
    assert '<small>UNAVAILABLE</small>' not in html
    assert '<small>UNKNOWN</small>' not in html

    # Every PARTIAL badge must be inside a section-header or today-head
    for match in re.finditer(r'<span class="badge state-partial">PARTIAL</span>', html):
        prefix = html[:match.start()]
        assert "today-head" in prefix[-200:] or "section-header" in prefix[-200:]


# ==============================================================================
# 6. PROFILE TODAY TOWER RESOLUTION AND PRESENTATION
# ==============================================================================

def test_tower_registry_known_types_map_to_chinese_names():
    # Integer type mapping
    assert TowerRegistry.resolve_tower_name(1) == "极乐净土"
    assert TowerRegistry.resolve_tower_name(2) == "米西利斯"
    assert TowerRegistry.resolve_tower_name(3) == "泰特拉"
    assert TowerRegistry.resolve_tower_name(4) == "朝圣者"

    # String integer mapping
    assert TowerRegistry.resolve_tower_name("1") == "极乐净土"
    assert TowerRegistry.resolve_tower_name("2") == "米西利斯"
    assert TowerRegistry.resolve_tower_name("3") == "泰特拉"
    assert TowerRegistry.resolve_tower_name("4") == "朝圣者"

    # Canonical keys
    assert TowerRegistry.resolve_tower_name("elysion") == "极乐净土"
    assert TowerRegistry.resolve_tower_name("missilis") == "米西利斯"
    assert TowerRegistry.resolve_tower_name("tetra") == "泰特拉"
    assert TowerRegistry.resolve_tower_name("pilgrim") == "朝圣者"
    assert TowerRegistry.resolve_tower_name("tribe") == "无限塔"

    # Aliases
    assert TowerRegistry.resolve_tower_name("极乐净土") == "极乐净土"
    assert TowerRegistry.resolve_tower_name("极乐净土塔") == "极乐净土"
    assert TowerRegistry.resolve_tower_name("米西利斯塔") == "米西利斯"
    assert TowerRegistry.resolve_tower_name("泰特拉塔") == "泰特拉"
    assert TowerRegistry.resolve_tower_name("朝圣者塔") == "朝圣者"
    assert TowerRegistry.resolve_tower_name("无限塔") == "无限塔"


def test_tower_registry_unknown_type_and_builder_fallback():
    # Unknown types return None from registry
    assert TowerRegistry.resolve_tower_name(99) is None
    assert TowerRegistry.resolve_tower_name("future_tower") is None
    assert TowerRegistry.resolve_tower_name(None) is None

    # ProfileBuilder falls back to explicit 未知塔 · TYPE {type}
    data_num = ProfileBuilder().build(
        account={}, basic={}, outpost={},
        daily={"tower_daily_info_list": [{"type": 99, "is_opened": False, "remaining_count": 0}]},
        roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )
    assert data_num.tower_daily_info is not None
    assert len(data_num.tower_daily_info) == 1
    assert data_num.tower_daily_info[0].display_name == "未知塔 · TYPE 99"

    data_str = ProfileBuilder().build(
        account={}, basic={}, outpost={},
        daily={"tower_daily_info_list": [{"type": "alien", "is_opened": False, "remaining_count": 0}]},
        roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )
    assert data_str.tower_daily_info is not None
    assert data_str.tower_daily_info[0].display_name == "未知塔 · TYPE alien"

    # Missing type and missing name falls back to 未知塔
    data_none = ProfileBuilder().build(
        account={}, basic={}, outpost={},
        daily={"tower_daily_info_list": [{"is_opened": False, "remaining_count": 0}]},
        roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )
    assert data_none.tower_daily_info is not None
    assert data_none.tower_daily_info[0].display_name == "未知塔"


def test_api_explicit_name_takes_priority_over_registry():
    # If API provides name or tower_name, it overrides registry resolution
    data_name = ProfileBuilder().build(
        account={}, basic={}, outpost={},
        daily={"tower_daily_info_list": [{"type": 1, "name": "特异开放极乐塔", "is_opened": True, "remaining_count": 3}]},
        roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )
    assert data_name.tower_daily_info is not None
    assert data_name.tower_daily_info[0].display_name == "特异开放极乐塔"

    data_tower_name = ProfileBuilder().build(
        account={}, basic={}, outpost={},
        daily={"tower_daily_info_list": [{"type": 2, "tower_name": "米西利斯挑战", "is_opened": True, "remaining_count": 2}]},
        roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )
    assert data_tower_name.tower_daily_info is not None
    assert data_tower_name.tower_daily_info[0].display_name == "米西利斯挑战"


def test_profile_today_renders_four_distinct_tower_names_no_generic_record():
    # Real production shape: 4 items with type 1, 2, 3, 4 without name field
    daily = {
        "outpost_battle_storage_fullness": 0.5,
        "tower_daily_info_list": [
            {"type": 1, "is_opened": False, "remaining_count": 3},
            {"type": 2, "is_opened": False, "remaining_count": 3},
            {"type": 3, "is_opened": True, "remaining_count": 3},
            {"type": 4, "is_opened": False, "remaining_count": 3},
        ]
    }
    profile_data = ProfileBuilder().build(
        account={}, basic={"nickname": "指挥官"}, outpost={},
        daily=daily, roster=None, fetched_at="2026-09-13 12:00", plugin_version="test"
    )

    # 1. Check data models
    assert profile_data.tower_daily_info is not None
    assert len(profile_data.tower_daily_info) == 4
    names = [item.display_name for item in profile_data.tower_daily_info]
    assert names == ["极乐净土", "米西利斯", "泰特拉", "朝圣者"]

    # 2. Check T2I payload
    payload = ProfileT2IPayloadBuilder().build(profile_data)
    today_labels = [row["label"] for row in payload["today"]]
    assert "极乐净土" in today_labels
    assert "米西利斯" in today_labels
    assert "泰特拉" in today_labels
    assert "朝圣者" in today_labels
    assert "塔记录" not in today_labels

    # 3. Check rendered HTML
    html = render("profile", payload)
    assert "塔记录" not in html
    assert "极乐净土" in html
    assert "米西利斯" in html
    assert "泰特拉" in html
    assert "朝圣者" in html
    # Check statuses
    assert "未开放" in html
    assert "剩余 3" in html
