# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile Dashboard v0.4 单元测试与端到端渲染回归。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from astrbot_plugin_nikke.features.character.registries.memorial import MemorialCategoryRegistry
from astrbot_plugin_nikke.features.profile.builder import (
    ProfileBuilder,
    format_compact_number,
    _parse_storage_fullness,
    _parse_sim_room_record,
    _parse_currencies,
)
from astrbot_plugin_nikke.ui.renderers.profile import ProfileCardRenderer
from astrbot_plugin_nikke.features.profile.models import (
    CurrencyItem,
    MemorialCountData,
    ProfileDashboardData,
    RecycleResearchData,
    SimulationRoomDailyRecord,
)
from astrbot_plugin_nikke.features.character.registries.research import research_zh_name


class ProfileV04UnitTests(unittest.TestCase):
    def test_format_compact_number(self):
        self.assertEqual(format_compact_number(0), "0")
        self.assertEqual(format_compact_number(999), "999")
        self.assertEqual(format_compact_number(1000), "1K")
        self.assertEqual(format_compact_number(1500), "1.5K")
        self.assertEqual(format_compact_number(10000), "10K")
        self.assertEqual(format_compact_number(10497), "10.5K")
        self.assertEqual(format_compact_number(26000000), "26M")
        self.assertEqual(format_compact_number(26500000), "26.5M")
        self.assertEqual(format_compact_number(130000000), "130M")
        self.assertEqual(format_compact_number(None), "—")
        self.assertEqual(format_compact_number("invalid"), "—")

    def test_memorial_category_registry(self):
        registry = MemorialCategoryRegistry()
        raw_memorials = [
            MemorialCountData("HandWriting", 94),
            MemorialCountData("CallLog", 39),
            MemorialCountData("Data", 80),
            MemorialCountData("OldTales", 8),
            MemorialCountData("UnbreakableSphere", 4),
        ]
        summary, partial = registry.summarize(raw_memorials, jukebox_count=180)
        self.assertFalse(partial)
        self.assertEqual(
            [(item.display_name, item.count) for item in summary],
            [("手机", 94), ("通话记录", 39), ("数据资料", 92), ("BGM", 180)],
        )

        empty_summary, empty_partial = registry.summarize(None, jukebox_count=None)
        self.assertIsNone(empty_summary)
        self.assertFalse(empty_partial)

        unknown_summary, unknown_partial = registry.summarize(
            [MemorialCountData("Unmapped", 8)], jukebox_count=None
        )
        self.assertIsNone(unknown_summary)
        self.assertTrue(unknown_partial)

    def test_parse_storage_fullness(self):
        self.assertEqual(_parse_storage_fullness(0), 0.0)
        self.assertEqual(_parse_storage_fullness(0.059), 5.9)
        self.assertEqual(_parse_storage_fullness(0.0687727), 6.9)
        self.assertEqual(_parse_storage_fullness(1.0), 100.0)
        self.assertEqual(_parse_storage_fullness(15.5), 15.5)
        self.assertIsNone(_parse_storage_fullness(None))
        self.assertIsNone(_parse_storage_fullness("bad"))

    def test_parse_sim_room_record(self):
        self.assertEqual(_parse_sim_room_record({"chapter": 3, "difficulty": 5}), "5-C")
        self.assertEqual(_parse_sim_room_record({"chapter": 1, "difficulty": 4}), "4-A")
        self.assertEqual(_parse_sim_room_record({"chapter": 2, "difficulty": 5}), "5-B")
        self.assertIsNone(_parse_sim_room_record(None))
        self.assertIsNone(_parse_sim_room_record({}))

    def test_research_zh_name(self):
        self.assertEqual(research_zh_name("General"), "通用研究")
        self.assertEqual(research_zh_name("Attacker"), "火力型")
        self.assertEqual(research_zh_name("Defender"), "防御型")
        self.assertEqual(research_zh_name("Supporter"), "辅助型")
        self.assertEqual(research_zh_name("Elysion"), "极乐净土")
        self.assertEqual(research_zh_name("Missilis"), "米西里斯")
        self.assertEqual(research_zh_name("Tetra"), "泰特拉")
        self.assertEqual(research_zh_name("Pilgrim"), "朝圣者")
        self.assertEqual(research_zh_name("Abnormal"), "反常")
        self.assertEqual(research_zh_name("Unknown"), "Unknown")
        self.assertIsNone(research_zh_name(None))

    def test_parse_currencies(self):
        raw = [
            {"type": 99, "value": 50000},
            {"type": 1000, "value": 130000000},
            {"type": 2000, "value": 26000000},
            {"type": 3000, "value": 10497},
            {"type": 5100, "value": 50},
            {"type": 5200, "value": 120},
            {"type": 11000, "value": 3500},
            {"type": 12000, "value": 800},
        ]
        items = _parse_currencies(raw)
        self.assertEqual(len(items), 8)
        self.assertEqual(items[0].display_name, "珠宝")
        self.assertEqual(items[0].compact_value, "50K")
        self.assertEqual(items[1].display_name, "信用点")
        self.assertEqual(items[1].compact_value, "130M")
        self.assertEqual(items[2].display_name, "战斗数据辑")
        self.assertEqual(items[2].compact_value, "26M")
        self.assertEqual(items[3].display_name, "芯尘")
        self.assertEqual(items[3].compact_value, "10.5K")


class ProfileV04RendererTests(unittest.TestCase):
    def full_v04_dashboard(self):
        currencies = [
            CurrencyItem(99, 50000, "珠宝", "jewel", "50K"),
            CurrencyItem(1000, 130000000, "信用点", "credit", "130M"),
            CurrencyItem(2000, 26000000, "战斗数据辑", "battle_data", "26M"),
            CurrencyItem(3000, 10497, "芯尘", "core_dust", "10.5K"),
            CurrencyItem(5100, 50, "高级招募券", "advanced_ticket", "50"),
            CurrencyItem(5200, 120, "普通招募券", "recruit_ticket", "120"),
            CurrencyItem(11000, 3500, "躯体标签", "body_label", "3.5K"),
            CurrencyItem(12000, 800, "联盟芯片", "union_chip", "800"),
        ]
        return ProfileDashboardData(
            commander_name="实测指挥官",
            area_id="8",
            synchro_level=420,
            outpost_battle_level=100,
            normal_campaign="35-36",
            hard_campaign="25-10",
            character_count=150,
            max_level=420,
            max_combat=180000,
            fetched_at="2026-09-11 12:00",
            plugin_version="0.3.0",
            commander_level=450,
            team_combat=888888,
            created_at="2022-11-04",
            character_costume_count=35,
            progress_tribe_tower="450",
            sim_room_overclock_score="27",
            infra_core_level="25",
            daily_available=True,
            storage_fullness=6.9,
            intercept_remaining=0,
            rookie_arena_remaining=5,
            special_arena_remaining=0,
            counsel_remaining=10,
            dispatch_completed=3,
            dispatch_total=15,
            tower_daily_remaining=0,
            sim_room_daily_record=SimulationRoomDailyRecord(
                chapter=3, difficulty=5, raw={"chapter": 3, "difficulty": 5}
            ),
            sim_room_overclock_subseason=27,
            sim_room_overclock_season=27,
            currencies=currencies,
            memorial_summary=[
                MemorialCountData("phone", 94, "手机", "phone"),
                MemorialCountData("call_log", 39, "通话记录", "call_log"),
                MemorialCountData("data", 92, "数据资料", "data"),
                MemorialCountData("bgm", 180, "BGM", "bgm"),
            ],
            recycle_room_researches=[
                RecycleResearchData("1001", 120, 0, "General", "Personal"),
                RecycleResearchData("1101", 80, 50, "Attacker", "Class"),
                RecycleResearchData("1102", 80, 0, "Defender", "Class"),
                RecycleResearchData("1103", 80, 0, "Supporter", "Class"),
                RecycleResearchData("1201", 60, 0, "Elysion", "Corporation"),
                RecycleResearchData("1202", 60, 0, "Missilis", "Corporation"),
                RecycleResearchData("1203", 60, 0, "Tetra", "Corporation"),
                RecycleResearchData("1204", 60, 0, "Pilgrim", "Corporation"),
                RecycleResearchData("1205", 20, 0, "Abnormal", "Corporation"),
            ],
            outpost_available=True,
            roster_available=True,
        )

    def test_render_v04_card_height_and_sections(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            renderer = ProfileCardRenderer(Path(directory), root / "fonts")
            with patch.object(renderer, "_section_panel", wraps=renderer._section_panel) as panel:
                path = renderer.render_profile(self.full_v04_dashboard())

            titles = [call.args[2] for call in panel.call_args_list]
            self.assertEqual(
                titles,
                [
                    "BASIC + CAMPAIGN / 基本信息与主线",
                    "TODAY / 今日状态",
                    "OUTPOST + ROSTER / 前哨与妮姬",
                    "RECYCLE ROOM / 循环室",
                    "COLLECTION / 遗失物品",
                    "RESOURCES / 我的资源",
                    "MORE / 更多数据",
                ],
            )
            with Image.open(path) as img:
                self.assertEqual(img.width, 1200)
                # Height must be within 1500..2200
                self.assertGreaterEqual(img.height, 1500)
                self.assertLessEqual(img.height, 2200)
                print(f"Rendered v0.4 card height: {img.height}px")
